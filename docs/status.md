# Project status

| Feature | PRD | Status |
|---------|-----|--------|
| Reolink email security filter | [001](001-reolink-email-security-filter.md) | implementation |

## Phase 2

- Behaviors done: combined person/animal forwarding, camera-name subjects with original-subject fallback, per-camera confidence overrides, multiple recipients, false-trigger discard, no local image persistence, environment validation, retry handling, Compose and Synology setup documentation.
- In progress: Docker build/runtime verification (Docker is unavailable in the current environment).
- Not started: user end-to-end run on Synology.
- Assumptions: authenticated SMTP with STARTTLS; all animal images are evaluated; camera names are matched case-insensitively as whole words; unspecified camera thresholds use the global threshold; every configured recipient receives all forwarded alerts; camera image bytes are not persisted on the NAS.
- Next action: build and run the container on a Docker host, then exercise each alert outcome against the configured mail services.
