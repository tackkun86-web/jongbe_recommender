"""Exclusion filters: 거래정지/관리종목/투자위험/ETF/ETN/인버스/레버리지/스팩/우선주."""
from __future__ import annotations

import re

from leader_watch.models import StockSnapshot

_ETF_ETN_KEYWORDS = (
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "HANARO", "KOSEF", "SOL", "ACE",
    "인버스", "레버리지", "2X", "선물", "스팩",
)

_PREFERRED_SHARE_SUFFIX = re.compile(r"(?:\d?우|\d?우[A-Z])$")


def _is_preferred_share(name: str) -> bool:
    return bool(_PREFERRED_SHARE_SUFFIX.search(name)) and not name.endswith("지주")


def is_excluded(snapshot: StockSnapshot) -> tuple[bool, str | None]:
    if snapshot.is_trading_halted:
        return True, "거래정지"
    if snapshot.is_administrative:
        return True, "관리종목"
    if snapshot.is_investment_alert:
        return True, "투자위험종목"
    if snapshot.is_etf_etn or any(keyword in snapshot.name for keyword in _ETF_ETN_KEYWORDS):
        return True, "ETF/ETN"
    if snapshot.is_preferred_share or _is_preferred_share(snapshot.name):
        return True, "우선주"
    return False, None
