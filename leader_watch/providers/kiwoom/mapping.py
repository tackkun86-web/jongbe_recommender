"""Pure functions mapping the kiwoom_bridge JSON schema to StockSnapshot/MinuteBar.

Unlike leader_watch/providers/kis/mapping.py, this file carries no
ASSUMPTION-tagged raw broker field names — kiwoom_bridge/ already normalizes
real Kiwoom TR responses into the clean JSON schema documented in Task 3 of
docs/superpowers/plans/2026-08-13-kiwoom-provider.md (mirroring
docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md, "브릿지 HTTP
프로토콜"). All broker-specific field-name guessing lives in
kiwoom_bridge/tr_client.py instead, tagged ASSUMPTION there.
"""
from __future__ import annotations

import datetime

from leader_watch.models import MinuteBar, StockSnapshot

_STATUS_ADMINISTRATIVE = "administrative"
_STATUS_INVESTMENT_ALERT = "investment_alert"
_STATUS_TRADING_HALTED = "trading_halted"


def parse_ranking_row(row: dict) -> tuple[str, str, int]:
    return row["code"], row["name"], int(row["rank"])


def parse_sector_ranking(rows: list[dict]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for position, row in enumerate(rows, start=1):
        raw_rank = row.get("rank")
        ranks[row["name"]] = int(raw_rank) if raw_rank else position
    return ranks


def quote_to_snapshot(
    quote: dict,
    code: str,
    name: str,
    market: str,
    received_at: datetime.datetime,
    market_rank: int,
    theme_rank_by_sector: dict[str, int],
) -> StockSnapshot:
    status = quote.get("status", "normal")
    sector_name = quote.get("sector") or None
    theme_rank = theme_rank_by_sector.get(sector_name) if sector_name else None
    # The bridge-supplied market (from Kiwoom's own field) wins when present;
    # `market` is only a fallback for when the bridge couldn't determine it.
    resolved_market = quote.get("market") or market

    execution_strength_raw = quote.get("execution_strength")
    execution_strength = (
        float(execution_strength_raw) if execution_strength_raw not in (None, "") else 100.0
    )

    return StockSnapshot(
        code=code,
        name=name,
        market=resolved_market,
        timestamp=received_at,
        current_price=float(quote["current_price"]),
        prev_close=float(quote["prev_close"]),
        open_price=float(quote["open"]),
        high_price=float(quote["high"]),
        low_price=float(quote["low"]),
        cum_volume=int(quote["volume"]),
        cum_trading_value=float(quote["trading_value"]),
        market_trading_value_rank=market_rank,
        execution_strength=execution_strength,
        theme=sector_name,
        theme_trading_value_rank=theme_rank,
        news_today=False,
        news_continuing=False,
        is_administrative=status == _STATUS_ADMINISTRATIVE,
        is_investment_alert=status == _STATUS_INVESTMENT_ALERT,
        is_trading_halted=status == _STATUS_TRADING_HALTED,
    )


def parse_minute_bar(row: dict, reference_date: datetime.date) -> MinuteBar:
    time_str = str(row["time"]).zfill(6)
    hour, minute = int(time_str[0:2]), int(time_str[2:4])
    timestamp = datetime.datetime(reference_date.year, reference_date.month, reference_date.day, hour, minute)
    return MinuteBar(
        timestamp=timestamp,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=int(row["volume"]),
    )
