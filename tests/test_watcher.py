import io
import os
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

import watcher


def jpeg_bytes(color: str = "red") -> bytes:
    image = Image.new("RGB", (2, 2), color=color)
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


class FakeBox:
    def __init__(self, class_id: int, confidence: float):
        self.cls = class_id
        self.conf = confidence


class FakeModel:
    names = {0: "person", 1: "bird", 2: "dog", 3: "car"}

    def __init__(self, boxes):
        self.boxes = boxes

    def predict(self, **_kwargs):
        return [SimpleNamespace(boxes=self.boxes, names=self.names)]


class FakeImap:
    def __init__(self):
        self.calls = []

    def uid(self, *args):
        self.calls.append(args)
        return "OK", []


def config_for() -> watcher.Config:
    return watcher.Config(
        imap_server="imap.example.com",
        imap_user="inbox@example.com",
        imap_password="secret",
        smtp_server="smtp.example.com",
        smtp_port=587,
        smtp_user="sender@example.com",
        smtp_password="secret",
        target_email="recipient@example.com",
        confidence_threshold=0.5,
        poll_interval_seconds=15,
        reconnect_delay_seconds=30,
    )


class ClassificationTests(unittest.TestCase):
    def test_person_detection_takes_precedence_over_animal(self):
        model = FakeModel([FakeBox(1, 0.95), FakeBox(0, 0.8)])
        self.assertEqual(watcher.classify_image(model, jpeg_bytes(), 0.5), "person")

    def test_animal_detection_is_forwardable(self):
        model = FakeModel([FakeBox(2, 0.78)])
        self.assertEqual(watcher.classify_image(model, jpeg_bytes(), 0.5), "animal")

    def test_low_confidence_person_does_not_hide_animal(self):
        model = FakeModel([FakeBox(0, 0.2), FakeBox(1, 0.7)])
        self.assertEqual(watcher.classify_image(model, jpeg_bytes(), 0.5), "animal")

    def test_non_animal_detection_is_discarded(self):
        model = FakeModel([FakeBox(3, 0.99)])
        self.assertIsNone(watcher.classify_image(model, jpeg_bytes(), 0.5))


class MessageProcessingTests(unittest.TestCase):
    def test_each_qualifying_attachment_is_sent(self):
        email = EmailMessage()
        email["Subject"] = "Motion detected"
        email["Message-ID"] = "<camera-1@example.com>"
        email["Date"] = "Sun, 25 Oct 2026 12:00:00 +0000"
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes("red"), maintype="image", subtype="jpeg", filename="one.jpg")
        email.add_attachment(jpeg_bytes("blue"), maintype="image", subtype="jpeg", filename="two.jpg")
        imap = FakeImap()
        config = config_for()

        with patch.object(watcher, "classify_image", side_effect=["person", "animal"]) as classify:
            with patch.object(watcher, "send_alert") as send:
                watcher.process_message(imap, config, object(), "42", email.as_bytes())

        self.assertEqual(classify.call_count, 2)
        self.assertEqual([call.args[4] for call in send.call_args_list], ["person", "animal"])
        self.assertEqual(imap.calls[-1], ("STORE", "42", "+FLAGS.SILENT", "(\\Seen)"))

    def test_processing_does_not_write_images_to_disk(self):
        email = EmailMessage()
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes(), maintype="image", subtype="jpeg", filename="person.jpg")
        imap = FakeImap()
        config = config_for()

        with tempfile.TemporaryDirectory() as working_dir:
            original_cwd = Path.cwd()
            try:
                os.chdir(working_dir)
                with patch.object(watcher, "classify_image", return_value="person"):
                    with patch.object(watcher, "send_alert"):
                        watcher.process_message(imap, config, object(), "46", email.as_bytes())
                self.assertEqual(list(Path(working_dir).iterdir()), [])
            finally:
                os.chdir(original_cwd)

    def test_discarded_message_is_marked_processed_without_notification(self):
        email = EmailMessage()
        email["Subject"] = "Motion detected"
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes(), maintype="image", subtype="jpeg", filename="false-trigger.jpg")
        imap = FakeImap()
        config = config_for()

        with patch.object(watcher, "classify_image", return_value=None):
            with patch.object(watcher, "send_alert") as send:
                watcher.process_message(imap, config, object(), "43", email.as_bytes())

        send.assert_not_called()
        self.assertEqual(imap.calls[-1][0], "STORE")

    def test_delivery_failure_leaves_message_unprocessed(self):
        email = EmailMessage()
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes(), maintype="image", subtype="jpeg", filename="person.jpg")
        imap = FakeImap()
        config = config_for()

        with patch.object(watcher, "classify_image", return_value="person"):
            with patch.object(watcher, "send_alert", side_effect=OSError("SMTP unavailable")):
                with self.assertRaises(OSError):
                    watcher.process_message(imap, config, object(), "44", email.as_bytes())
        self.assertEqual(imap.calls, [])
        self.assertEqual(imap.calls, [])

    def test_alert_email_uses_class_prefix_and_authenticated_starttls(self):
        config = config_for()
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp

        with patch.object(watcher.smtplib, "SMTP", return_value=smtp):
            watcher.send_alert(config, "Motion detected", "camera.jpg", jpeg_bytes(), "person")

        sent_email = smtp.send_message.call_args.args[0]
        self.assertEqual(sent_email["Subject"], "[ALERT: Person] Motion detected")
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with(config.smtp_user, config.smtp_password)


class RetryTests(unittest.TestCase):
    def test_run_forever_retries_after_a_transient_poll_failure(self):
        config = config_for()
        with patch.object(watcher, "poll_once", side_effect=[OSError("offline"), None]) as poll:
            with patch.object(watcher.time, "sleep", side_effect=[None, KeyboardInterrupt]):
                with self.assertLogs(watcher.LOGGER.name, level="ERROR"):
                    with self.assertRaises(KeyboardInterrupt):
                        watcher.run_forever(config, object())

        self.assertEqual(poll.call_count, 2)


class ConfigurationTests(unittest.TestCase):
    def test_configuration_requires_credentials(self):
        with self.assertRaisesRegex(ValueError, "IMAP_SERVER"):
            watcher.Config.from_env({})

    def test_configuration_rejects_out_of_range_confidence(self):
        env = {
            "IMAP_SERVER": "imap.example.com",
            "IMAP_USER": "inbox@example.com",
            "IMAP_PASSWORD": "secret",
            "SMTP_SERVER": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASSWORD": "secret",
            "TARGET_EMAIL": "recipient@example.com",
            "CONFIDENCE_THRESHOLD": "1.1",
        }
        with self.assertRaisesRegex(ValueError, "CONFIDENCE_THRESHOLD"):
            watcher.Config.from_env(env)


if __name__ == "__main__":
    unittest.main()
