from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .text import telegram_chunks

LOGGER = logging.getLogger(__name__)


class TelegramSender:
    def __init__(
        self,
        *,
        bot_token: str,
        uppercase: bool = False,
        timeout: int = 10,
        session: requests.Session | None = None,
    ) -> None:
        if not bot_token:
            raise ValueError("Telegram BotToken is required")
        self.bot_token = bot_token
        self.uppercase = uppercase
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def send_url(self) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    def send(self, text: str, chat_id: str | int | None) -> bool:
        if not chat_id:
            LOGGER.error("Cannot send Telegram message without a chat_id")
            return False
        outgoing = text.upper() if self.uppercase else text
        ok = True
        for chunk in telegram_chunks(outgoing):
            ok = self._send_chunk(chunk, str(chat_id)) and ok
            time.sleep(0.2)
        return ok

    def _send_chunk(self, chunk: str, chat_id: str) -> bool:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        for attempt in (1, 2):
            try:
                response = self.session.post(self.send_url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                LOGGER.error("Telegram send failed for chat %s: %s", chat_id, exc)
                return False

            if response.status_code == 429 and attempt == 1:
                retry_after = 3
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after", retry_after))
                except Exception:
                    pass
                time.sleep(min(max(retry_after, 1), 30))
                continue

            if not response.ok:
                body = response.text[:500]
                LOGGER.error("Telegram send failed for chat %s: HTTP %s %s", chat_id, response.status_code, body)
                return False

            LOGGER.info("Sent Telegram message to chat %s", chat_id)
            return True
        return False
