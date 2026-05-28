#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/WeatherTelegramAlerts"
CONFIG_PATH="$APP_DIR/config.yaml"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo ./uninstall.sh" >&2
  exit 1
fi

systemctl disable --now weather-alerts.service weather-alerts-web.service 2>/dev/null || true
systemctl disable --now weatheralerts.service weatheralerts-web.service 2>/dev/null || true
rm -f /etc/systemd/system/weather-alerts.service /etc/systemd/system/weather-alerts-web.service
rm -f /etc/systemd/system/weatheralerts.service /etc/systemd/system/weatheralerts-web.service
systemctl daemon-reload || true

echo "Services removed. Application files remain at $APP_DIR and config remains at $CONFIG_PATH."
echo "Remove them manually if you no longer need the state, logs, or private config."
