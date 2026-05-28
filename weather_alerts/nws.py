from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import requests
from dateutil import parser as date_parser

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    alerts: list[dict[str, Any]]
    failed_zones: set[str]


class NWSClient:
    def __init__(
        self,
        *,
        user_agent: str,
        blocked_events: Iterable[str] | None = None,
        start_key: str = "onset",
        end_key: str = "ends",
        timeout: int = 10,
        session: requests.Session | None = None,
    ) -> None:
        self.user_agent = user_agent or "WeatherTelegramAlerts/2.0 (no-contact@example.com)"
        self.blocked_events = list(blocked_events or [])
        self.start_key = start_key
        self.end_key = end_key
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/geo+json, application/json",
        }

    def fetch_many(self, county_codes: Iterable[str]) -> FetchResult:
        alerts: list[dict[str, Any]] = []
        failed_zones: set[str] = set()
        for zone in county_codes:
            zone = str(zone).strip()
            if not zone:
                continue
            try:
                alerts.extend(self.fetch_zone(zone))
            except Exception as exc:
                LOGGER.error("NWS fetch error for %s: %s", zone, exc)
                failed_zones.add(zone)
        return FetchResult(alerts=alerts, failed_zones=failed_zones)

    def fetch_zone(self, zone: str) -> list[dict[str, Any]]:
        response = self.session.get(
            "https://api.weather.gov/alerts/active",
            params={"zone": zone},
            timeout=self.timeout,
            headers=self.headers,
        )
        response.raise_for_status()
        payload = response.json()
        return self.parse_alerts(payload, zone)

    def parse_alerts(self, payload: dict[str, Any], zone: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        output: list[dict[str, Any]] = []
        for feature in payload.get("features", []) or []:
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties", {}) or {}
            event = str(props.get("event") or "").strip()
            if not event or self.is_blocked(event):
                continue

            start_raw = props.get(self.start_key) or props.get("effective") or props.get("onset")
            end_raw = props.get(self.end_key) or props.get("ends") or props.get("expires")
            if not start_raw or not end_raw:
                continue

            try:
                start_dt = date_parser.isoparse(str(start_raw)).astimezone(timezone.utc)
                end_dt = date_parser.isoparse(str(end_raw)).astimezone(timezone.utc)
            except (TypeError, ValueError) as exc:
                LOGGER.debug("Skipping alert with unparseable dates for %s: %s", zone, exc)
                continue

            if not (start_dt <= now < end_dt):
                continue

            output.append(
                {
                    "id": str(feature.get("id") or props.get("id") or f"{zone}:{event}:{start_raw}"),
                    "zone": zone,
                    "Title": event,
                    "Description": str(props.get("description") or "").strip(),
                    "Instruction": str(props.get("instruction") or "").strip(),
                    "Severity": str(props.get("severity") or ""),
                    "Urgency": str(props.get("urgency") or ""),
                    "Certainty": str(props.get("certainty") or ""),
                    "Start": start_dt.isoformat(),
                    "End": end_dt.isoformat(),
                }
            )
        return output

    def is_blocked(self, event: str) -> bool:
        return any(fnmatch.fnmatch(event, pattern) for pattern in self.blocked_events)


def time_keys(time_type: str | None) -> tuple[str, str]:
    normalized = str(time_type or "onset").strip().lower()
    if normalized == "effective":
        return "effective", "expires"
    return "onset", "ends"
