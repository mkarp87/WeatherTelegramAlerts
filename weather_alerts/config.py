from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from ruamel.yaml import YAML

BASE_DIR = Path(__file__).resolve().parent.parent
YAML = YAML(typ="safe")


def resolve_path(path_value: str | os.PathLike[str] | None, *, base_dir: Path | None = None) -> Path:
    """Resolve a config path. Relative paths are relative to the app root."""
    base = base_dir or BASE_DIR
    if not path_value:
        return base
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path


def load_config(config_path: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        loaded = YAML.load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Config must be a YAML mapping: {path}")
    config: dict[str, Any] = loaded
    apply_environment_overrides(config)
    return config


def apply_environment_overrides(config: dict[str, Any]) -> None:
    """Allow secrets and local runtime settings to be supplied by environment."""
    mappings = [
        ("TELEGRAM_BOT_TOKEN", ("Telegram", "BotToken")),
        ("TELEGRAM_CHAT_ID", ("Telegram", "ChatID")),
        ("WEATHERALERTS_USER_AGENT", ("WeatherAlerts", "UserAgent")),
        ("WEATHERALERTS_WEBHOOK_TOKEN", ("Webapp", "WebhookToken")),
        ("WEATHERALERTS_LOG_ENDPOINT", ("Webapp", "LogEndpoint")),
    ]
    for env_name, key_path in mappings:
        value = os.environ.get(env_name)
        if value:
            set_nested(config, key_path, value)


def set_nested(config: dict[str, Any], key_path: tuple[str, ...], value: Any) -> None:
    current = config
    for part in key_path[:-1]:
        existing = current.get(part)
        if not isinstance(existing, dict):
            existing = {}
            current[part] = existing
        current = existing
    current[key_path[-1]] = value


def get_nested(config: Mapping[str, Any], key_path: tuple[str, ...], default: Any = None) -> Any:
    current: Any = config
    for part in key_path:
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
