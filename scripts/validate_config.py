#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from weather_alerts.config import as_bool, load_config  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_config.py /path/to/config.yaml", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        config = load_config(path)
    except Exception as exc:
        print(f"ERROR: could not load config: {exc}", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []

    counties = config.get("Alerting", {}).get("CountyCodes") or []
    labels = config.get("Alerting", {}).get("CountyLabels") or {}
    chats = config.get("Alerting", {}).get("CountyChatMap") or {}
    telegram = config.get("Telegram", {}) or {}
    weather = config.get("WeatherAlerts", {}) or {}
    web = config.get("Webapp", {}) or {}

    if not counties:
        errors.append("Alerting.CountyCodes is empty")
    for code in counties:
        if code not in labels:
            warnings.append(f"No CountyLabels entry for {code}")
        if code not in chats and not telegram.get("ChatID"):
            errors.append(f"No CountyChatMap entry for {code}, and Telegram.ChatID is not set")

    token = str(telegram.get("BotToken") or "")
    if not token or "PUT_YOUR" in token:
        errors.append("Telegram.BotToken is missing or still a placeholder")
    if not telegram.get("ChatID") and not chats:
        errors.append("Set Telegram.ChatID or Alerting.CountyChatMap")

    user_agent = str(weather.get("UserAgent") or "")
    if not user_agent or "no-contact" in user_agent.lower():
        warnings.append("WeatherAlerts.UserAgent should identify your app and include contact info")

    if as_bool(web.get("RequireWebhookToken", web.get("RequireLogToken")), default=True):
        webhook_token = str(web.get("WebhookToken") or web.get("LogToken") or "")
        if not webhook_token or "CHANGE-ME" in webhook_token:
            errors.append("Webapp.WebhookToken is missing or still a placeholder")
        if len(webhook_token) < 24:
            warnings.append("Webapp.WebhookToken should be at least 24 characters")

    inject_alerts = config.get("DEV", {}).get("INJECTALERTS")
    if inject_alerts and isinstance(inject_alerts, dict):
        warnings.append("DEV.INJECTALERTS is a single mapping; list syntax is recommended")

    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)

    if errors:
        return 1
    print("Config validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
