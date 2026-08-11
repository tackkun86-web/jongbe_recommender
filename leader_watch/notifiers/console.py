"""Console-output notifier, used for local simulation/testing."""
from __future__ import annotations

from leader_watch.notifiers.base import AlertNotifier


class ConsoleNotifier(AlertNotifier):
    def send(self, title: str, body: str) -> bool:
        print(f"\n{title}\n{body}\n")
        return True
