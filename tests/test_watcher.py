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
        target_emails=("recipient@example.com",),
        confidence_threshold=0.5,
        camera_confidence_thresholds={"Chata": 0.3},
        poll_interval_seconds=15,
        reconnect_delay_seconds=30,
    )


class ClassificationTests(unittest.TestCase):
    def test_person_detection_is_forwardable(self):
        model = FakeModel([FakeBox(0, 0.8)])
        self.assertTrue(watcher.has_qualifying_detection(model, jpeg_bytes(), 0.5))

    def test_person_and_animal_detections_both_match(self):
        model = FakeModel([FakeBox(1, 0.95), FakeBox(0, 0.8)])
        self.assertTrue(watcher.has_qualifying_detection(model, jpeg_bytes(), 0.5))

    def test_animal_detection_is_forwardable(self):
        model = FakeModel([FakeBox(2, 0.78)])
        self.assertTrue(watcher.has_qualifying_detection(model, jpeg_bytes(), 0.5))

    def test_low_confidence_person_is_not_a_qualifying_detection(self):
        model = FakeModel([FakeBox(0, 0.2)])
        self.assertFalse(watcher.has_qualifying_detection(model, jpeg_bytes(), 0.5))

    def test_non_animal_detection_is_discarded(self):
        model = FakeModel([FakeBox(3, 0.99)])
        self.assertFalse(watcher.has_qualifying_detection(model, jpeg_bytes(), 0.5))


class ForwardedSubjectTests(unittest.TestCase):
    def test_uses_camera_only_subject_for_each_known_camera(self):
        subjects = {
            "An alarm from Sprcha.": "Sprcha",
            "PIR Alarm for Chata at 12:00": "Chata",
            "An alarm from Altanok.": "Altanok",
            "[PIR] Detected from Sad at 12:00": "Sad",
            "An alarm from Gang.": "Gang",
        }
        for subject, camera_name in subjects.items():
            with self.subTest(subject=subject):
                self.assertEqual(watcher.forwarded_subject_from_source(subject), f"[{camera_name}]")

    def test_falls_back_to_original_subject_if_camera_name_is_missing(self):
        source_subject = "Unknown camera triggered at 12:00"
        self.assertEqual(watcher.forwarded_subject_from_source(source_subject), source_subject)

    def test_camera_name_matching_is_case_insensitive_and_requires_whole_word(self):
        self.assertEqual(watcher.forwarded_subject_from_source("pir alarm for cHaTa"), "[Chata]")
        source_subject = "An alarm from Chatan"
        self.assertEqual(watcher.forwarded_subject_from_source(source_subject), source_subject)


