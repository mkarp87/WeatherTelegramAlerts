# WeatherTelegramAlerts

WeatherTelegramAlerts monitors active National Weather Service alerts, sends Telegram notifications by county, and provides a web dashboard for current alerts, radar, and recent event logs.

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
Logs page:   http://SERVER_IP:8085/weatheralerts/logs.html
```

## Requirements

- Ubuntu/Debian system with systemd
- Python 3.9 or newer
- Network access to `api.weather.gov`, `api.telegram.org`, configured CDN URLs, configured map tile URL, and NOAA/NWS map services
- Telegram bot token
- Telegram chat IDs

The installer installs the required OS packages with `apt-get` when available.

## Install from GitHub

```bash
cd /opt
sudo git clone https://github.com/mkarp87/WeatherTelegramAlerts.git
cd /opt/WeatherTelegramAlerts

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

Core settings:

```yaml
WeatherAlerts:
  PollInterval: 300
  StateFile: "data/last_alerts.json"
  UserAgent: "WeatherTelegramAlerts/2.2.5 (https://github.com/mkarp87/WeatherTelegramAlerts)"

Telegram:
  BotToken: "PUT_YOUR_TELEGRAM_BOT_TOKEN_HERE"
  ChatID: "-1000000000000"

Webapp:
  Host: "0.0.0.0"
  Port: 8085
  DirectLog: true
  LogDatabase: "data/alert_logs.sqlite3"
  Waitress: true
  LogoURL: ""
  LogoAlt: "Weather Alerts"
```

`Alerting.CountyCodes` defines monitored NWS county or zone codes. `Alerting.CountyChatMap` maps each code to a Telegram chat. `Telegram.ChatID` is the fallback chat for unmapped counties.

`Alerting.CountyChatLinks` optionally makes county names clickable on the dashboard and event log page. Use public Telegram usernames, `t.me` links, or private invite links. Numeric Bot API chat IDs are not user-clickable Telegram links.

Set `Webapp.LogoURL` to show a custom dashboard logo in the header. Leave it blank to use the built-in `NC` mark.

`Webapp.Waitress: true` runs the dashboard with Waitress, a production WSGI server for Flask.

## Radar dashboard

The dashboard can display a configurable radar panel. Leaflet is loaded from the configured CDN URL, base map tiles are loaded from the configured tile URL, and radar reflectivity is loaded from an external NOAA/NCEP WMS layer.

The default radar mode is `wms`. This avoids the intermittent blank-image behavior that can occur with ArcGIS dynamic export layers in some browsers.

```yaml
Webapp:
  Radar:
    Enabled: true
    Title: "Eastern North Carolina Radar"
    Mode: "wms"
    Height: 620
    Opacity: 0.85
    RefreshSeconds: 300
    DefaultRegion: "eastern_nc"

    WmsURL: "https://opengeo.ncep.noaa.gov/geoserver/conus/conus_bref_qcd/ows"
    WmsLayers: "conus_bref_qcd"
    WmsVersion: "1.1.1"
    WmsFormat: "image/png"
    WmsStyles: ""
    WmsTransparent: true
    WmsTiled: true
    WmsUppercase: true

    LeafletCssURL: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    LeafletJsURL: "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    BaseTileURL: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    BaseTileAttribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    RadarAttribution: "NOAA/NWS/NCEP"
    SourceLabel: "NOAA/NCEP MRMS WMS"
    ScrollWheelZoom: false
    Regions:
      eastern_nc:
        Label: "Eastern NC"
        CenterLat: 35.35
        CenterLon: -77.25
        Zoom: 7
      pitt_craven:
        Label: "Pitt / Craven / Lenoir"
        CenterLat: 35.35
        CenterLon: -77.35
        Zoom: 9
```

The region selector on the dashboard is generated from `Webapp.Radar.Regions`. Blank map areas mean there are no radar returns at that location; they do not necessarily indicate a failed layer. If the WMS layer fails to load, the dashboard displays an error below the radar map.

Legacy ArcGIS mode remains available with `Mode: "arcgis"`, `ServiceURL`, and `LayerIds`, but WMS mode is the recommended default.

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
