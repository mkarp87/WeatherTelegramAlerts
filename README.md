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

## Repository safety

Do not commit your real `config.yaml`. It contains Telegram tokens, chat IDs, and webhook secrets.

This repository includes `config.example.yaml` only. Runtime files are ignored by `.gitignore`:

- `config.yaml`
- `config.*.private.yaml`
- `data/`
- `logs/`
- `last_alerts.json`
- SQLite database files

## Quick install from this ZIP

Unzip the project on the server, copy your private config file to the same server, then run:

```bash
cd WeatherTelegramAlerts
sudo ./install.sh --config /path/to/config.NC4ES.private.yaml --start
```

The installer will:

1. Install Python dependencies needed by the app.
2. Copy the application to `/opt/weathertelegramalerts`.
3. Copy the private config to `/etc/weathertelegramalerts/config.yaml`.
4. Create a Python virtual environment.
5. Install two systemd services:
   - `weatheralerts.service`
   - `weatheralerts-web.service`
6. Start both services when `--start` is supplied.

Dashboard URL:

```text
http://SERVER_IP:8085/weatheralerts
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
sudo systemctl status weatheralerts.service
sudo systemctl status weatheralerts-web.service
sudo journalctl -u weatheralerts.service -f
sudo journalctl -u weatheralerts-web.service -f
sudo systemctl restart weatheralerts-web.service weatheralerts.service
```

## Configuration notes

`WeatherAlerts.UserAgent` should identify your application and include contact information or a project URL. NWS can use that value if they need to contact the operator of a client that is causing problems.

`Webapp.WebhookToken` must match in both the poller and web app because the poller POSTs logs to `/weatheralerts/log` using this header:

```text
X-WeatherAlerts-Token: YOUR_TOKEN
```

The installer copies your config to `/etc/weathertelegramalerts/config.yaml` with restrictive file permissions.

## Uploading to GitHub

The ZIP is safe to upload as source because it does not include the private NC4ES config. To push with git from the unzipped directory:

```bash
./scripts/push_to_github.sh https://github.com/mkarp87/WeatherTelegramAlerts.git main
git commit -m "Harden WeatherTelegramAlerts deployment"
git push origin main
```

The push helper refuses to continue if `config.yaml` is present in the repository root.

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
