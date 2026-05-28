#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/WeatherTelegramAlerts"
CONFIG_DIR=""
SERVICE_USER="weatheralerts"
CONFIG_SOURCE=""
INSTALL_SERVICES="1"
START_MODE="auto"
MAIN_SERVICE="weather-alerts.service"
RECREATE_VENV="1"
INSTALL_VERSION="2.2.5"

log() {
  printf '[install] %s\n' "$*"
}

fail() {
  printf '[install] ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
Usage: sudo ./install.sh [options]

Options:
  --app-dir PATH       Install application files here. Default: /opt/WeatherTelegramAlerts
  --config PATH        Copy this private config to /opt/WeatherTelegramAlerts/config.yaml
  --config-dir PATH    Store runtime config here. Default: same as --app-dir
  --user USER          System user for the service. Default: weatheralerts
  --no-services        Install files only; do not install systemd unit
  --start              Start or restart the service after install
  --no-start           Do not start the service after install
  --keep-venv          Reuse an existing venv if present; still installs requirements
  -h, --help           Show this help

Recommended first install:
  sudo ./install.sh --config /path/to/config.yaml --start

Recommended update when /opt/WeatherTelegramAlerts/config.yaml already exists:
  sudo ./install.sh --start
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-dir)
      APP_DIR="${2:-}"
      shift 2
      ;;
    --config)
      CONFIG_SOURCE="${2:-}"
      shift 2
      ;;
    --config-dir)
      CONFIG_DIR="${2:-}"
      shift 2
      ;;
    --user)
      SERVICE_USER="${2:-}"
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
    --keep-venv)
      RECREATE_VENV="0"
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

[ -n "$APP_DIR" ] || fail "--app-dir cannot be empty"
if [ -z "$CONFIG_DIR" ]; then
  CONFIG_DIR="$APP_DIR"
fi
CONFIG_PATH="$CONFIG_DIR/config.yaml"

if [ "$(id -u)" -ne 0 ]; then
  fail "Run this installer as root, for example: sudo ./install.sh --config /path/to/config.yaml --start"
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[ -f "$SRC_DIR/app.py" ] || fail "app.py not found. Run install.sh from the extracted WeatherTelegramAlerts directory."
[ -f "$SRC_DIR/WeatherAlerts.py" ] || fail "WeatherAlerts.py not found. Run install.sh from the extracted WeatherTelegramAlerts directory."
[ -f "$SRC_DIR/webapp.py" ] || fail "webapp.py not found. Run install.sh from the extracted WeatherTelegramAlerts directory."
[ -f "$SRC_DIR/requirements.txt" ] || fail "requirements.txt not found. Run install.sh from the extracted WeatherTelegramAlerts directory."
[ -d "$SRC_DIR/weather_alerts" ] || fail "weather_alerts package not found. Run install.sh from the extracted WeatherTelegramAlerts directory."

if command -v apt-get >/dev/null 2>&1; then
  log "Installing system prerequisites with apt."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3 python3-venv python3-pip ca-certificates
fi

