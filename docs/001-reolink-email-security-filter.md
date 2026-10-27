Status: implementation

# Reolink Email Security Filter

## Overview

Build a standalone Python service for Synology NAS that monitors a dedicated Reolink alert inbox, classifies attached JPEG images with a local YOLOv8 Nano model, and forwards only person or animal alerts. Images are processed in memory and are not stored on the NAS.

## User stories

- As a camera owner, I want person detections forwarded promptly so I can respond to people at the remote site.
- As a camera owner, I want animal detections forwarded promptly while insects and other false triggers remain silent.
- As a camera owner, I want camera images classified and forwarded without creating local photo copies.
- As a Synology administrator, I want to configure and operate the service through Container Manager without putting credentials in the image.

## UI/UX

The service has no interactive UI. It exposes its status through container logs and is configured with a `.env` file and Docker Compose. The setup guide will explain configuring environment values, starting the container, and checking logs.

## Technical approach

- Python 3.11 slim container with `imaplib`, `smtplib`, Pillow, and `ultralytics`; use `yolov8n.pt` and CPU inference by default.
- Poll the configured IMAP inbox for unprocessed messages, parse MIME attachments, and evaluate each JPEG independently. Reconnect after transient failures with bounded connection timeouts and retry delay.
- Use SMTP with TLS and `SMTP_USER`/`SMTP_PASSWORD` to send a new email to `TARGET_EMAIL`, attaching the original image. Set the forwarded subject to only the recognized camera name in brackets (for example, `[Sprcha]`), extracted from the source subject.
- Use the model's COCO classes and `CONFIDENCE_THRESHOLD`. Forward an image if it contains any qualifying person or supported animal detection; do not distinguish between these detections in the email subject or body. Images with neither are discarded without notification.
- Recognize the five configured camera names (`Sprcha`, `Chata`, `Altanok`, `Sad`, `Gang`) as case-insensitive whole words in the incoming subject. If a name is found, use only that canonical name in brackets as the forwarded subject. Otherwise, preserve the original source subject.
- Keep image bytes in memory for inference and email delivery; do not create NAS photo copies.
- Persist only the Ultralytics runtime configuration/cache on the NAS. Camera images are not written to that mount.
- Configure IMAP and SMTP host/account settings, destination, and model confidence threshold through environment variables and Compose. `ANIMAL_STRIDE` is omitted because the user confirmed it was a mistake and all animal images must be analyzed.

### Decisions

- Chose not to store camera images on the NAS; images remain in memory only while being classified and sent.
- Keep a separate bind-mounted directory only for Ultralytics runtime configuration/cache; it does not contain alert photos.
- Chose authenticated SMTP with TLS; SMTP credentials are separate from the IMAP inbox credentials.
- Treat each JPEG attachment as an independent image and notification; do not skip animal images.
- Use only the camera name in the forwarded subject, with no alert-type label or original subject text.
- On a transient processing or delivery failure, leave the message unprocessed for retry. Delivery is best-effort and may duplicate a notification if SMTP accepted it but the connection failed before the service recorded success.

## Data model / state shape

- IMAP message: source mailbox identifier, message identifier, source subject, and zero or more JPEG attachments.
- Image result: attachment bytes, detected class names and confidence scores, and one outcome: qualifying person/animal alert or discard.
- Camera identity: one of `Sprcha`, `Chata`, `Altanok`, `Sad`, or `Gang`, parsed from the source email subject.
- Runtime configuration: IMAP server/user/password, SMTP server/port/user/password, target email, and confidence threshold. Secrets are supplied at runtime and not baked into the image.

## Behaviors

- `shouldForwardQualifyingCameraImagesWithCameraSubject`: Each image with a person or supported animal detection at or above the confidence threshold is sent to the destination with its recognized camera name in brackets as the subject, or the original source subject if no known name is found.
  Type: api
- `shouldDiscardImagesWithoutPersonOrAnimal`: Images containing only insects, shadows, tree motion, or other non-person/non-animal detections produce no notification.
  Type: api
- `shouldNotPersistCameraImagesOnNas`: Camera image bytes are used in memory for inference and email delivery but are never written to a NAS-mounted photo archive.
  Type: api
- `shouldRetryInboxProcessingAfterTransientNetworkFailure`: IMAP/SMTP timeouts or temporary network failures cause reconnection and retry without permanently consuming the source message.
  Type: api
- `shouldLoadRuntimeConfigurationFromEnvironment`: The service reads credentials, endpoints, destination, and confidence threshold at runtime and reports missing or invalid required configuration clearly.
  Type: api
- `shouldRunFromSynologyContainerManager`: The supplied Dockerfile and Compose configuration build and run the service with a documented environment-file setup and no photo archive mount.
  Type: api

## Out of scope

- Telegram notifications.
- NAS photo archiving or retention.
- Web dashboard, camera-side configuration, or cloud inference.
- GPU-specific acceleration.
- Notifications for objects outside person and supported COCO animal classes.

## Retrospective

- To be completed after implementation.
