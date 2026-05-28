#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/WeatherTelegramAlerts"
CONFIG_DIR=""
SERVICE_USER="weatheralerts"
CONFIG_SOURCE=""
INSTALL_SERVICES="1"
START_MODE="auto"
POLL_SERVICE="weather-alerts.service"
WEB_SERVICE="weather-alerts-web.service"

usage() {
  cat <<'USAGE'
Usage: sudo ./install.sh [options]

Options:
  --app-dir PATH       Install application files here. Default: /opt/WeatherTelegramAlerts
  --config PATH        Copy this private config to /opt/WeatherTelegramAlerts/config.yaml
  --config-dir PATH    Store runtime config here. Default: same as --app-dir
  --user USER          System user for services. Default: weatheralerts
  --no-services        Install files only; do not install systemd units
  --start              Start or restart services after install
  --no-start           Do not start services after install
  -h, --help           Show this help

Recommended first install:
  sudo ./install.sh --config /path/to/config.NC4ES.private.yaml --start

Recommended update when /opt/WeatherTelegramAlerts/config.yaml already exists:
  sudo ./install.sh --start
USAGE
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

if [ -z "$CONFIG_DIR" ]; then
  CONFIG_DIR="$APP_DIR"
fi
CONFIG_PATH="$CONFIG_DIR/config.yaml"

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

# Stop known service names before replacing files. Ignore missing services.
if command -v systemctl >/dev/null 2>&1; then
  systemctl stop "$POLL_SERVICE" "$WEB_SERVICE" 2>/dev/null || true
  systemctl stop weatheralerts.service weatheralerts-web.service 2>/dev/null || true
fi

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
  SRC_REAL="$(readlink -f "$CONFIG_SOURCE")"
  DEST_REAL="$(readlink -m "$CONFIG_PATH")"
  if [ "$SRC_REAL" != "$DEST_REAL" ]; then
    cp "$CONFIG_SOURCE" "$CONFIG_PATH"
  fi
  CONFIG_READY="1"
elif [ -f "$CONFIG_PATH" ]; then
  CONFIG_READY="1"
else
  cp "$APP_DIR/config.example.yaml" "$CONFIG_PATH"
  CONFIG_READY="0"
fi

mkdir -p "$APP_DIR/data" "$APP_DIR/logs"
chown -R root:root "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data" "$APP_DIR/logs"
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_PATH"
chmod 600 "$CONFIG_PATH"
chmod 755 "$APP_DIR" "$CONFIG_DIR"

if [ -x "$APP_DIR/scripts/validate_config.py" ]; then
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$SERVICE_USER" -- "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/validate_config.py" "$CONFIG_PATH" || true
  else
    su -s /bin/sh -c "\"$APP_DIR/.venv/bin/python\" \"$APP_DIR/scripts/validate_config.py\" \"$CONFIG_PATH\"" "$SERVICE_USER" || true
  fi
fi

if [ "$INSTALL_SERVICES" = "1" ] && ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; skipping service installation."
  INSTALL_SERVICES="0"
fi

if [ "$INSTALL_SERVICES" = "1" ]; then
  # Remove older service names from prior packages so only the requested names remain enabled.
  systemctl disable weatheralerts.service weatheralerts-web.service 2>/dev/null || true
  rm -f /etc/systemd/system/weatheralerts.service /etc/systemd/system/weatheralerts-web.service

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

  SHOULD_START="0"
  if [ "$START_MODE" = "yes" ]; then
    SHOULD_START="1"
  elif [ "$START_MODE" = "auto" ] && [ "$CONFIG_READY" = "1" ]; then
    SHOULD_START="1"
  fi

  if [ "$SHOULD_START" = "1" ]; then
    systemctl restart "$WEB_SERVICE" "$POLL_SERVICE"
    echo "Services started."
  else
    echo "Services installed but not started. Edit $CONFIG_PATH, then run:"
    echo "  sudo systemctl start $WEB_SERVICE $POLL_SERVICE"
  fi
fi

cat <<EOF_SUMMARY

Install complete.
Application: $APP_DIR
Config:      $CONFIG_PATH
Dashboard:   http://SERVER_IP:8085/weatheralerts

Useful commands:
  sudo systemctl status weather-alerts.service
  sudo systemctl status weather-alerts-web.service
  sudo journalctl -u weather-alerts.service -f
  sudo journalctl -u weather-alerts-web.service -f
EOF_SUMMARY
