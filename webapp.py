#!/usr/bin/env python3
"""Compatibility wrapper for the WeatherTelegramAlerts web dashboard."""

from weather_alerts.web import cli

if __name__ == "__main__":
    raise SystemExit(cli())
