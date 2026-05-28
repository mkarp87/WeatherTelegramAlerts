#!/usr/bin/env bash
set -euo pipefail
CONFIG="${1:-config.yaml}"
python3 WeatherAlerts.py -c "$CONFIG" --once
