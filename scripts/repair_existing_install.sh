#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/WeatherTelegramAlerts}"
SERVICE_USER="${SERVICE_USER:-weatheralerts}"
CONFIG_PATH="${CONFIG_PATH:-$APP_DIR/config.yaml}"
MAIN_SERVICE="weather-alerts.service"
VENV_DIR="$APP_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

log() {
  printf '[repair] %s\n' "$*"
}

fail() {
  printf '[repair] ERROR: %s\n' "$*" >&2
  exit 1
}

if [ "$(id -u)" -ne 0 ]; then
  fail "Run as root: sudo ./scripts/repair_existing_install.sh"
fi

[ -d "$APP_DIR" ] || fail "Application directory not found: $APP_DIR"
[ -f "$CONFIG_PATH" ] || fail "Config file not found: $CONFIG_PATH"
[ -f "$APP_DIR/requirements.txt" ] || fail "requirements.txt not found in $APP_DIR. Reinstall from the updated ZIP."
[ -f "$APP_DIR/app.py" ] || fail "app.py not found in $APP_DIR. Reinstall from the unified ZIP."
[ -f "$APP_DIR/WeatherAlerts.py" ] || fail "WeatherAlerts.py not found in $APP_DIR. Reinstall from the unified ZIP."
[ -f "$APP_DIR/webapp.py" ] || fail "webapp.py not found in $APP_DIR. Reinstall from the unified ZIP."

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

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  log "Creating service user: $SERVICE_USER"
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

log "Stopping old services."
systemctl stop "$MAIN_SERVICE" weather-alerts-web.service weatheralerts.service weatheralerts-web.service 2>/dev/null || true
systemctl disable weather-alerts-web.service weatheralerts.service weatheralerts-web.service 2>/dev/null || true
rm -f /etc/systemd/system/weather-alerts-web.service /etc/systemd/system/weatheralerts.service /etc/systemd/system/weatheralerts-web.service

log "Recreating virtual environment at $VENV_DIR"
rm -rf "$VENV_DIR"
"$SYSTEM_PYTHON" -m venv "$VENV_DIR" || fail "$SYSTEM_PYTHON -m venv failed. Install python3-venv and rerun."
[ -x "$VENV_PYTHON" ] || fail "Virtual environment Python not found at $VENV_PYTHON"

log "Installing Python requirements."
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel
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

log "Fixing runtime permissions."
mkdir -p "$APP_DIR/data" "$APP_DIR/logs"
rm -f "$APP_DIR/data/last_alerts.json.tmp" 2>/dev/null || true
chown -R root:root "$APP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data" "$APP_DIR/logs"
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG_PATH"
chmod 600 "$CONFIG_PATH"
chmod 755 "$APP_DIR"

log "Testing service-user write access."
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

log "Writing unified systemd service."
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
log "Restarting service."
systemctl restart "$MAIN_SERVICE"

cat <<EOF_SUMMARY
Repair complete.
  Unified service: sudo systemctl status $MAIN_SERVICE
  Logs:            sudo journalctl -u $MAIN_SERVICE -f
  Python venv:     $VENV_DIR
EOF_SUMMARY
