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
from .db import connect, insert_log, list_logs, prune_logs
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


def normalize_telegram_chat_link(value: Any) -> str:
    """Normalize a configured Telegram link for dashboard use.

    Numeric Bot API chat IDs are intentionally not converted. Private groups
    need a Telegram invite link or public username to be opened by users.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""

    lowered = raw.lower()
    if lowered.startswith(("https://", "http://", "tg://")):
        return raw
    if lowered.startswith(("t.me/", "telegram.me/")):
        return f"https://{raw}"
    if raw.startswith("@"):
        username = raw[1:].strip("/")
        return f"https://t.me/{username}" if username else ""
    if raw.startswith("+"):
        return f"https://t.me/{raw}"
    if raw.startswith("-") or raw.isdigit():
        return ""
    return f"https://t.me/{raw.strip('/')}"


def county_chat_links_by_code(config: dict[str, Any]) -> dict[str, str]:
    alert_cfg = config.get("Alerting", {}) or {}
    raw_links = (
        alert_cfg.get("CountyChatLinks")
        or alert_cfg.get("CountyChatURLs")
        or alert_cfg.get("CountyTelegramLinks")
        or {}
    )
    if not isinstance(raw_links, dict):
        return {}

    links: dict[str, str] = {}
    for code, raw_link in raw_links.items():
        zone = str(code).strip()
        link = normalize_telegram_chat_link(raw_link)
        if zone and link:
            links[zone] = link
    return links


def county_chat_links_by_label(config: dict[str, Any]) -> dict[str, str]:
    alert_cfg = config.get("Alerting", {}) or {}
    labels = {str(k): str(v) for k, v in (alert_cfg.get("CountyLabels") or {}).items()}
    by_code = county_chat_links_by_code(config)
    return {labels.get(code, code): link for code, link in by_code.items()}


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


def _as_int(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _as_float(value: Any, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _parse_layer_ids(value: Any) -> list[int]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = str(value).replace(";", ",").split(",")
    parsed: list[int] = []
    for item in raw_values:
        try:
            parsed.append(int(str(item).strip()))
        except (TypeError, ValueError):
            continue
    return parsed


def radar_config_from_config(config: dict[str, Any]) -> dict[str, Any]:
    web_cfg = config.get("Webapp", {}) or {}
    raw = web_cfg.get("Radar", {}) or {}
    if not isinstance(raw, dict):
        raw = {}

    enabled = as_bool(raw.get("Enabled"), default=False)
    raw_regions = raw.get("Regions") or {}
    if not isinstance(raw_regions, dict):
        raw_regions = {}

    regions: dict[str, dict[str, Any]] = {}
    for key, value in raw_regions.items():
        if not isinstance(value, dict):
            continue
        region_key = str(key).strip()
        if not region_key:
            continue
        try:
            lat = float(value.get("CenterLat", value.get("Lat", value.get("Latitude"))))
            lon = float(value.get("CenterLon", value.get("Lon", value.get("Longitude"))))
        except (TypeError, ValueError):
            LOGGER.warning("Skipping radar region %s because CenterLat/CenterLon are invalid", region_key)
            continue
        zoom = _as_int(value.get("Zoom"), 7, minimum=3, maximum=14)
        regions[region_key] = {
            "label": str(value.get("Label") or region_key).strip() or region_key,
            "center_lat": lat,
            "center_lon": lon,
            "zoom": zoom,
        }

    if enabled and not regions:
        regions["eastern_nc"] = {
            "label": "Eastern NC",
            "center_lat": 35.35,
            "center_lon": -77.25,
            "zoom": 7,
        }

    default_region = str(raw.get("DefaultRegion") or "").strip()
    if default_region not in regions and regions:
        default_region = next(iter(regions))

    default_leaflet_css_url = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    default_leaflet_js_url = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    leaflet_css_url = str(raw.get("LeafletCssURL") or default_leaflet_css_url).strip()
    leaflet_js_url = str(raw.get("LeafletJsURL") or default_leaflet_js_url).strip()

    css_integrity_raw = raw.get("LeafletCssIntegrity")
    js_integrity_raw = raw.get("LeafletJsIntegrity")
    leaflet_css_integrity = (
        "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
        if css_integrity_raw is None and leaflet_css_url == default_leaflet_css_url
        else str(css_integrity_raw or "").strip()
    )
    leaflet_js_integrity = (
        "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
        if js_integrity_raw is None and leaflet_js_url == default_leaflet_js_url
        else str(js_integrity_raw or "").strip()
    )

    raw_mode = str(raw.get("Mode") or "").strip().lower()
    if raw_mode not in {"wms", "arcgis"}:
        raw_mode = "wms"

    service_url = str(
        raw.get("ServiceURL")
        or "https://mapservices.weather.noaa.gov/eventdriven/rest/services/radar/radar_base_reflectivity/MapServer"
    ).strip()
    layer_ids = _parse_layer_ids(raw.get("LayerIds", raw.get("Layers")))
    is_noaa_reflectivity = "mapservices.weather.noaa.gov" in service_url and "radar_base_reflectivity" in service_url
    use_default_layers = as_bool(raw.get("UseDefaultLayers"), default=is_noaa_reflectivity)

    default_wms_url = "https://opengeo.ncep.noaa.gov/geoserver/conus/conus_bref_qcd/ows"
    wms_url = str(raw.get("WmsURL") or raw.get("WMSURL") or raw.get("WmsUrl") or default_wms_url).strip()
    wms_layers = str(raw.get("WmsLayers") or raw.get("WMSLayers") or raw.get("WmsLayer") or "conus_bref_qcd").strip()
    wms_version = str(raw.get("WmsVersion") or raw.get("WMSVersion") or "1.1.1").strip() or "1.1.1"
    wms_format = str(raw.get("WmsFormat") or raw.get("WMSFormat") or "image/png").strip() or "image/png"
    wms_styles = str(raw.get("WmsStyles") or raw.get("WMSStyles") or "").strip()
    wms_time = str(raw.get("WmsTime") or raw.get("WMSTime") or "").strip()

    source_label = str(raw.get("SourceLabel") or "").strip()
    if not source_label:
        source_label = "NOAA/NCEP MRMS WMS" if raw_mode == "wms" else "NOAA/NWS ArcGIS MapServer"

    return {
        "enabled": bool(enabled and regions),
        "title": str(raw.get("Title") or "Weather Radar").strip() or "Weather Radar",
        "mode": raw_mode,
        "source_label": source_label,
        "height": _as_int(raw.get("Height"), 620, minimum=320, maximum=1200),
        "opacity": _as_float(raw.get("Opacity"), 0.85 if raw_mode == "wms" else 0.72, minimum=0.05, maximum=1.0),
        "refresh_seconds": _as_int(raw.get("RefreshSeconds"), 300, minimum=60, maximum=3600),
        "default_region": default_region,
        "regions": regions,
        "service_url": service_url,
        "layer_ids": [] if use_default_layers else layer_ids,
        "use_default_layers": use_default_layers,
        "wms_url": wms_url,
        "wms_layers": wms_layers,
        "wms_version": wms_version,
        "wms_format": wms_format,
        "wms_styles": wms_styles,
        "wms_time": wms_time,
        "wms_transparent": as_bool(raw.get("WmsTransparent"), default=True),
        "wms_tiled": as_bool(raw.get("WmsTiled"), default=True),
        "wms_uppercase": as_bool(raw.get("WmsUppercase"), default=True),
        "leaflet_css_url": leaflet_css_url,
        "leaflet_js_url": leaflet_js_url,
        "esri_leaflet_js_url": str(raw.get("EsriLeafletJsURL") or "https://cdn.jsdelivr.net/npm/esri-leaflet@3.0.19/dist/esri-leaflet.js").strip(),
        "leaflet_css_integrity": leaflet_css_integrity,
        "leaflet_js_integrity": leaflet_js_integrity,
        "cdn_crossorigin": str(raw.get("CdnCrossorigin") or "").strip(),
        "base_tile_url": str(raw.get("BaseTileURL") or "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").strip(),
        "base_tile_attribution": str(
            raw.get("BaseTileAttribution")
            or '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        ),
        "radar_attribution": str(raw.get("RadarAttribution") or "NOAA/NWS/NCEP"),
        "image_format": str(raw.get("ImageFormat") or "png32").strip() or "png32",
        "disable_cache": as_bool(raw.get("DisableCache"), default=True),
        "startup_delay_ms": _as_int(raw.get("StartupDelayMs"), 350, minimum=0, maximum=5000),
        "max_zoom": _as_int(raw.get("MaxZoom"), 18, minimum=8, maximum=20),
        "scroll_wheel_zoom": as_bool(raw.get("ScrollWheelZoom"), default=False),
    }


def create_app(config_path: str | None = None) -> Flask:
    cfg_path = config_path or str(BASE_DIR / "config.yaml")
    initial_config = load_config(cfg_path)
    setup_logging(initial_config)
    try:
        connect(db_path_from_config(initial_config)).close()
    except Exception as exc:
        LOGGER.warning("Alert log database is not available yet: %s", exc)

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

    @app.context_processor
    def inject_branding():
        try:
            config = load_config(app.config["WEATHERALERTS_CONFIG"])
            web_cfg = config.get("Webapp", {}) or {}
        except Exception:
            web_cfg = {}
        logo_url = str(web_cfg.get("LogoURL") or web_cfg.get("LogoUrl") or web_cfg.get("Logo") or "").strip()
        logo_alt = str(web_cfg.get("LogoAlt") or "NC4ES Weather Alerts").strip() or "NC4ES Weather Alerts"
        return {
            "brand_logo_url": logo_url,
            "brand_logo_alt": logo_alt,
        }

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
            county_chat_links=county_chat_links_by_label(config),
            dev=dev_flag,
            generated_at=format_et(datetime.now(timezone.utc).isoformat()),
            radar=radar_config_from_config(config),
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
        db_error = None
        try:
            logs_raw = list_logs(db_path, hours=hours)
        except Exception as exc:
            LOGGER.exception("Could not read alert log database: %s", exc)
            logs_raw = []
            db_error = f"Could not open log database at {db_path}: {exc}"
        labels = {str(k): str(v) for k, v in (config.get("Alerting", {}).get("CountyLabels") or {}).items()}
        chat_links = county_chat_links_by_code(config)
        formatted = []
        for entry in logs_raw:
            zone = str(entry.get("county") or "UNKNOWN")
            copy = dict(entry)
            copy["timestamp_et"] = format_et(str(entry.get("timestamp") or ""))
            copy["county_label"] = labels.get(zone, zone)
            copy["county_chat_link"] = chat_links.get(zone, "")
            formatted.append(copy)
        used_zones = sorted({str(entry.get("county") or "UNKNOWN") for entry in logs_raw})
        county_labels = {zone: labels.get(zone, zone) for zone in used_zones}
        return render_template(
            "logs.html",
            logs=formatted,
            labels=county_labels,
            hours=hours,
            generated_at=format_et(datetime.now(timezone.utc).isoformat()),
            db_error=db_error,
        )

    @app.route("/weatheralerts/logs.json")
    def logs_json():
        config = cfg()
        hours = int(request.args.get("hours", config.get("Webapp", {}).get("LogHours", 24)) or 24)
        try:
            return jsonify(list_logs(db_path_from_config(config), hours=hours))
        except Exception as exc:
            LOGGER.exception("Could not read alert log database JSON: %s", exc)
            return jsonify({"error": "log database unavailable", "detail": str(exc)}), 500

    return app


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WeatherTelegramAlerts web dashboard")
    parser.add_argument("-c", "--config", default=str(BASE_DIR / "config.yaml"), help="Path to YAML config file")
    parser.add_argument("-p", "--port", type=int, default=None, help="Port to run the web server on")
    parser.add_argument("--host", default=None, help="Host/IP to bind")
    parser.add_argument("--waitress", action="store_true", help="Run this compatibility wrapper with the Waitress WSGI server")
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
