# Reolink email alert filter

## Files

- `watcher.py` — IMAP polling, YOLOv8 classification, and SMTP forwarding; camera images are not stored locally.
- `Dockerfile` and `docker-compose.yml` — CPU-only container build and model-configuration volume setup.
- `requirements.txt` — Python runtime dependencies.
- `.env.example` — configuration template; copy it to `.env` and fill in credentials.
- [Active PRD](001-reolink-email-security-filter.md) — behaviors and implementation decisions.

## Synology Container Manager setup

1. Create a shared folder for this service, then place the project files in a project directory under it. In Container Manager, create a **Project** from that directory using `docker-compose.yml`.
2. In File Station, copy `.env.example` to a file named `.env` in the project directory, then open `.env` in a text editor and replace the example values:
   - `IMAP_SERVER` is the mail provider's IMAP hostname (typically TLS port 993); `IMAP_USER` is the dedicated camera-alert inbox address, and `IMAP_PASSWORD` is that inbox's password or app password. Enable IMAP access for the mailbox if the provider requires it.
   - `SMTP_SERVER` is the provider's authenticated outgoing-mail hostname; `SMTP_PORT` should be its STARTTLS submission port, commonly `587`. This service uses STARTTLS, not implicit-TLS port `465`. `SMTP_USER` and `SMTP_PASSWORD` are the credentials for that sending account; they can differ from the IMAP credentials.
   - `TARGET_EMAIL` is the recipient list for forwarded alerts. Separate multiple addresses with commas, for example `you@example.com, family@example.com`; each qualifying alert goes to every listed recipient.
   - `CONFIDENCE_THRESHOLD` is the default detection threshold, between `0.0` and `1.0` (for example, `0.5`). You can override it for individual cameras with `CAMERA_CONFIDENCE_THRESHOLDS`, using comma-separated `CameraName:value` pairs, such as `Sprcha:0.3,Chata:0.4`. Use only the configured names `Sprcha`, `Chata`, `Altanok`, `Sad`, and `Gang`; omitted cameras use the default. Lower values are more permissive and may forward more borderline detections; higher values are stricter and may reduce false alerts.
   - If your account uses multi-factor authentication, create a provider-approved app password for IMAP and SMTP rather than using your normal sign-in password. The optional `POLL_INTERVAL_SECONDS` and `RECONNECT_DELAY_SECONDS` control inbox polling and retry delays.

   Keep the real `.env` private; Compose loads it into the container and `.gitignore` excludes it from Git. Do not start the service with the untouched example credentials.
3. The repository includes `data/model-cache` for the Ultralytics runtime configuration bind mount. Keep that folder beside `docker-compose.yml` when copying the project to the NAS. Set `PUID` and `PGID` to the numeric user and group IDs that have read/write access to it, then grant that account access in File Station.
4. Build and start the project. The image installs CPU-only PyTorch and downloads `yolov8n.pt` at build time. Only Ultralytics runtime configuration is mounted outside the container; alert photos are not saved by the service.
5. Check the project’s container logs in Container Manager. The service polls the INBOX and sends one email per qualifying JPEG attachment, using the camera name alone (for example, `[Sprcha]`) as the subject when recognized, or preserving the original subject otherwise. Image bytes are held in memory while being processed and sent; there is no NAS photo archive.

To validate the Python code and tests locally, run:

```sh
python -m unittest discover -s tests -v
```
