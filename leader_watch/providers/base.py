"""MarketDataProvider interface — the only surface engine.py depends on."""
from __future__ import annotations

import abc
import datetime

from leader_watch.models import StockSnapshot


class MarketDataProvider(abc.ABC):
    @abc.abstractmethod
    def get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]:
        """Return the latest known snapshot (as of `now`) for every tracked stock."""
        raise NotImplementedError
