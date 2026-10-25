"""Forward Reolink alert images containing people or animals."""

from __future__ import annotations

import hashlib
import imaplib
import logging
import os
import smtplib
import ssl
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import EmailMessage, Message
from email.policy import default
from email.utils import parsedate_to_datetime
from io import BytesIO
from pathlib import Path
from typing import Mapping

from PIL import Image

LOGGER = logging.getLogger("reolink_watcher")
CONNECTION_TIMEOUT = 30
ANIMAL_CLASSES = frozenset(
    {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
)


@dataclass(frozen=True)
class Config:
    imap_server: str
    imap_user: str
    imap_password: str
    smtp_server: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    target_email: str
    confidence_threshold: float
    archive_dir: Path
    poll_interval_seconds: int
    reconnect_delay_seconds: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        values = os.environ if env is None else env
        required = (
            "IMAP_SERVER",
            "IMAP_USER",
            "IMAP_PASSWORD",
            "SMTP_SERVER",
            "SMTP_PORT",
            "SMTP_USER",
            "SMTP_PASSWORD",
            "TARGET_EMAIL",
        )
        missing = [name for name in required if not values.get(name)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        try:
            smtp_port = int(values["SMTP_PORT"])
            confidence = float(values.get("CONFIDENCE_THRESHOLD", "0.5"))
            poll_interval = int(values.get("POLL_INTERVAL_SECONDS", "15"))
            reconnect_delay = int(values.get("RECONNECT_DELAY_SECONDS", "30"))
        except ValueError as error:
            raise ValueError("SMTP_PORT, CONFIDENCE_THRESHOLD, and interval settings must be numeric") from error

        if not 1 <= smtp_port <= 65535:
            raise ValueError("SMTP_PORT must be between 1 and 65535")
        if not 0 <= confidence <= 1:
            raise ValueError("CONFIDENCE_THRESHOLD must be between 0 and 1")
        if poll_interval < 1 or reconnect_delay < 1:
            raise ValueError("Polling and reconnect intervals must be positive integers")

        return cls(
            imap_server=values["IMAP_SERVER"],
            imap_user=values["IMAP_USER"],
            imap_password=values["IMAP_PASSWORD"],
            smtp_server=values["SMTP_SERVER"],
            smtp_port=smtp_port,
            smtp_user=values["SMTP_USER"],
            smtp_password=values["SMTP_PASSWORD"],
            target_email=values["TARGET_EMAIL"],
            confidence_threshold=confidence,
            archive_dir=Path(values.get("ARCHIVE_DIR", "/data/archive")),
            poll_interval_seconds=poll_interval,
            reconnect_delay_seconds=reconnect_delay,
        )


def classify_image(model: object, image_bytes: bytes, confidence_threshold: float) -> str | None:
    """Return person, animal, or None for an image's highest-priority alert."""
    with Image.open(BytesIO(image_bytes)) as image:
        predictions = model.predict(source=image.convert("RGB"), conf=confidence_threshold, verbose=False)

    if not predictions:
        return None

    result = predictions[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return None

    found_person = False
    found_animal = False
    names = getattr(result, "names", getattr(model, "names", {}))

    for box in boxes:
        class_id = int(_scalar(box.cls))
        confidence = float(_scalar(box.conf))
        if confidence < confidence_threshold:
            continue

        if isinstance(names, Mapping):
            class_name = names.get(class_id)
        elif 0 <= class_id < len(names):
            class_name = names[class_id]
        else:
            class_name = None
        if not isinstance(class_name, str):
            continue

        normalized_name = class_name.strip().lower()
        found_person |= normalized_name == "person"
        found_animal |= normalized_name in ANIMAL_CLASSES

    if found_person:
        return "person"
    if found_animal:
        return "animal"
    return None


def _scalar(value: object) -> float:
    item = getattr(value, "item", None)
    return float(item() if callable(item) else value)


def extract_jpeg_attachments(message: Message) -> list[tuple[str, bytes]]:
    attachments: list[tuple[str, bytes]] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        payload = part.get_payload(decode=True)
        if not payload or not payload.startswith(b"\xff\xd8"):
            continue
        filename = part.get_filename() or "camera-alert.jpg"
        attachments.append((Path(filename).name, payload))
    return attachments


def send_alert(config: Config, subject: str, image_name: str, image_bytes: bytes, alert_type: str) -> None:
    prefix = "[ALERT: Person]" if alert_type == "person" else "[ALERT: Animal]"
    email = EmailMessage()
    email["From"] = config.smtp_user
    email["To"] = config.target_email
    email["Subject"] = f"{prefix} {subject or 'Reolink camera alert'}"
    email.set_content(f"A {alert_type} was detected in a Reolink camera image.")
    email.add_attachment(
        image_bytes,
        maintype="image",
        subtype="jpeg",
        filename=image_name or "camera-alert.jpg",
    )

    context = ssl.create_default_context()
    with smtplib.SMTP(config.smtp_server, config.smtp_port, timeout=CONNECTION_TIMEOUT) as client:
        client.ehlo()
        client.starttls(context=context)
        client.ehlo()
        client.login(config.smtp_user, config.smtp_password)
        client.send_message(email)


def archive_image(
    archive_dir: Path,
    image_bytes: bytes,
    message_uid: str,
    message_id: str,
    part_number: int,
    received_at: datetime,
) -> Path:
    target = _archive_path(archive_dir, image_bytes, message_uid, message_id, part_number, received_at)
    target_dir = target.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return target

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target_dir, prefix=".incoming-", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(image_bytes)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return target


def process_message(imap: imaplib.IMAP4_SSL, config: Config, model: object, uid: str, raw_message: bytes) -> None:
    message = message_from_bytes(raw_message, policy=default)
    subject = str(message.get("Subject", "Reolink camera alert"))
    message_id = str(message.get("Message-ID", ""))
    received_at = _message_date(message)
    attachments = extract_jpeg_attachments(message)

    for part_number, (filename, image_bytes) in enumerate(attachments, start=1):
        alert_type = classify_image(model, image_bytes, config.confidence_threshold)
        if alert_type is None:
            continue

        archive_path = _archive_path(
            config.archive_dir, image_bytes, uid, message_id, part_number, received_at
        )
        if archive_path.exists():
            continue

        send_alert(config, subject, filename, image_bytes, alert_type)
        archive_image(config.archive_dir, image_bytes, uid, message_id, part_number, received_at)

    status, _ = imap.uid("STORE", uid, "+FLAGS.SILENT", "(\\Seen)")
    if status != "OK":
        raise imaplib.IMAP4.error(f"Could not mark message {uid} as processed")


def _archive_path(
    archive_dir: Path,
    image_bytes: bytes,
    message_uid: str,
    message_id: str,
    part_number: int,
    received_at: datetime,
) -> Path:
    uid_token = hashlib.sha256(message_uid.encode("utf-8")).hexdigest()[:12]
    message_token = hashlib.sha256((message_id or message_uid).encode("utf-8")).hexdigest()[:12]
    image_token = hashlib.sha256(image_bytes).hexdigest()[:12]
    return (
        archive_dir
        / received_at.strftime("%Y")
        / received_at.strftime("%m")
        / received_at.strftime("%d")
        / f"uid-{uid_token}-{message_token}-part-{part_number}-{image_token}.jpg"
    )


def _message_date(message: Message) -> datetime:
    date_header = message.get("Date")
    if date_header:
        try:
            received_at = parsedate_to_datetime(str(date_header))
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
            return received_at.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            LOGGER.warning("Invalid email Date header; using current UTC time")
    return datetime.now(timezone.utc)


def poll_once(config: Config, model: object) -> None:
    imap = imaplib.IMAP4_SSL(config.imap_server, timeout=CONNECTION_TIMEOUT)
    try:
        imap.login(config.imap_user, config.imap_password)
        status, _ = imap.select("INBOX")
        if status != "OK":
            raise imaplib.IMAP4.error("Could not select the INBOX mailbox")

        status, data = imap.uid("SEARCH", None, "UNSEEN")
        if status != "OK":
            raise imaplib.IMAP4.error("Could not search for unread messages")

        uids = data[0].split() if data and data[0] else []
        for uid_bytes in uids:
            uid = uid_bytes.decode("ascii")
            try:
                status, fetched = imap.uid("FETCH", uid, "(RFC822)")
                if status != "OK":
                    raise imaplib.IMAP4.error(f"Could not fetch message {uid}")
                raw_message = next(
                    (item[1] for item in fetched if isinstance(item, tuple) and isinstance(item[1], bytes)),
                    None,
                )
                if raw_message is None:
                    raise imaplib.IMAP4.error(f"Message {uid} had no RFC822 payload")
                process_message(imap, config, model, uid, raw_message)
            except Exception:
                LOGGER.exception("Failed to process unread IMAP message %s; it will be retried", uid)
    finally:
        try:
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            LOGGER.warning("IMAP logout failed")


def run_forever(config: Config, model: object) -> None:
    while True:
        try:
            poll_once(config, model)
            delay = config.poll_interval_seconds
        except Exception:
            LOGGER.exception("IMAP polling failed; reconnecting")
            delay = config.reconnect_delay_seconds
        time.sleep(delay)


def load_model() -> object:
    from ultralytics import YOLO

    return YOLO("yolov8n.pt")


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = Config.from_env()
    except ValueError as error:
        LOGGER.error("Invalid configuration: %s", error)
        raise SystemExit(2) from error

    try:
        model = load_model()
    except Exception:
        LOGGER.exception("Could not load the local yolov8n.pt model")
        raise SystemExit(1)
    LOGGER.info("Starting Reolink email alert watcher")
    run_forever(config, model)


if __name__ == "__main__":
    main()
