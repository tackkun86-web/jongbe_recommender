"""Telegram notifier — same Bot API call pattern as the existing notifier.py."""
from __future__ import annotations

import requests

from leader_watch.notifiers.base import AlertNotifier

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier(AlertNotifier):
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    def send(self, title: str, body: str) -> bool:
        if not self._bot_token or not self._chat_id:
            return False
        try:
            response = requests.post(
                _API_URL.format(token=self._bot_token),
                data={"chat_id": self._chat_id, "text": f"{title}\n\n{body}"},
                timeout=10,
            )
            return bool(getattr(response, "ok", False))
        except Exception:
            return False
