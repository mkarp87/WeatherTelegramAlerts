#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/weathertelegramalerts"
CONFIG_DIR="/etc/weathertelegramalerts"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo ./uninstall.sh" >&2
  exit 1
fi

systemctl disable --now weatheralerts.service weatheralerts-web.service 2>/dev/null || true
rm -f /etc/systemd/system/weatheralerts.service /etc/systemd/system/weatheralerts-web.service
systemctl daemon-reload || true

echo "Services removed. Application files remain at $APP_DIR and config remains at $CONFIG_DIR."
echo "Remove them manually if you no longer need the state, logs, or private config."
