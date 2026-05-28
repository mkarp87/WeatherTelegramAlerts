from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


def load_state(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    state_path = Path(path)
    try:
        with state_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        LOGGER.warning("State file is corrupt; starting with empty state: %s", exc)
        return []
    except OSError as exc:
        LOGGER.warning("Could not read state file; starting with empty state: %s", exc)
        return []

    if not isinstance(data, list):
        LOGGER.warning("State file does not contain a list; starting with empty state")
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def save_state(path: str | os.PathLike[str], state: list[dict[str, Any]]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, state_path)


def alert_key(entry: dict[str, Any]) -> str:
    return f"{entry.get('id', '')}:{entry.get('zone', '')}"
