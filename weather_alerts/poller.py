from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .config import BASE_DIR, as_bool, load_config, resolve_path
from .nws import NWSClient, time_keys
from .state import alert_key, load_state, save_state
from .telegram import TelegramSender
from .text import build_alert_message, modify_description

LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")


def setup_logging(config: dict[str, Any]) -> None:
    debug = as_bool(config.get("Logging", {}).get("Debug"), default=False)
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )


def state_file_from_config(config: dict[str, Any]) -> Path:
    configured = config.get("WeatherAlerts", {}).get("StateFile", "data/last_alerts.json")
    return resolve_path(configured, base_dir=BASE_DIR)


def file_log_dir_from_config(config: dict[str, Any]) -> Path:
    configured = config.get("Logging", {}).get("FileLogDir", "logs")
    return resolve_path(configured, base_dir=BASE_DIR)


def log_alert_to_file(config: dict[str, Any], zone: str | None, title: str, description: str) -> None:
    if not zone:
        return
    log_dir = file_log_dir_from_config(config)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{zone}.log"
    timestamp = datetime.now(timezone.utc).astimezone(EASTERN).isoformat()
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {title}\n{description}\n\n")
    except OSError as exc:
        LOGGER.error("Error writing file log for %s: %s", zone, exc)


def normalize_inject_alerts(raw: Any) -> list[dict[str, Any]]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def current_alerts_from_config(config: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    weather_cfg = config.get("WeatherAlerts", {}) or {}
    alert_cfg = config.get("Alerting", {}) or {}
    dev_cfg = config.get("DEV", {}) or {}
    telegram_cfg = config.get("Telegram", {}) or {}

    county_codes = [str(code) for code in (alert_cfg.get("CountyCodes") or [])]
    county_chat_map = {str(k): str(v) for k, v in (alert_cfg.get("CountyChatMap") or {}).items()}
    county_labels = {str(k): str(v) for k, v in (alert_cfg.get("CountyLabels") or {}).items()}
    default_chat_id = telegram_cfg.get("ChatID")

    if as_bool(dev_cfg.get("INJECT"), default=False):
        LOGGER.info("DEV injection mode is enabled")
        injected: list[dict[str, Any]] = []
        inject_chat_ids = [str(v) for v in (dev_cfg.get("InjectChatIDs") or [])]
        inject_alerts = normalize_inject_alerts(dev_cfg.get("INJECTALERTS"))
        all_targets = sorted(set(county_chat_map.values()) | ({str(default_chat_id)} if default_chat_id else set()))

        for item in inject_alerts:
            title = str(item.get("Title") or "Test Weather Alert")
            description = str(item.get("Description") or "")
            code = item.get("Code")
            code = str(code) if code else None
            if inject_chat_ids:
                targets = inject_chat_ids
            elif code and county_chat_map.get(code):
                targets = [county_chat_map[code]]
            else:
                targets = all_targets
            for chat_id in targets:
                injected.append(
                    {
                        "id": f"inject:{code or 'global'}:{chat_id}:{title}",
                        "zone": code,
                        "chat_id": chat_id,
                        "Title": title,
                        "Description": description,
                        "county_label": county_labels.get(code, code) if code else "DEV",
                    }
                )
        return injected, set()

    start_key, end_key = time_keys(alert_cfg.get("TimeType", "onset"))
    client = NWSClient(
        user_agent=weather_cfg.get("UserAgent") or "WeatherTelegramAlerts/2.0 (no-contact@example.com)",
        blocked_events=alert_cfg.get("GlobalBlockedEvents", []) or [],
        start_key=start_key,
        end_key=end_key,
        timeout=int(weather_cfg.get("RequestTimeout", 10) or 10),
    )
    result = client.fetch_many(county_codes)
    for alert in result.alerts:
        zone = str(alert.get("zone") or "")
        alert["chat_id"] = county_chat_map.get(zone) or default_chat_id
        alert["county_label"] = county_labels.get(zone, zone)
    return result.alerts, result.failed_zones


def post_web_log(config: dict[str, Any], *, county: str | None, event: str, description: str) -> None:
    web_cfg = config.get("Webapp", {}) or {}
    url = web_cfg.get("LogEndpoint")
    if not url:
        return
    token = web_cfg.get("WebhookToken") or web_cfg.get("LogToken")
    headers = {"X-WeatherAlerts-Token": str(token)} if token else {}
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "county": county or "ALL",
        "event": event,
        "description": description,
    }
    try:
        response = requests.post(str(url), json=payload, headers=headers, timeout=5)
        if response.status_code >= 400:
            LOGGER.warning("Web log POST failed: HTTP %s %s", response.status_code, response.text[:200])
    except requests.RequestException as exc:
        LOGGER.debug("Web log POST failed: %s", exc)


