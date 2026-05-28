#!/usr/bin/env python3
"""Compatibility wrapper for the WeatherTelegramAlerts poller."""

from weather_alerts.poller import cli

if __name__ == "__main__":
    raise SystemExit(cli())
