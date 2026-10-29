"""Forward Reolink alert images containing people or animals."""

from __future__ import annotations

import imaplib
import logging
import os
import re
import smtplib
import ssl
import time
from dataclasses import dataclass
from email import message_from_bytes
from email.message import EmailMessage, Message
from email.policy import default
from io import BytesIO
from pathlib import Path
from typing import Mapping

from PIL import Image

LOGGER = logging.getLogger("reolink_watcher")
CONNECTION_TIMEOUT = 30
ANIMAL_CLASSES = frozenset(
    {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
)
CAMERA_NAMES = ("Sprcha", "Chata", "Altanok", "Sad", "Gang")
CAMERA_NAME_PATTERN = re.compile(
    rf"(?<!\w)({'|'.join(CAMERA_NAMES)})(?!\w)",
    re.IGNORECASE,
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
    target_emails: tuple[str, ...]
    confidence_threshold: float
    camera_confidence_thresholds: Mapping[str, float]
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
            raise ValueError(
                "SMTP_PORT, CONFIDENCE_THRESHOLD, and interval settings must be numeric"
            ) from error
        camera_thresholds = _parse_camera_thresholds(values.get("CAMERA_CONFIDENCE_THRESHOLDS", ""))

        target_emails = tuple(address.strip() for address in values["TARGET_EMAIL"].split(",") if address.strip())
        if not target_emails:
            raise ValueError("TARGET_EMAIL must contain at least one recipient address")

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
            target_emails=target_emails,
            confidence_threshold=confidence,
            camera_confidence_thresholds=camera_thresholds,
            poll_interval_seconds=poll_interval,
            reconnect_delay_seconds=reconnect_delay,
        )


def _parse_camera_thresholds(value: str) -> dict[str, float]:
    thresholds: dict[str, float] = {}
    known_names = {name.casefold(): name for name in CAMERA_NAMES}
    for entry in value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            camera_name, raw_threshold = entry.split(":", maxsplit=1)
            canonical_name = known_names[camera_name.strip().casefold()]
            threshold = float(raw_threshold.strip())
        except (ValueError, KeyError) as error:
            raise ValueError(
                f"Invalid CAMERA_CONFIDENCE_THRESHOLDS entry {entry!r}; "
                "expected CameraName:0.0-1.0 for a configured camera"
            ) from error
        if not 0 <= threshold <= 1:
            raise ValueError(f"Threshold for {canonical_name} must be between 0 and 1")
        if canonical_name in thresholds:
            raise ValueError(f"Duplicate confidence threshold for camera {canonical_name}")
        thresholds[canonical_name] = threshold
    return thresholds


def has_qualifying_detection(model: object, image_bytes: bytes, confidence_threshold: float) -> bool:
    """Return whether an image contains a qualifying person or animal."""
    with Image.open(BytesIO(image_bytes)) as image:
        predictions = model.predict(source=image.convert("RGB"), conf=confidence_threshold, verbose=False)

    if not predictions:
        return False

    result = predictions[0]
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return False

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
        if normalized_name == "person" or normalized_name in ANIMAL_CLASSES:
            return True
    return False


def forwarded_subject_from_source(source_subject: str) -> str:
    camera_name = camera_name_from_subject(source_subject)
    if camera_name is None:
        return source_subject or "Reolink camera alert"

    return f"[{camera_name}]"


def camera_name_from_subject(source_subject: str) -> str | None:
    match = CAMERA_NAME_PATTERN.search(source_subject)
    if match is None:
        return None
    return next(name for name in CAMERA_NAMES if name.casefold() == match.group(1).casefold())


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


def send_alert(config: Config, subject: str, image_name: str, image_bytes: bytes) -> None:
    email = EmailMessage()
    email["From"] = config.smtp_user
    email["To"] = ", ".join(config.target_emails)
    email["Subject"] = subject
    email.set_content("A Reolink camera image matched the alert filter.")
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
        client.send_message(email, to_addrs=config.target_emails)


def process_message(imap: imaplib.IMAP4_SSL, config: Config, model: object, uid: str, raw_message: bytes) -> None:
    message = message_from_bytes(raw_message, policy=default)
    subject = str(message.get("Subject") or "Reolink camera alert")
    attachments = extract_jpeg_attachments(message)
    camera_name = camera_name_from_subject(subject)
    forwarded_subject = forwarded_subject_from_source(subject)
    confidence_threshold = config.camera_confidence_thresholds.get(
        camera_name, config.confidence_threshold
    )

    for filename, image_bytes in attachments:
        if not has_qualifying_detection(model, image_bytes, confidence_threshold):
            continue

        send_alert(config, forwarded_subject, filename, image_bytes)

    status, _ = imap.uid("STORE", uid, "+FLAGS.SILENT", "(\\Seen)")
    if status != "OK":
        raise imaplib.IMAP4.error(f"Could not mark message {uid} as processed")


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
