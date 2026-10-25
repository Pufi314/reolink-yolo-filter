# Reolink email alert filter

## Files

- `watcher.py` — IMAP polling, YOLOv8 classification, and SMTP forwarding; camera images are not stored locally.
- `Dockerfile` and `docker-compose.yml` — CPU-only container build and model-configuration volume setup.
- `requirements.txt` — Python runtime dependencies.
- `.env.example` — configuration template; copy it to `.env` and fill in credentials.
- [Active PRD](001-reolink-email-security-filter.md) — behaviors and implementation decisions.

## Synology Container Manager setup

1. Create a shared folder for this service, then place the project files in a project directory under it. In Container Manager, create a **Project** from that directory using `docker-compose.yml`.
2. Copy `.env.example` to `.env`. Set the IMAP inbox, outgoing SMTP server and account, destination address, and detection confidence. Use an app password if your mail provider requires one. Keep `.env` private; it is excluded from Git.
3. Set `PUID` and `PGID` to the numeric user and group IDs that have read/write access to `data/model-cache`. Create that directory under the project directory and grant the account access.
4. Build and start the project. The image installs CPU-only PyTorch and downloads `yolov8n.pt` at build time. Only Ultralytics runtime configuration is mounted outside the container; alert photos are not saved by the service.
5. Check the project’s container logs in Container Manager. The service polls the INBOX and sends one email per qualifying JPEG attachment. Image bytes are held in memory while being processed and sent; there is no NAS photo archive.

To validate the Python code and tests locally, run:

```sh
python -m unittest discover -s tests -v
```
