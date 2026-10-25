# Reolink email alert filter

## Files

- `watcher.py` — IMAP polling, YOLOv8 classification, SMTP forwarding, and image archiving.
- `Dockerfile` and `docker-compose.yml` — CPU-only container build and NAS volume setup.
- `requirements.txt` — Python runtime dependencies.
- `.env.example` — configuration template; copy it to `.env` and fill in credentials.
- [Active PRD](001-reolink-email-security-filter.md) — behaviors and implementation decisions.

## Synology Container Manager setup

1. Create a shared folder for this service, then place the project files in a project directory under it. In Container Manager, create a **Project** from that directory using `docker-compose.yml`.
2. Copy `.env.example` to `.env`. Set the IMAP inbox, outgoing SMTP server and account, destination address, and detection confidence. Use an app password if your mail provider requires one. Keep `.env` private; it is excluded from Git.
3. Set `PUID` and `PGID` to the numeric user and group IDs that have read/write access to the project’s `data` directory. Create `data/archive` and `data/model-cache` under the project directory and grant that account access.
4. Build and start the project. The image installs CPU-only PyTorch and downloads `yolov8n.pt` at build time; the forwarded alert images and Ultralytics runtime configuration are mounted outside the container.
5. Check the project’s container logs in Container Manager. The service polls the INBOX, sends one email per qualifying JPEG attachment, and stores successfully forwarded images in `data/archive/YYYY/MM/DD/`. No automatic archive deletion is configured.

To validate the Python code and tests locally, run:

```sh
python -m unittest discover -s tests -v
```
