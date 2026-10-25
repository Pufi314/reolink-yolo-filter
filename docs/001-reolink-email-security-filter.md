Status: exploration

# Reolink Email Security Filter

## Overview

Build a standalone Python service for Synology NAS that monitors a dedicated Reolink alert inbox, classifies attached JPEG images with a local YOLOv8 Nano model, and forwards only person or animal alerts. Successfully forwarded images are archived on a NAS-mounted shared folder.

## User stories

- As a camera owner, I want person detections forwarded promptly so I can respond to people at the remote site.
- As a camera owner, I want animal detections forwarded promptly while insects and other false triggers remain silent.
- As a camera owner, I want qualifying alert photos kept on my NAS independently of the container lifecycle.
- As a Synology administrator, I want to configure and operate the service through Container Manager without putting credentials in the image.

## UI/UX

The service has no interactive UI. It exposes its status through container logs and is configured with a `.env` file and Docker Compose. The setup guide will explain creating a persistent NAS archive folder, configuring environment values, starting the container, and checking logs.

## Technical approach

- Python 3.11 slim container with `imaplib`, `smtplib`, Pillow, and `ultralytics`; use `yolov8n.pt` and CPU inference by default.
- Poll the configured IMAP inbox for unprocessed messages, parse MIME attachments, and evaluate each JPEG independently. Reconnect after transient failures with bounded connection timeouts and retry delay.
- Use SMTP with TLS and `SMTP_USER`/`SMTP_PASSWORD` to send a new email to `TARGET_EMAIL`, attaching the original image. Use the source subject with `[ALERT: Person]` or `[ALERT: Animal]` prepended.
- Use the model's COCO classes and `CONFIDENCE_THRESHOLD`. A qualifying person detection takes precedence over animal detections in the same image; otherwise any qualifying animal class results in an animal alert. Images with neither are discarded without notification.
- Mount a host shared-folder path into the container at `/data/archive`. Store successfully forwarded images beneath date-based directories; do not automatically delete archived images.
- Configure the requested IMAP and SMTP host/account settings, destination, model confidence threshold, and archive path through environment variables and Compose. `ANIMAL_STRIDE` is omitted because the user confirmed it was a mistake and all animal images must be analyzed.

### Decisions

- Chose a bind-mounted Synology shared folder for archives so images persist outside the container and are directly manageable by NAS tools.
- Archive only person/animal images after successful forwarding; do not retain false triggers.
- Chose date-based folders and no automatic retention cleanup to avoid deleting user data without an agreed retention policy.
- Chose authenticated SMTP with TLS; SMTP credentials are separate from the IMAP inbox credentials.
- Treat each JPEG attachment as an independent image and notification; do not skip animal images.
- On a transient processing or delivery failure, leave the message unprocessed for retry. Delivery is best-effort and may duplicate a notification if SMTP accepted it but the connection failed before the service recorded success.

## Data model / state shape

- IMAP message: source mailbox identifier, message identifier, source subject, and zero or more JPEG attachments.
- Image result: attachment bytes, detected class names and confidence scores, and one outcome: person alert, animal alert, or discard.
- Archive path: `/data/archive/YYYY/MM/DD/` with a collision-safe image filename derived from the message and attachment.
- Runtime configuration: IMAP server/user/password, SMTP server/port/user/password, target email, confidence threshold, and mounted archive location. Secrets are supplied at runtime and not baked into the image.

## Behaviors

- `shouldForwardEveryImageWithPersonDetection`: Each image with a person detection at or above the confidence threshold is sent to the destination with `[ALERT: Person]` prepended to the subject.
  Type: api
- `shouldForwardEveryImageWithAnimalDetection`: Each image with a supported animal detection and no qualifying person detection is sent with `[ALERT: Animal]` prepended to the subject.
  Type: api
- `shouldDiscardImagesWithoutPersonOrAnimal`: Images containing only insects, shadows, tree motion, or other non-person/non-animal detections produce no notification and are not archived.
  Type: api
- `shouldArchiveSuccessfullyForwardedAlertImages`: Every successfully forwarded person/animal image is persisted in the mounted date-based archive; false triggers and failed deliveries are not archived.
  Type: api
- `shouldRetryInboxProcessingAfterTransientNetworkFailure`: IMAP/SMTP timeouts or temporary network failures cause reconnection and retry without permanently consuming the source message.
  Type: api
- `shouldLoadRuntimeConfigurationFromEnvironment`: The service reads credentials, endpoints, destination, and confidence threshold at runtime and reports missing or invalid required configuration clearly.
  Type: api
- `shouldRunFromSynologyContainerManager`: The supplied Dockerfile and Compose configuration build and run the service with a persistent archive mount and a documented environment-file setup.
  Type: api

## Out of scope

- Telegram notifications.
- Automatic archive retention/deletion policy.
- Web dashboard, camera-side configuration, or cloud inference.
- GPU-specific acceleration.
- Notifications for objects outside person and supported COCO animal classes.

## Retrospective

- To be completed after implementation.
