#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/WeatherTelegramAlerts}"
SERVICE_USER="${SERVICE_USER:-weatheralerts}"
CONFIG_PATH="${CONFIG_PATH:-$APP_DIR/config.yaml}"
POLL_SERVICE="weather-alerts.service"
WEB_SERVICE="weather-alerts-web.service"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo ./scripts/repair_existing_install.sh" >&2
  exit 1
fi

if [ ! -d "$APP_DIR" ]; then
  echo "Application directory not found: $APP_DIR" >&2
  exit 1
fi

if [ ! -f "$CONFIG_PATH" ]; then
  echo "Config file not found: $CONFIG_PATH" >&2
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

systemctl stop "$POLL_SERVICE" "$WEB_SERVICE" 2>/dev/null || true
systemctl stop weatheralerts.service weatheralerts-web.service 2>/dev/null || true
systemctl disable weatheralerts.service weatheralerts-web.service 2>/dev/null || true
rm -f /etc/systemd/system/weatheralerts.service /etc/systemd/system/weatheralerts-web.service

mkdir -p "$APP_DIR/data" "$APP_DIR/logs"
chown -R root:root "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data" "$APP_DIR/logs"
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_PATH"
chmod 600 "$CONFIG_PATH"
chmod 755 "$APP_DIR"

cat > /etc/systemd/system/$POLL_SERVICE <<EOF_SERVICE
[Unit]
Description=WeatherTelegramAlerts Telegram poller
After=network-online.target $WEB_SERVICE
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/WeatherAlerts.py -c $CONFIG_PATH
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF_SERVICE

cat > /etc/systemd/system/$WEB_SERVICE <<EOF_SERVICE
[Unit]
Description=WeatherTelegramAlerts web dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/webapp.py -c $CONFIG_PATH --waitress
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF_SERVICE

systemctl daemon-reload
systemctl enable "$WEB_SERVICE" "$POLL_SERVICE"
systemctl restart "$WEB_SERVICE" "$POLL_SERVICE"

echo "Repair complete."
echo "  Telegram poller: sudo systemctl status $POLL_SERVICE"
echo "  Web dashboard:    sudo systemctl status $WEB_SERVICE"