def serialize_state(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("id", "zone", "chat_id", "Title", "Description", "End", "county_label")
    output: list[dict[str, Any]] = []
    for alert in alerts:
        output.append({field: alert.get(field) for field in fields if field in alert})
    return output


def merge_state_for_failed_zones(
    *,
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    failed_zones: set[str],
) -> list[dict[str, Any]]:
    merged = {alert_key(entry): entry for entry in serialize_state(current)}
    for entry in previous:
        if str(entry.get("zone")) in failed_zones:
            merged.setdefault(alert_key(entry), entry)
    return list(merged.values())


def send_new_or_changed_alerts(
    *,
    config: dict[str, Any],
    sender: TelegramSender,
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
) -> int:
    max_words = int(config.get("SkyDescribe", {}).get("MaxWords", 150) or 150)
    prefix = str(config.get("DEV", {}).get("PrefixMessage", "") or "") if as_bool(config.get("DEV", {}).get("INJECT"), False) else ""
    previous_by_key = {alert_key(entry): entry for entry in previous}
    sent = 0

    for alert in current:
        key = alert_key(alert)
        old = previous_by_key.get(key)
        changed = (
            old is None
            or alert.get("Title") != old.get("Title")
            or alert.get("Description") != old.get("Description")
        )
        if not changed:
            continue

        title = str(alert.get("Title") or "Weather Alert")
        description = str(alert.get("Description") or "")
        county_label = str(alert.get("county_label") or alert.get("zone") or "")
        message = build_alert_message(
            title=title,
            description=description,
            county_label=county_label,
            prefix=prefix,
            max_words=max_words,
        )
        if sender.send(message, alert.get("chat_id")):
            sent += 1
        log_alert_to_file(config, alert.get("zone"), title, description)
        post_web_log(config, county=alert.get("zone"), event=title, description=description)
    return sent


def send_cleared_alerts(
    *,
    config: dict[str, Any],
    sender: TelegramSender,
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    failed_zones: set[str],
) -> int:
    current_keys = {alert_key(entry) for entry in current}
    sent = 0
    seen: set[tuple[str, str, str]] = set()
    for old in previous:
        zone = str(old.get("zone") or "")
        if zone in failed_zones:
            continue
        if alert_key(old) in current_keys:
            continue
        chat_id = str(old.get("chat_id") or config.get("Telegram", {}).get("ChatID") or "")
        title = str(old.get("Title") or "Weather alert")
        county_label = str(old.get("county_label") or zone or "this area")
        dedupe = (chat_id, zone, title)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        message = modify_description(f"ALL CLEAR: {title} has cleared for {county_label}.", max_words=60)
        if sender.send(message, chat_id):
            sent += 1
        post_web_log(config, county=zone or "ALL", event="ALL CLEAR", description=f"{title} cleared")
    return sent


def main_iteration(config: dict[str, Any]) -> None:
    state_path = state_file_from_config(config)
    previous = load_state(state_path)
    current, failed_zones = current_alerts_from_config(config)
    county_codes = {str(code) for code in (config.get("Alerting", {}).get("CountyCodes") or [])}

    if failed_zones and county_codes and failed_zones >= county_codes:
        LOGGER.warning("All configured NWS zones failed to fetch; preserving previous state and suppressing all-clear messages")
        return

    telegram_cfg = config.get("Telegram", {}) or {}
    bot_token = telegram_cfg.get("BotToken")
    if not bot_token:
        raise ValueError("Telegram.BotToken missing. Set it in private config.yaml or TELEGRAM_BOT_TOKEN.")
    sender = TelegramSender(
        bot_token=str(bot_token),
        uppercase=as_bool(config.get("WeatherAlerts", {}).get("Uppercase"), default=False),
    )

    cleared = send_cleared_alerts(
        config=config,
        sender=sender,
        current=current,
        previous=previous,
        failed_zones=failed_zones,
    )
    sent = send_new_or_changed_alerts(config=config, sender=sender, current=current, previous=previous)

    if not sent and not cleared:
        LOGGER.info("No new, changed, or cleared alerts.")
    else:
        LOGGER.info("Iteration complete: %s new/changed, %s cleared", sent, cleared)

    save_state(state_path, merge_state_for_failed_zones(current=current, previous=previous, failed_zones=failed_zones))


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WeatherTelegramAlerts poller")
    parser.add_argument("-c", "--config", default=str(BASE_DIR / "config.yaml"), help="Path to YAML config file")
    parser.add_argument("--once", action="store_true", help="Run one polling iteration and exit")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    setup_logging(config)
    interval = int(config.get("WeatherAlerts", {}).get("PollInterval", 300) or 300)
    LOGGER.info("Starting WeatherTelegramAlerts poller with interval=%ss", interval)

    if args.once:
        main_iteration(config)
        return 0

    while True:
        try:
            config = load_config(args.config)
            setup_logging(config)
            main_iteration(config)
        except KeyboardInterrupt:
            LOGGER.info("Interrupted; exiting")
            return 0
        except Exception as exc:
            LOGGER.exception("Unhandled poller exception: %s", exc)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(cli())
