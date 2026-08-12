"""Hand-authored per-minute scenarios replayed by MockProvider.

Each scenario is a list of (minute_offset_from_09:00, StockSnapshot-kwargs) tuples.
MockProvider interpolates by "most recent tick at or before `now`".
"""
from __future__ import annotations

import datetime

from leader_watch.models import MinuteBar, StockSnapshot

_DATE = datetime.date(2026, 8, 11)


def _t(hh: int, mm: int) -> datetime.datetime:
    return datetime.datetime(_DATE.year, _DATE.month, _DATE.day, hh, mm)


def _bar(hh, mm, o, h, l, c, v) -> MinuteBar:
    return MinuteBar(timestamp=_t(hh, mm), open=o, high=h, low=l, close=c, volume=v)


def _snap(code, name, theme, theme_rank, t, **kw) -> StockSnapshot:
    defaults = dict(
        code=code, name=name, market="KOSPI", timestamp=t,
        theme=theme, theme_trading_value_rank=theme_rank,
        news_today=True, news_continuing=False,
        minute_bars_1m=[], minute_bars_5m=[],
        avg_trading_value_same_time_20d=3_000_000_000,
        avg_volume_same_time_20d=300_000,
        execution_strength=120.0,
    )
    defaults.update(kw)
    return StockSnapshot(**defaults)


