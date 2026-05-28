# Changelog

## 2.1.4

- Initialized the SQLite log database during install and repair as the service user.
- Added clearer log-database permission errors.
- Prevented the logs page from returning a generic internal server error when the database cannot be opened.

## 2.1.2

- Made the installer use the system Python instead of an activated app virtualenv Python.
- Ensured `install.sh` still creates `/opt/WeatherTelegramAlerts/.venv` and installs `requirements.txt` when run from `/opt/WeatherTelegramAlerts`.
- Removed the explicit `--waitress` flag from the installed systemd command; Waitress remains enabled by `Webapp.Waitress: true`.
- Updated the README for GitHub-based installation and update workflows.

## 2.1.1

- Fixed `install.sh` when run from `/opt/WeatherTelegramAlerts` itself.
- Replaced the fragile `tar | tar` application copy step with a Python file copier.
- Preserved the venv creation, requirements installation, old-service cleanup, and runtime-permission checks after source-file copy.

## 2.1.0

- Collapsed the web dashboard and Telegram/NWS poller into one unified app process.
- Changed the installed service layout to one service only: `weather-alerts.service`.
- Removed the need for `weather-alerts-web.service`; the installer disables and removes it.
- Added `app.py` and `weather_alerts.unified` as the preferred entrypoint.
- Changed dashboard event logging so the embedded poller writes directly to SQLite by default instead of HTTP-posting back into the local web app.
- Added a service-user write test during install and repair to catch data/log permission problems before the service starts.
- Added stale `last_alerts.json.tmp` cleanup during install and repair.
- Improved state-write permission errors with an actionable message.

## 2.0.4

- Made `install.sh` explicitly recreate `/opt/WeatherTelegramAlerts/.venv` by default.
- Added installer progress output for venv creation, pip upgrades, requirements installation, and dependency import checks.
- Added source-directory validation so `install.sh` fails clearly when run outside the extracted project directory.
- Updated the existing-install repair script to recreate the venv and reinstall `requirements.txt` before restarting services.
- Added support for a self-contained installer artifact that embeds the app source.

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
- Added per-zone/per-alert clear messages.
- Preserved state when NWS fetches fail, preventing false all-clear messages.
- Added atomic JSON state file writes.
- Added consistent NWS User-Agent handling for poller and dashboard.
- Added dashboard cache controls and per-zone TTL caching.
- Added Telegram message chunking.
- Added installer, systemd service definitions, validation helper, and push helper.
