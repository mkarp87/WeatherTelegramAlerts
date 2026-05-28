# WeatherTelegramAlerts

WeatherTelegramAlerts monitors active National Weather Service alerts, routes new or changed alerts to Telegram chats, and displays current alerts plus recent alert events on a Flask web dashboard.

## Main features

- NWS active alert polling by county or zone code.
- Per-county Telegram chat routing.
- Global event blocking for tests or unwanted event types.
- Web dashboard at `/weatheralerts`.
- Event log page at `/weatheralerts/logs.html`.
- Per-alert all-clear messages that do not fire when an NWS fetch fails.
- Authenticated web log endpoint using `X-WeatherAlerts-Token`.
- SQLite event log storage.
- Dashboard NWS response caching.
- Systemd installer for Linux servers.

```

The installer will:

1. Install Python dependencies needed by the app.
2. Copy the application to `/opt/WeatherTelegramAlerts`.
3. Copy the private config to `/opt/WeatherTelegramAlerts/config.yaml`.
4. Create a Python virtual environment.
5. Ensure `/opt/WeatherTelegramAlerts/data` and `/opt/WeatherTelegramAlerts/logs` are writable by the service user.
6. Install two systemd services:
   - `weather-alerts.service` for Telegram/NWS polling.
   - `weather-alerts-web.service` for the web dashboard.
7. Start both services when `--start` is supplied.

Dashboard URL:

```text
http://SERVER_IP:8085/weatheralerts
```

## Updating an existing install

When `/opt/WeatherTelegramAlerts/config.yaml` already exists, update the app files and preserve that config with:

```bash
cd WeatherTelegramAlerts
sudo ./install.sh --start
```

For a quick repair of an existing `/opt/WeatherTelegramAlerts` install without reinstalling packages:

```bash
sudo ./scripts/repair_existing_install.sh
```

## Manual local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
python3 scripts/validate_config.py config.yaml
python3 webapp.py -c config.yaml --waitress
python3 WeatherAlerts.py -c config.yaml
```

Run one polling iteration and exit:

```bash
python3 WeatherAlerts.py -c config.yaml --once
```

## Service commands

```bash
sudo systemctl status weather-alerts.service
sudo systemctl status weather-alerts-web.service
sudo journalctl -u weather-alerts.service -f
sudo journalctl -u weather-alerts-web.service -f
sudo systemctl restart weather-alerts-web.service weather-alerts.service
```

## Configuration notes

`WeatherAlerts.UserAgent` should identify your application and include contact information or a project URL. NWS can use that value if they need to contact the operator of a client that is causing problems.

`Webapp.WebhookToken` must match in both the poller and web app because the poller POSTs logs to `/weatheralerts/log` using this header:

```text
X-WeatherAlerts-Token: YOUR_TOKEN
```

The installer copies your config to `/opt/WeatherTelegramAlerts/config.yaml` with restrictive file permissions and gives the service user ownership of `data/`, `logs/`, and `config.yaml`.

## What changed in this hardened version

- Replaced the unauthenticated web log endpoint with token validation.
- Removed browser-side unsafe HTML insertion from logs.
- Added SQLite persistence for web logs.
- Added per-zone/per-alert clear handling.
- Suppressed false all-clear messages when NWS fetches fail.
- Added atomic state writes.
- Added NWS User-Agent headers consistently.
- Added dashboard response caching.
- Added Telegram message chunking below Telegram's message-length limit.
- Added systemd installer and service files.
- Added private-config and runtime-state protection in `.gitignore`.
