"""Pure functions mapping raw KIS API response dicts to StockSnapshot/MinuteBar.

All field-name constants below are the implementer's best-effort mapping to
the commonly documented KIS Developers 국내주식 API response schema. They are
named `ASSUMPTION`s — see
docs/superpowers/specs/2026-08-12-real-provider-kis-design.md,
"구현 중 반드시 검증해야 할 가정". If your account's actual response uses
different field names, change ONLY the constants below; the mapping
functions' logic does not need to change.
"""
from __future__ import annotations

import datetime

from leader_watch.models import MinuteBar, StockSnapshot

# --- ASSUMPTION: quote/ranking field names ---
_F_CODE = "stck_shrn_iscd"
_F_NAME = "hts_kor_isnm"
_F_RANK = "data_rank"

_F_CURRENT_PRICE = "stck_prpr"
_F_OPEN_PRICE = "stck_oprc"
_F_HIGH_PRICE = "stck_hgpr"
_F_LOW_PRICE = "stck_lwpr"
_F_PREV_DIFF = "prdy_vrss"  # signed change vs previous close; prev_close is derived from this
_F_ACML_VOLUME = "acml_vol"
_F_ACML_TRADING_VALUE = "acml_tr_pbmn"
_F_SECTOR_NAME = "bstp_kor_isnm"
_F_STATUS_CODE = "iscd_stat_cls_code"
_F_EXECUTION_STRENGTH = "pgtr_symp_str"  # falls back to neutral 100.0 if absent/blank

# --- ASSUMPTION: iscd_stat_cls_code -> exclusion flag, per commonly documented
# KIS 종목상태구분코드 values. Verify the exact code set against real docs. ---
_ADMINISTRATIVE_CODES = {"51"}
_INVESTMENT_ALERT_CODES = {"52", "53", "54"}
_TRADING_HALTED_CODES = {"58"}

# --- ASSUMPTION: minute-bar field names ---
_F_BAR_TIME = "stck_cntg_hour"  # HHMMSS
_F_BAR_OPEN = "stck_oprc"
_F_BAR_HIGH = "stck_hgpr"
_F_BAR_LOW = "stck_lwpr"
_F_BAR_CLOSE = "stck_prpr"
_F_BAR_VOLUME = "cntg_vol"


def parse_ranking_row(row: dict) -> tuple[str, str, int]:
    code = row[_F_CODE]
    name = row[_F_NAME]
    rank = int(row[_F_RANK])
    return code, name, rank


def parse_sector_ranking(rows: list[dict]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for position, row in enumerate(rows, start=1):
        name = row[_F_NAME]
        raw_rank = row.get(_F_RANK)
        ranks[name] = int(raw_rank) if raw_rank else position
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
    current_price = float(quote[_F_CURRENT_PRICE])
    prev_diff = float(quote.get(_F_PREV_DIFF, 0.0))
    prev_close = current_price - prev_diff

    status_code = str(quote.get(_F_STATUS_CODE, ""))
    sector_name = quote.get(_F_SECTOR_NAME) or None
    theme_rank = theme_rank_by_sector.get(sector_name) if sector_name else None

    execution_strength_raw = quote.get(_F_EXECUTION_STRENGTH)
    execution_strength = (
        float(execution_strength_raw) if execution_strength_raw not in (None, "") else 100.0
    )

    return StockSnapshot(
        code=code,
        name=name,
        market=market,
        timestamp=received_at,
        current_price=current_price,
        prev_close=prev_close,
        open_price=float(quote[_F_OPEN_PRICE]),
        high_price=float(quote[_F_HIGH_PRICE]),
        low_price=float(quote[_F_LOW_PRICE]),
        cum_volume=int(float(quote[_F_ACML_VOLUME])),
        cum_trading_value=float(quote[_F_ACML_TRADING_VALUE]),
        market_trading_value_rank=market_rank,
        execution_strength=execution_strength,
        theme=sector_name,
        theme_trading_value_rank=theme_rank,
        news_today=False,
        news_continuing=False,
        is_administrative=status_code in _ADMINISTRATIVE_CODES,
        is_investment_alert=status_code in _INVESTMENT_ALERT_CODES,
        is_trading_halted=status_code in _TRADING_HALTED_CODES,
    )


def parse_minute_bar(row: dict, reference_date: datetime.date) -> MinuteBar:
    time_str = str(row[_F_BAR_TIME]).zfill(6)
    hour, minute = int(time_str[0:2]), int(time_str[2:4])
    timestamp = datetime.datetime(reference_date.year, reference_date.month, reference_date.day, hour, minute)
    return MinuteBar(
        timestamp=timestamp,
        open=float(row[_F_BAR_OPEN]),
        high=float(row[_F_BAR_HIGH]),
        low=float(row[_F_BAR_LOW]),
        close=float(row[_F_BAR_CLOSE]),
        volume=int(float(row[_F_BAR_VOLUME])),
    )
