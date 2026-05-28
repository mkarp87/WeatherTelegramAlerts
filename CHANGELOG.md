# Changelog

## 2.0.0

- Hardened `/weatheralerts/log` with webhook token authentication.
- Added SQLite-backed log persistence.
- Added safer dashboard templates with escaped content.
- Added per-alert clear messages.
- Preserved state when NWS fetches fail, preventing false all-clear messages.
- Added atomic JSON state file writes.
- Added consistent NWS User-Agent handling for poller and dashboard.
- Added dashboard cache controls and per-zone TTL caching.
- Added Telegram message chunking.
- Added installer, systemd service definitions, validation helper, and push helper.
