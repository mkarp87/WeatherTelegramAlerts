# Changelog

## 2.0.2

- Changed the default install path to `/opt/WeatherTelegramAlerts`.
- Changed the default config path to `/opt/WeatherTelegramAlerts/config.yaml`.
- Renamed systemd services to `weather-alerts.service` and `weather-alerts-web.service`.
- Corrected the web service so it starts `webapp.py` instead of the Telegram poller.
- Ensured `data/` and `logs/` under the app directory are owned by the service user to prevent state-write permission errors.
- Restyled the dashboard and event log pages with a darker card-based interface.
- Served dashboard static assets under `/weatheralerts/static` for better proxy compatibility.

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
