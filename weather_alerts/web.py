from __future__ import annotations

import argparse
import hmac
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser
from flask import Flask, abort, jsonify, redirect, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import BASE_DIR, as_bool, load_config, resolve_path
from .db import insert_log, list_logs, prune_logs
from .nws import NWSClient, time_keys
from .text import modify_description

LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
_ALERT_CACHE: dict[tuple[Any, ...], tuple[float, list[dict[str, str]]]] = {}


def setup_logging(config: dict[str, Any]) -> None:
    debug = as_bool(config.get("Logging", {}).get("Debug"), default=False)
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def db_path_from_config(config: dict[str, Any]) -> Path:
    configured = config.get("Webapp", {}).get("LogDatabase", "data/alert_logs.sqlite3")
    return resolve_path(configured, base_dir=BASE_DIR)


def sanitize_text(value: Any, *, limit: int) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def format_et(ts: str) -> str:
    try:
        dt = date_parser.isoparse(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(EASTERN).strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return str(ts)


def token_is_valid(config: dict[str, Any], provided: str) -> bool:
    web_cfg = config.get("Webapp", {}) or {}
    require_token = as_bool(web_cfg.get("RequireWebhookToken", web_cfg.get("RequireLogToken")), default=True)
    if not require_token:
        return True
    expected = str(web_cfg.get("WebhookToken") or web_cfg.get("LogToken") or "")
    if not expected:
        LOGGER.error("Webhook token is required but not configured")
        return False
    return hmac.compare_digest(provided or "", expected)



def alert_kind_from_event(event: Any) -> str:
    text = str(event or "").lower()
    if "tornado" in text:
        return "tornado"
    if "severe thunderstorm" in text or "extreme wind" in text:
        return "severe"
    if "flash flood" in text or "flood" in text or "storm surge" in text or "coastal flood" in text:
        return "flood"
    if "winter" in text or "snow" in text or "ice" in text or "blizzard" in text or "freeze" in text:
        return "winter"
    if "watch" in text:
        return "watch"
    if "advisory" in text:
        return "advisory"
    if "statement" in text:
        return "statement"
    return "alert"

def normalize_inject_alerts(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def fetch_dashboard_alerts_for_zone(
    *,
    config: dict[str, Any],
    zone: str,
    start_key: str,
    end_key: str,
    max_words: int,
) -> list[dict[str, str]]:
    weather_cfg = config.get("WeatherAlerts", {}) or {}
    web_cfg = config.get("Webapp", {}) or {}
    alert_cfg = config.get("Alerting", {}) or {}
    blocked = tuple(alert_cfg.get("GlobalBlockedEvents", []) or [])
    cache_seconds = int(web_cfg.get("CacheSeconds", 90) or 90)
    user_agent = weather_cfg.get("UserAgent") or web_cfg.get("UserAgent") or "WeatherTelegramAlerts/2.0 (no-contact@example.com)"
    key = (zone, start_key, end_key, max_words, blocked, user_agent)
    now_ts = time.time()
    cached = _ALERT_CACHE.get(key)
    if cached and now_ts - cached[0] < cache_seconds:
        return cached[1]

    client = NWSClient(
        user_agent=user_agent,
        blocked_events=blocked,
        start_key=start_key,
        end_key=end_key,
        timeout=int(weather_cfg.get("RequestTimeout", 10) or 10),
    )
    try:
        raw_alerts = client.fetch_zone(zone)
    except Exception as exc:
        LOGGER.error("Dashboard NWS fetch error for %s: %s", zone, exc)
        return [
            {
                "event": "Dashboard fetch error",
                "description": f"Could not fetch active alerts for {zone}. The poller will not send all-clear messages from this dashboard error.",
                "kind": "error",
            }
        ]

    output = []
    for item in raw_alerts:
        title = str(item.get("Title") or "Weather Alert")
        output.append(
            {
                "event": title,
                "description": modify_description(
                    f"{title}: {item.get('Description') or ''}",
                    max_words=max_words,
                ),
                "kind": alert_kind_from_event(title),
            }
        )
    _ALERT_CACHE[key] = (now_ts, output)
    return output


def build_dashboard(config: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    alert_cfg = config.get("Alerting", {}) or {}
    dev_cfg = config.get("DEV", {}) or {}
    counties = [str(code) for code in (alert_cfg.get("CountyCodes") or [])]
    labels = {str(k): str(v) for k, v in (alert_cfg.get("CountyLabels") or {}).items()}
    start_key, end_key = time_keys(alert_cfg.get("TimeType", "onset"))
    max_words = int(config.get("SkyDescribe", {}).get("MaxWords", 150) or 150)

    inj_map: dict[str, list[dict[str, str]]] = {}
    global_tests: list[dict[str, str]] = []
    if as_bool(dev_cfg.get("INJECT"), default=False):
        prefix = str(dev_cfg.get("PrefixMessage") or "")
        for item in normalize_inject_alerts(dev_cfg.get("INJECTALERTS")):
            code = str(item.get("Code") or "")
            event = str(item.get("Title") or "Test Weather Alert")
            desc = str(item.get("Description") or "")
            test_alert = {
                "event": event,
                "description": modify_description(prefix + desc, max_words=max_words),
                "kind": "test",
            }
            if code in counties:
                inj_map.setdefault(code, []).append(test_alert)
            else:
                global_tests.append(test_alert)

    dashboard: dict[str, list[dict[str, str]]] = {}
    for code in counties:
        label = labels.get(code, code)
        real = fetch_dashboard_alerts_for_zone(
            config=config,
            zone=code,
            start_key=start_key,
            end_key=end_key,
            max_words=max_words,
        )
        dashboard[label] = inj_map.get(code, []) + global_tests + real
    return dashboard


def create_app(config_path: str | None = None) -> Flask:
    cfg_path = config_path or str(BASE_DIR / "config.yaml")
    initial_config = load_config(cfg_path)
    setup_logging(initial_config)

    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
        static_url_path="/weatheralerts/static",
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.url_map.strict_slashes = False
    app.config["WEATHERALERTS_CONFIG"] = cfg_path
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

    def cfg() -> dict[str, Any]:
        config = load_config(app.config["WEATHERALERTS_CONFIG"])
        setup_logging(config)
        return config

    @app.after_request
    def add_no_cache_headers(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    @app.route("/")
    def root():
        return redirect("/weatheralerts")

    @app.route("/weatheralerts")
    @app.route("/weatheralerts/")
    def current():
        config = cfg()
        dashboard = build_dashboard(config)
        dev_flag = as_bool(config.get("DEV", {}).get("INJECT"), default=False)
        return render_template(
            "index.html",
            dashboard=dashboard,
            dev=dev_flag,
            generated_at=format_et(datetime.now(timezone.utc).isoformat()),
        )

    @app.route("/api/alerts")
    def api_alerts():
        return jsonify(build_dashboard(cfg()))

    @app.route("/weatheralerts/log", methods=["POST"])
    def log_event():
        config = cfg()
        provided = request.headers.get("X-WeatherAlerts-Token", "")
        if not token_is_valid(config, provided):
            abort(403)

        data = request.get_json(silent=True) or {}
        event = sanitize_text(data.get("event"), limit=200)
        blocked = config.get("Alerting", {}).get("GlobalBlockedEvents", []) or []
        import fnmatch

        if any(fnmatch.fnmatch(event, pattern) for pattern in blocked):
            LOGGER.info("Blocked log event: %s", event)
            return ("", 204)

        timestamp = sanitize_text(data.get("timestamp") or datetime.now(timezone.utc).isoformat(), limit=80)
        entry = {
            "timestamp": timestamp,
            "county": sanitize_text(data.get("county") or "UNKNOWN", limit=80),
            "event": event,
            "description": sanitize_text(data.get("description"), limit=10000),
        }
        db_path = db_path_from_config(config)
        insert_log(db_path, entry)
        prune_logs(db_path, days=int(config.get("Webapp", {}).get("LogRetentionDays", 7) or 7))
        return ("", 204)

    @app.route("/weatheralerts/logs.html")
    def logs():
        config = cfg()
        hours = int(request.args.get("hours", config.get("Webapp", {}).get("LogHours", 24)) or 24)
        db_path = db_path_from_config(config)
        logs_raw = list_logs(db_path, hours=hours)
        labels = {str(k): str(v) for k, v in (config.get("Alerting", {}).get("CountyLabels") or {}).items()}
        formatted = []
        for entry in logs_raw:
            zone = str(entry.get("county") or "UNKNOWN")
            copy = dict(entry)
            copy["timestamp_et"] = format_et(str(entry.get("timestamp") or ""))
            copy["county_label"] = labels.get(zone, zone)
            formatted.append(copy)
        used_zones = sorted({str(entry.get("county") or "UNKNOWN") for entry in logs_raw})
        county_labels = {zone: labels.get(zone, zone) for zone in used_zones}
        return render_template(
            "logs.html",
            logs=formatted,
            labels=county_labels,
            hours=hours,
            generated_at=format_et(datetime.now(timezone.utc).isoformat()),
        )

    @app.route("/weatheralerts/logs.json")
    def logs_json():
        config = cfg()
        hours = int(request.args.get("hours", config.get("Webapp", {}).get("LogHours", 24)) or 24)
        return jsonify(list_logs(db_path_from_config(config), hours=hours))

    return app


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WeatherTelegramAlerts web dashboard")
    parser.add_argument("-c", "--config", default=str(BASE_DIR / "config.yaml"), help="Path to YAML config file")
    parser.add_argument("-p", "--port", type=int, default=None, help="Port to run the web server on")
    parser.add_argument("--host", default=None, help="Host/IP to bind")
    parser.add_argument("--waitress", action="store_true", help="Run with Waitress instead of Flask's development server")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    setup_logging(config)
    host = args.host or config.get("Webapp", {}).get("Host", "127.0.0.1")
    port = int(args.port or config.get("Webapp", {}).get("Port", 8085) or 8085)
    app = create_app(args.config)

    if args.waitress:
        from waitress import serve

        serve(app, host=host, port=port)
    else:
        app.run(host=host, port=port, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(cli())