select_system_python() {
  local app_real candidate candidate_real
  app_real="$(readlink -m "$APP_DIR")"
  for candidate in /usr/bin/python3 /usr/local/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
    [ -n "$candidate" ] || continue
    [ -x "$candidate" ] || continue
    candidate_real="$(readlink -f "$candidate" 2>/dev/null || printf '%s' "$candidate")"
    case "$candidate_real" in
      "$app_real/.venv"/*)
        continue
        ;;
    esac
    printf '%s\n' "$candidate_real"
    return 0
  done
  return 1
}

SYSTEM_PYTHON="$(select_system_python || true)"
[ -n "$SYSTEM_PYTHON" ] || fail "python3 is required and must not be the app virtualenv Python. Install python3 and python3-venv, then rerun."
log "Using system Python: $SYSTEM_PYTHON"
"$SYSTEM_PYTHON" --version

if ! "$SYSTEM_PYTHON" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
then
  fail "Python 3.9 or newer is required."
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  log "Creating service user: $SERVICE_USER"
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

log "Preparing application directory: $APP_DIR"
mkdir -p "$APP_DIR" "$CONFIG_DIR"

if [ "$INSTALL_SERVICES" = "1" ] && command -v systemctl >/dev/null 2>&1; then
  log "Stopping old services if present."
  systemctl stop "$MAIN_SERVICE" weather-alerts-web.service weatheralerts.service weatheralerts-web.service 2>/dev/null || true
  systemctl disable weather-alerts-web.service weatheralerts.service weatheralerts-web.service 2>/dev/null || true
  rm -f /etc/systemd/system/weather-alerts-web.service /etc/systemd/system/weatheralerts.service /etc/systemd/system/weatheralerts-web.service
  systemctl daemon-reload 2>/dev/null || true
fi

SRC_REAL="$(readlink -f "$SRC_DIR")"
APP_REAL="$(readlink -m "$APP_DIR")"

if [ "$SRC_REAL" = "$APP_REAL" ]; then
  log "Source directory is already $APP_DIR; skipping file copy and continuing with venv setup."
else
  log "Copying application files from $SRC_DIR to $APP_DIR"
  "$SYSTEM_PYTHON" - "$SRC_DIR" "$APP_DIR" <<'PY_COPY'
import fnmatch
import shutil
import sys
from pathlib import Path

src = Path(sys.argv[1]).resolve()
dst = Path(sys.argv[2]).resolve()

skip_names = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "config.yaml",
    "data",
    "logs",
}
skip_patterns = (
    "*.pyc",
    "config.*.private.yaml",
)

def should_skip(path: Path) -> bool:
    name = path.name
    if name in skip_names:
        return True
    if any(fnmatch.fnmatch(name, pattern) for pattern in skip_patterns):
        return True
    try:
        dst.relative_to(path.resolve())
        return True
    except ValueError:
        return False

for item in src.iterdir():
    if should_skip(item):
        continue
    target = dst / item.name
    if item.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        if target.exists() and target.is_dir():
            shutil.rmtree(target)
        shutil.copy2(item, target)
PY_COPY
fi

[ -f "$APP_DIR/requirements.txt" ] || fail "Install source problem: $APP_DIR/requirements.txt is missing."

VENV_DIR="$APP_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ "$RECREATE_VENV" = "1" ]; then
  log "Recreating virtual environment at $VENV_DIR"
  rm -rf "$VENV_DIR"
elif [ -x "$VENV_PYTHON" ]; then
  log "Reusing existing virtual environment at $VENV_DIR"
else
  log "Creating virtual environment at $VENV_DIR"
fi

if [ ! -x "$VENV_PYTHON" ]; then
  "$SYSTEM_PYTHON" -m venv "$VENV_DIR" || fail "$SYSTEM_PYTHON -m venv failed. On Debian/Ubuntu, install python3-venv and rerun."
fi

[ -x "$VENV_PYTHON" ] || fail "Virtual environment Python was not created at $VENV_PYTHON"
log "Virtual environment ready: $VENV_PYTHON"
"$VENV_PYTHON" --version

log "Upgrading pip tooling."
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

log "Installing Python requirements from $APP_DIR/requirements.txt"
"$VENV_PYTHON" -m pip install -r "$APP_DIR/requirements.txt"

log "Verifying installed Python modules."
"$VENV_PYTHON" - <<'PY'
import flask
import requests
from ruamel.yaml import YAML
import dateutil
import waitress
import werkzeug
print("Python dependency import check passed.")
PY

CONFIG_READY="0"
if [ -n "$CONFIG_SOURCE" ]; then
  if [ ! -f "$CONFIG_SOURCE" ]; then
    fail "Config source not found: $CONFIG_SOURCE"
  fi
  log "Installing private config to $CONFIG_PATH"
  SRC_REAL="$(readlink -f "$CONFIG_SOURCE")"
  DEST_REAL="$(readlink -m "$CONFIG_PATH")"
  if [ "$SRC_REAL" != "$DEST_REAL" ]; then
    cp "$CONFIG_SOURCE" "$CONFIG_PATH"
  fi
  CONFIG_READY="1"
elif [ -f "$CONFIG_PATH" ]; then
  log "Using existing config: $CONFIG_PATH"
  CONFIG_READY="1"
else
  log "No private config found; installing sample config at $CONFIG_PATH"
  cp "$APP_DIR/config.example.yaml" "$CONFIG_PATH"
  CONFIG_READY="0"
fi

log "Setting runtime directories and permissions."
mkdir -p "$APP_DIR/data" "$APP_DIR/logs"
rm -f "$APP_DIR/data/last_alerts.json.tmp" 2>/dev/null || true
chown -R root:root "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data" "$APP_DIR/logs"
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_PATH"
chmod 600 "$CONFIG_PATH"
chmod 755 "$APP_DIR" "$CONFIG_DIR"
chmod +x "$APP_DIR/app.py" "$APP_DIR/WeatherAlerts.py" "$APP_DIR/webapp.py" 2>/dev/null || true

log "Testing service-user write access to runtime directories."
if command -v runuser >/dev/null 2>&1; then
  runuser -u "$SERVICE_USER" -- "$VENV_PYTHON" - <<PY
from pathlib import Path
base = Path("$APP_DIR")
for rel in ("data/.write_test", "logs/.write_test"):
    p = base / rel
    p.write_text("ok", encoding="utf-8")
    p.unlink()
print("Runtime directory write check passed.")
PY
else
  su -s /bin/sh -c "\"$VENV_PYTHON\" - <<'PY'\nfrom pathlib import Path\nbase = Path('$APP_DIR')\nfor rel in ('data/.write_test', 'logs/.write_test'):\n    p = base / rel\n    p.write_text('ok', encoding='utf-8')\n    p.unlink()\nprint('Runtime directory write check passed.')\nPY" "$SERVICE_USER"
fi

log "Initializing SQLite log database as service user."
if command -v runuser >/dev/null 2>&1; then
  runuser -u "$SERVICE_USER" -- env PYTHONPATH="$APP_DIR" "$VENV_PYTHON" - <<PY
from weather_alerts.config import BASE_DIR, load_config, resolve_path
from weather_alerts.db import connect
config = load_config(r"""$CONFIG_PATH""")
db_path = resolve_path((config.get("Webapp") or {}).get("LogDatabase", "data/alert_logs.sqlite3"), base_dir=BASE_DIR)
connect(db_path).close()
print(f"SQLite log database ready: {db_path}")
PY
else
  su -s /bin/sh -c "PYTHONPATH='$APP_DIR' '$VENV_PYTHON' - <<'PY'
from weather_alerts.config import BASE_DIR, load_config, resolve_path
from weather_alerts.db import connect
config = load_config('$CONFIG_PATH')
db_path = resolve_path((config.get('Webapp') or {}).get('LogDatabase', 'data/alert_logs.sqlite3'), base_dir=BASE_DIR)
connect(db_path).close()
print(f'SQLite log database ready: {db_path}')
PY" "$SERVICE_USER"
fi

if [ -f "$APP_DIR/scripts/validate_config.py" ]; then
  log "Validating config."
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$SERVICE_USER" -- "$VENV_PYTHON" "$APP_DIR/scripts/validate_config.py" "$CONFIG_PATH" || true
  else
    su -s /bin/sh -c "\"$VENV_PYTHON\" \"$APP_DIR/scripts/validate_config.py\" \"$CONFIG_PATH\"" "$SERVICE_USER" || true
  fi
fi

if [ "$INSTALL_SERVICES" = "1" ] && ! command -v systemctl >/dev/null 2>&1; then
  log "systemctl not found; skipping service installation."
  INSTALL_SERVICES="0"
fi

if [ "$INSTALL_SERVICES" = "1" ]; then
  log "Writing single systemd service: $MAIN_SERVICE"
  systemctl disable weather-alerts-web.service weatheralerts.service weatheralerts-web.service 2>/dev/null || true
  rm -f /etc/systemd/system/weather-alerts-web.service /etc/systemd/system/weatheralerts.service /etc/systemd/system/weatheralerts-web.service

  cat > /etc/systemd/system/$MAIN_SERVICE <<EOF_SERVICE
[Unit]
Description=WeatherTelegramAlerts unified service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_PYTHON $APP_DIR/app.py -c $CONFIG_PATH
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF_SERVICE

  systemctl daemon-reload
  systemctl enable "$MAIN_SERVICE"

  SHOULD_START="0"
  if [ "$START_MODE" = "yes" ]; then
    SHOULD_START="1"
  elif [ "$START_MODE" = "auto" ] && [ "$CONFIG_READY" = "1" ]; then
    SHOULD_START="1"
  fi

  if [ "$SHOULD_START" = "1" ]; then
    log "Starting service."
    systemctl restart "$MAIN_SERVICE"
    log "Service started."
  else
    log "Service installed but not started. Edit $CONFIG_PATH, then run:"
    echo "  sudo systemctl start $MAIN_SERVICE"
  fi
fi

cat <<EOF_SUMMARY

Install complete.
Application: $APP_DIR
Config:      $CONFIG_PATH
Venv:        $VENV_DIR
Service:     $MAIN_SERVICE
Dashboard:   http://SERVER_IP:8085/weatheralerts

Useful commands:
  sudo systemctl status weather-alerts.service
  sudo journalctl -u weather-alerts.service -f
  sudo systemctl restart weather-alerts.service
EOF_SUMMARY