class MessageProcessingTests(unittest.TestCase):
    def test_each_qualifying_attachment_is_sent(self):
        email = EmailMessage()
        email["Subject"] = "An alarm from Sprcha."
        email["Message-ID"] = "<camera-1@example.com>"
        email["Date"] = "Sun, 25 Oct 2026 12:00:00 +0000"
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes("red"), maintype="image", subtype="jpeg", filename="one.jpg")
        email.add_attachment(jpeg_bytes("blue"), maintype="image", subtype="jpeg", filename="two.jpg")
        imap = FakeImap()
        config = config_for()

        with patch.object(watcher, "has_qualifying_detection", side_effect=[True, True]) as classify:
            with patch.object(watcher, "send_alert") as send:
                watcher.process_message(imap, config, object(), "42", email.as_bytes())

        self.assertEqual(classify.call_count, 2)
        self.assertEqual([call.args[2] for call in classify.call_args_list], [0.5, 0.5])
        self.assertEqual([call.args[1] for call in send.call_args_list], ["[Sprcha]", "[Sprcha]"])
        self.assertEqual(imap.calls[-1], ("STORE", "42", "+FLAGS.SILENT", "(\\Seen)"))

    def test_camera_threshold_override_is_used_for_each_image(self):
        email = EmailMessage()
        email["Subject"] = "PIR Alarm for Chata at 12:00"
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes(), maintype="image", subtype="jpeg", filename="animal.jpg")
        imap = FakeImap()
        config = config_for()

        with patch.object(watcher, "has_qualifying_detection", return_value=True) as classify:
            with patch.object(watcher, "send_alert"):
                watcher.process_message(imap, config, object(), "48", email.as_bytes())

        self.assertEqual(classify.call_args.args[2], 0.3)

    def test_unknown_camera_uses_default_confidence_threshold(self):
        email = EmailMessage()
        email["Subject"] = "Unknown camera triggered"
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes(), maintype="image", subtype="jpeg", filename="animal.jpg")
        imap = FakeImap()
        config = config_for()

        with patch.object(watcher, "has_qualifying_detection", return_value=True) as classify:
            with patch.object(watcher, "send_alert"):
                watcher.process_message(imap, config, object(), "49", email.as_bytes())

        self.assertEqual(classify.call_args.args[2], config.confidence_threshold)

    def test_processing_does_not_write_images_to_disk(self):
        email = EmailMessage()
        email["Subject"] = "An alarm from Sprcha."
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes(), maintype="image", subtype="jpeg", filename="person.jpg")
        imap = FakeImap()
        config = config_for()

        with tempfile.TemporaryDirectory() as working_dir:
            original_cwd = Path.cwd()
            try:
                os.chdir(working_dir)
                with patch.object(watcher, "has_qualifying_detection", return_value=True):
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

        with patch.object(watcher, "has_qualifying_detection", return_value=False):
            with patch.object(watcher, "send_alert") as send:
                watcher.process_message(imap, config, object(), "43", email.as_bytes())

        send.assert_not_called()
        self.assertEqual(imap.calls[-1][0], "STORE")

    def test_unknown_camera_subject_is_forwarded_unchanged(self):
        email = EmailMessage()
        email["Subject"] = "An alarm from Garage."
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes(), maintype="image", subtype="jpeg", filename="animal.jpg")
        imap = FakeImap()
        config = config_for()

        with patch.object(watcher, "has_qualifying_detection", return_value=True):
            with patch.object(watcher, "send_alert") as send:
                watcher.process_message(imap, config, object(), "47", email.as_bytes())

        self.assertEqual(send.call_args.args[1], "An alarm from Garage.")
        self.assertEqual(imap.calls[-1][0], "STORE")

    def test_delivery_failure_leaves_message_unprocessed(self):
        email = EmailMessage()
        email.set_content("Camera alert")
        email.add_attachment(jpeg_bytes(), maintype="image", subtype="jpeg", filename="person.jpg")
        imap = FakeImap()
        config = config_for()

        with patch.object(watcher, "has_qualifying_detection", return_value=True):
            with patch.object(watcher, "send_alert", side_effect=OSError("SMTP unavailable")):
                with self.assertRaises(OSError):
                    email["Subject"] = "PIR Alarm for Chata at 12:00"
                    watcher.process_message(imap, config, object(), "44", email.as_bytes())
            self.assertEqual(imap.calls, [])

    def test_alert_email_uses_camera_only_subject_and_authenticated_starttls(self):
        config = config_for()
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp

        with patch.object(watcher.smtplib, "SMTP", return_value=smtp):
            watcher.send_alert(config, "[Gang]", "camera.jpg", jpeg_bytes())

        sent_email = smtp.send_message.call_args.args[0]
        self.assertEqual(sent_email["Subject"], "[Gang]")
        self.assertNotIn("ALERT", sent_email["Subject"])
        self.assertNotIn("Motion detected", sent_email["Subject"])
        body = sent_email.get_body(preferencelist=("plain",)).get_content()
        self.assertNotIn("person", body)
        self.assertNotIn("animal", body)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with(config.smtp_user, config.smtp_password)
        smtp.send_message.assert_called_once_with(
            sent_email, to_addrs=config.target_emails
        )


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
    def valid_env(self):
        return {
            "IMAP_SERVER": "imap.example.com",
            "IMAP_USER": "inbox@example.com",
            "IMAP_PASSWORD": "secret",
            "SMTP_SERVER": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "sender@example.com",
            "SMTP_PASSWORD": "secret",
            "TARGET_EMAIL": "one@example.com, two@example.com",
        }

    def test_configuration_requires_credentials(self):
        with self.assertRaisesRegex(ValueError, "IMAP_SERVER"):
            watcher.Config.from_env({})

    def test_configuration_parses_multiple_recipients_and_camera_thresholds(self):
        env = self.valid_env()
        env["CAMERA_CONFIDENCE_THRESHOLDS"] = "Sprcha:0.2, Chata:0.35"

        config = watcher.Config.from_env(env)

        self.assertEqual(config.target_emails, ("one@example.com", "two@example.com"))
        self.assertEqual(config.camera_confidence_thresholds, {"Sprcha": 0.2, "Chata": 0.35})

    def test_configuration_accepts_one_recipient(self):
        env = self.valid_env()
        env["TARGET_EMAIL"] = "one@example.com"

        self.assertEqual(watcher.Config.from_env(env).target_emails, ("one@example.com",))

    def test_configuration_rejects_unknown_camera_threshold(self):
        env = self.valid_env()
        env["CAMERA_CONFIDENCE_THRESHOLDS"] = "Garage:0.3"

        with self.assertRaisesRegex(ValueError, "CAMERA_CONFIDENCE_THRESHOLDS"):
            watcher.Config.from_env(env)

    def test_configuration_rejects_out_of_range_camera_threshold(self):
        env = self.valid_env()
        env["CAMERA_CONFIDENCE_THRESHOLDS"] = "Sprcha:1.1"

        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            watcher.Config.from_env(env)

    def test_configuration_rejects_out_of_range_confidence(self):
        env = self.valid_env()
        env["CONFIDENCE_THRESHOLD"] = "1.1"
        with self.assertRaisesRegex(ValueError, "CONFIDENCE_THRESHOLD"):
            watcher.Config.from_env(env)


if __name__ == "__main__":
    unittest.main()
