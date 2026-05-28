# WeatherTelegramAlerts

WeatherTelegramAlerts monitors active National Weather Service alerts, sends Telegram notifications by county, and provides a web dashboard for current alerts and recent event logs.

## Architecture

The application runs as one systemd service:

```text
weather-alerts.service
  /opt/WeatherTelegramAlerts/.venv/bin/python /opt/WeatherTelegramAlerts/app.py -c /opt/WeatherTelegramAlerts/config.yaml
```

The service starts the web dashboard and the embedded Telegram/NWS polling loop in the same process. There is no separate `weather-alerts-web.service`.

## Paths

```text
Application: /opt/WeatherTelegramAlerts
Config:      /opt/WeatherTelegramAlerts/config.yaml
Data:        /opt/WeatherTelegramAlerts/data
Logs:        /opt/WeatherTelegramAlerts/logs
Service:     weather-alerts.service
Dashboard:   http://SERVER_IP:8085/weatheralerts
```

## Requirements

- Ubuntu/Debian system with systemd
- Python 3.9 or newer
- Network access to `api.weather.gov` and the Telegram Bot API
- Telegram bot token
- Telegram chat IDs

The installer installs the required OS packages with `apt-get` when available.

## Install from GitHub

```bash
cd /opt
sudo git clone https://github.com/mkarp87/WeatherTelegramAlerts.git
cd /opt/WeatherTelegramAlerts
sudo ./install.sh --config /path/to/private/config.yaml --start
```

The private config is copied to:

```text
/opt/WeatherTelegramAlerts/config.yaml
```

For an existing install where `config.yaml` is already present:

```bash
cd /opt/WeatherTelegramAlerts
sudo git pull
sudo ./install.sh --start
```

The installer recreates `/opt/WeatherTelegramAlerts/.venv`, installs `requirements.txt`, fixes runtime permissions, initializes the SQLite log database, removes older split-service units, and installs `weather-alerts.service`.

## Service commands

```bash
sudo systemctl status weather-alerts.service
sudo journalctl -u weather-alerts.service -f
sudo systemctl restart weather-alerts.service
sudo systemctl stop weather-alerts.service
```

Confirm that the old web service is not running:

```bash
sudo systemctl status weather-alerts-web.service
```

It should be missing, disabled, or inactive.

## Configuration

Use `config.example.yaml` as the public template. Do not commit `config.yaml` or private configs.

Important settings:

```yaml
WeatherAlerts:
  PollInterval: 300
  StateFile: "data/last_alerts.json"
  UserAgent: "WeatherTelegramAlerts/2.1.4 (https://github.com/mkarp87/WeatherTelegramAlerts)"

Webapp:
  Host: "0.0.0.0"
  Port: 8085
  DirectLog: true
  LogDatabase: "data/alert_logs.sqlite3"
  Waitress: true
  LogoURL: ""
  LogoAlt: "NC4ES Weather Alerts"
```

`Alerting.CountyCodes` defines monitored NWS county or zone codes. `Alerting.CountyChatMap` maps each code to a Telegram chat. `Telegram.ChatID` is the fallback chat for unmapped counties.

Set `Webapp.LogoURL` to show a custom dashboard logo in the header. Leave it blank to use the built-in `NC` mark.

`Webapp.Waitress: true` runs the dashboard with Waitress, a production WSGI server for Flask.

## Manual validation

Validate the config:

```bash
/opt/WeatherTelegramAlerts/.venv/bin/python /opt/WeatherTelegramAlerts/scripts/validate_config.py /opt/WeatherTelegramAlerts/config.yaml
```

Run one poll cycle without starting the web server:

```bash
/opt/WeatherTelegramAlerts/.venv/bin/python /opt/WeatherTelegramAlerts/app.py -c /opt/WeatherTelegramAlerts/config.yaml --once
```

Run locally from a checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
python3 scripts/validate_config.py config.yaml
python3 app.py -c config.yaml
```

## Repair an existing install

```bash
cd /opt/WeatherTelegramAlerts
sudo ./scripts/repair_existing_install.sh
```

The repair script removes stale split-service units, recreates the virtual environment, reinstalls dependencies, rewrites `weather-alerts.service`, removes stale state temp files, fixes `data/` and `logs/` ownership, initializes the SQLite log database, and restarts the service.

## Repository safety

The repository ignores private and runtime files:

```text
config.yaml
config.*.private.yaml
.env
data/
logs/
last_alerts.json
*.sqlite3
*.sqlite3-*
.venv/
```

Keep Telegram tokens and real chat IDs out of GitHub.

## Compatibility wrappers

These entrypoints are retained:

```text
app.py            unified service entrypoint
WeatherAlerts.py poller-only compatibility wrapper
webapp.py        dashboard-only compatibility wrapper
```

Use `app.py` for normal service operation.
