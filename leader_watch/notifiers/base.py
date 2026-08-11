"""AlertNotifier interface — engine.py depends only on `send`."""
from __future__ import annotations

import abc


class AlertNotifier(abc.ABC):
    @abc.abstractmethod
    def send(self, title: str, body: str) -> bool:
        raise NotImplementedError
