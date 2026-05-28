#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/weathertelegramalerts"
CONFIG_DIR="/etc/weathertelegramalerts"
SERVICE_USER="weatheralerts"
CONFIG_SOURCE=""
INSTALL_SERVICES="1"
START_MODE="auto"

usage() {
  cat <<'EOF'
Usage: sudo ./install.sh [options]

Options:
  --app-dir PATH       Install application files here. Default: /opt/weathertelegramalerts
  --config PATH        Copy this private config to /etc/weathertelegramalerts/config.yaml
  --config-dir PATH    Store runtime config here. Default: /etc/weathertelegramalerts
  --user USER          System user for services. Default: weatheralerts
  --no-services        Install files only; do not install systemd units
  --start              Start or restart services after install
  --no-start           Do not start services after install
  -h, --help           Show this help

Recommended:
  sudo ./install.sh --config /path/to/config.NC4ES.private.yaml --start
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-dir)
      APP_DIR="$2"
      shift 2
      ;;
    --config)
      CONFIG_SOURCE="$2"
      shift 2
      ;;
    --config-dir)
      CONFIG_DIR="$2"
      shift 2
      ;;
    --user)
      SERVICE_USER="$2"
      shift 2
      ;;
    --no-services)
      INSTALL_SERVICES="0"
      shift
      ;;
    --start)
      START_MODE="yes"
      shift
      ;;
    --no-start)
      START_MODE="no"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
 done

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer as root, for example: sudo ./install.sh --config /path/to/config.yaml --start" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required." >&2
  exit 1
fi

if ! python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
then
  echo "Python 3.9 or newer is required." >&2
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 python3-venv python3-pip ca-certificates
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

mkdir -p "$APP_DIR" "$CONFIG_DIR"

tar \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='config.yaml' \
  --exclude='config.*.private.yaml' \
  --exclude='data' \
  --exclude='logs' \
  -C "$SRC_DIR" -cf - . | tar -C "$APP_DIR" -xf -

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

CONFIG_READY="0"
if [ -n "$CONFIG_SOURCE" ]; then
  if [ ! -f "$CONFIG_SOURCE" ]; then
    echo "Config source not found: $CONFIG_SOURCE" >&2
    exit 1
  fi
  cp "$CONFIG_SOURCE" "$CONFIG_DIR/config.yaml"
  CONFIG_READY="1"
elif [ -f "$CONFIG_DIR/config.yaml" ]; then
  CONFIG_READY="1"
else
  cp "$APP_DIR/config.example.yaml" "$CONFIG_DIR/config.yaml"
  CONFIG_READY="0"
fi

mkdir -p "$APP_DIR/data" "$APP_DIR/logs"
chown -R root:root "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data" "$APP_DIR/logs"
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR/config.yaml"
chmod 600 "$CONFIG_DIR/config.yaml"
chmod 755 "$APP_DIR" "$CONFIG_DIR"

if [ -x "$APP_DIR/scripts/validate_config.py" ]; then
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$SERVICE_USER" -- "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/validate_config.py" "$CONFIG_DIR/config.yaml" || true
  else
    su -s /bin/sh -c "\"$APP_DIR/.venv/bin/python\" \"$APP_DIR/scripts/validate_config.py\" \"$CONFIG_DIR/config.yaml\"" "$SERVICE_USER" || true
  fi
fi

if [ "$INSTALL_SERVICES" = "1" ] && ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; skipping service installation."
  INSTALL_SERVICES="0"
fi

if [ "$INSTALL_SERVICES" = "1" ]; then
  cat > /etc/systemd/system/weatheralerts.service <<EOF
[Unit]
Description=WeatherTelegramAlerts poller
After=network-online.target weatheralerts-web.service
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/WeatherAlerts.py -c $CONFIG_DIR/config.yaml
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

  cat > /etc/systemd/system/weatheralerts-web.service <<EOF
[Unit]
Description=WeatherTelegramAlerts web dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/webapp.py -c $CONFIG_DIR/config.yaml --waitress
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable weatheralerts.service weatheralerts-web.service

  SHOULD_START="0"
  if [ "$START_MODE" = "yes" ]; then
    SHOULD_START="1"
  elif [ "$START_MODE" = "auto" ] && [ "$CONFIG_READY" = "1" ]; then
    SHOULD_START="1"
  fi

  if [ "$SHOULD_START" = "1" ]; then
    systemctl restart weatheralerts-web.service weatheralerts.service
    echo "Services started."
  else
    echo "Services installed but not started. Edit $CONFIG_DIR/config.yaml, then run:"
    echo "  sudo systemctl start weatheralerts-web.service weatheralerts.service"
  fi
fi

cat <<EOF

Install complete.
Application: $APP_DIR
Config:      $CONFIG_DIR/config.yaml
Dashboard:   http://SERVER_IP:8085/weatheralerts

Useful commands:
  sudo systemctl status weatheralerts.service
  sudo systemctl status weatheralerts-web.service
  sudo journalctl -u weatheralerts.service -f
  sudo journalctl -u weatheralerts-web.service -f
EOF