def build_scenarios() -> dict[str, list[StockSnapshot]]:
    """Returns {code: [snapshot, snapshot, ...]} sorted by timestamp ascending."""
    scenarios: dict[str, list[StockSnapshot]] = {}

    # 1) LEAD01 — normal confirm, holds leadership through 10:30.
    # NOTE: growth coefficient is 40 (not a slower rate like 8) so that by the first
    # early-candidate tick (minute=6) price has already cleared both the +2% change_pct
    # gate and the open_price=10200 vs_open_pct>=0 gate; a slower ramp leaves vs_open_pct
    # negative through minute=18, which trips check_rejection's "2 consecutive open-breach"
    # rule during VALIDATION and rejects LEAD01 before it ever reaches CONFIRMATION.
    # NOTE: ticks are 1 minute apart (not 3) so that a poll 2 minutes after another still
    # lands on a fresh (< engine.Config.stale_threshold_seconds old) tick — with 3-minute
    # spacing, a poll landing between ticks replays a >=60s-stale snapshot that
    # engine.run_once's is_stale() filter drops entirely, silently starving the
    # early-candidate streak counter of its second observation.
    lead01 = []
    price = 10000
    for minute in range(0, 91, 1):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        price = 10000 + minute * 40
        lead01.append(_snap(
            "LEAD01", "리딩전자", "반도체", 1, t,
            current_price=price, prev_close=10000, open_price=10200,
            high_price=max(price, 10200), low_price=9950,
            cum_volume=300_000 + minute * 20_000, cum_trading_value=(300_000 + minute * 20_000) * price,
            market_trading_value_rank=max(1, 8 - minute // 15),
            minute_bars_1m=[_bar(9, 0, 10000, 10200, 9950, price, 300_000 + minute * 5_000)],
        ))
    scenarios["LEAD01"] = lead01

    # 2) FAIL01 — early candidate, breaches open twice in VALIDATION, rejected.
    fail01 = []
    for minute in range(0, 25, 2):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        price = 10300 if minute < 10 else 10000 - minute * 5  # breaches open after 09:10
        fail01.append(_snap(
            "FAIL01", "실패산업", "2차전지", 2, t,
            current_price=price, prev_close=10000, open_price=10200,
            high_price=10350, low_price=min(price, 9800),
            cum_volume=200_000 + minute * 10_000, cum_trading_value=(200_000 + minute * 10_000) * price,
            market_trading_value_rank=20,
        ))
    scenarios["FAIL01"] = fail01

    # 3) GAP01 — gap-up > 8%, weak follow-through, excluded from confirmation.
    gap01 = []
    for minute in range(0, 40, 5):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        price = 10900 - minute * 2
        gap01.append(_snap(
            "GAP01", "갭상승홀딩스", "바이오", 1, t,
            current_price=price, prev_close=10000, open_price=10900,
            high_price=10950, low_price=10850,
            cum_volume=150_000, cum_trading_value=150_000 * price,
            market_trading_value_rank=15, execution_strength=95.0,
        ))
    scenarios["GAP01"] = gap01

    # 4) RANK01 — big trading value but rank falls outside top 30 by 09:30.
    # theme is "반도체" (same as LEAD01) so LEAD01 has a theme_follower_count >= 1 at
    # confirmation time; evaluate_confirmation hard-blocks with "테마 내 후속 종목이 전혀
    # 없음" when theme_follower_count == 0, and LEAD01 was otherwise the only stock on
    # this theme. RANK01's own rank-based rejection story is unaffected by its theme label.
    rank01 = []
    for minute in range(0, 40, 5):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        rank01.append(_snap(
            "RANK01", "순위이탈전자", "반도체", 2, t,
            current_price=10400, prev_close=10000, open_price=10100,
            high_price=10450, low_price=10050,
            cum_volume=180_000, cum_trading_value=180_000 * 10400,
            market_trading_value_rank=10 + minute,  # climbs past 30 as time passes
        ))
    scenarios["RANK01"] = rank01

    # 5) WEAK01 — confirms normally, then weakens after 09:30 (drawdown > 5%).
    weak01 = []
    for minute in range(0, 91, 5):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        if minute <= 30:
            price = 10000 + minute * 10
        else:
            price = 10300 - (minute - 30) * 15
        weak01.append(_snap(
            "WEAK01", "약화전자", "조선", 1, t,
            current_price=price, prev_close=10000, open_price=10100,
            high_price=10300, low_price=min(price, 9900),
            cum_volume=250_000 + minute * 5_000, cum_trading_value=(250_000 + minute * 5_000) * price,
            market_trading_value_rank=6 if minute <= 30 else 40,
        ))
    scenarios["WEAK01"] = weak01

    # 6) CHAL01 / CHAL02 — same theme, CHAL02 overtakes CHAL01 after 09:40 (leader change).
    chal01, chal02 = [], []
    for minute in range(0, 91, 5):
        t = _t(9, 0) + datetime.timedelta(minutes=minute)
        p1 = 10000 + minute * 5 if minute <= 40 else 10200
        p2 = 10000 + minute * 3 if minute <= 40 else 10000 + minute * 12
        chal01.append(_snap(
            "CHAL01", "기존대장주", "로봇", 1 if minute <= 40 else 2, t,
            current_price=p1, prev_close=10000, open_price=10100,
            high_price=max(p1, 10200), low_price=9950,
            cum_volume=200_000, cum_trading_value=200_000 * p1,
            market_trading_value_rank=3 if minute <= 40 else 6,
        ))
        chal02.append(_snap(
            "CHAL02", "신규도전자", "로봇", 2 if minute <= 40 else 1, t,
            current_price=p2, prev_close=10000, open_price=10050,
            high_price=max(p2, 10100), low_price=9980,
            cum_volume=180_000 + minute * 3_000, cum_trading_value=(180_000 + minute * 3_000) * p2,
            market_trading_value_rank=5 if minute <= 40 else 2,
        ))
    scenarios["CHAL01"] = chal01
    scenarios["CHAL02"] = chal02

    # 7) STALE01 — data stops updating after 09:04 (simulates feed delay/staleness).
    stale01 = [
        _snap("STALE01", "지연데이터", "화학", 1, _t(9, 2),
              current_price=10300, prev_close=10000, open_price=10100,
              high_price=10350, low_price=10050,
              cum_volume=100_000, cum_trading_value=100_000 * 10300,
              market_trading_value_rank=25),
    ]
    scenarios["STALE01"] = stale01

    return scenarios
