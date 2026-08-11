"""Pure-function phase-transition logic for the leader-watch state machine."""
from __future__ import annotations

import datetime

from leader_watch.config import Config
from leader_watch.models import CandidateState, MinuteBar, ScoreBreakdown, StockSnapshot, safe_ratio
from leader_watch.scoring import calculate_leader_score

_MARKET_OPEN = datetime.time(9, 0)


def _meets_early_conditions(
    snapshot: StockSnapshot, market_rank: int, theme_rank: int | None, config: Config
) -> bool:
    if snapshot.timestamp.time() < _MARKET_OPEN:
        return False
    if market_rank > config.early_trading_value_rank:
        return False
    if snapshot.change_pct < 2.0:
        return False
    if snapshot.vs_open_pct < 0:
        return False
    if theme_rank is None or theme_rank > 2:
        return False
    if snapshot.avg_volume_same_time_20d and snapshot.cum_volume <= snapshot.avg_volume_same_time_20d:
        return False
    return True


def decide_early_candidate(
    snapshot: StockSnapshot,
    history: list[StockSnapshot],
    market_rank: int,
    theme_rank: int | None,
    theme_follower_count: int,
    prior_streak: int,
    config: Config,
) -> tuple[bool, ScoreBreakdown, int]:
    breakdown = calculate_leader_score(snapshot, history, theme_follower_count, config)

    if not _meets_early_conditions(snapshot, market_rank, theme_rank, config):
        return False, breakdown, 0

    if breakdown.total < config.early_min_score:
        return False, breakdown, 0

    new_streak = prior_streak + 1
    qualifies = new_streak >= 2
    return qualifies, breakdown, new_streak


def update_open_recovery_tracking(candidate: CandidateState, snapshot: StockSnapshot) -> int:
    if snapshot.vs_open_pct < 0:
        candidate.consecutive_open_recovery_fail += 1
    else:
        candidate.consecutive_open_recovery_fail = 0
    return candidate.consecutive_open_recovery_fail


def _declining_five_minute_highs(bars: list[MinuteBar]) -> bool:
    if len(bars) < 3:
        return False
    highs = [bar.high for bar in bars[-5:]]
    return all(earlier > later for earlier, later in zip(highs, highs[1:]))


def check_rejection(
    candidate: CandidateState,
    snapshot: StockSnapshot,
    history: list[StockSnapshot],
    market_rank: int,
    theme_rank: int | None,
    config: Config,
) -> str | None:
    from leader_watch.filters import is_excluded

    excluded, _ = is_excluded(snapshot)
    if excluded:
        return "거래정지, 관리종목, 투자위험 종목 등 제외 대상에 해당"

    if candidate.consecutive_open_recovery_fail >= 2 and snapshot.vs_open_pct < 0:
        return "시가 이탈 후 2회 연속 회복하지 못함"

    bars = snapshot.minute_bars_1m
    if len(bars) >= 2:
        avg_volume = sum(bar.volume for bar in bars[:-1]) / len(bars[:-1])
        if bars[-1].is_bearish_long_candle(avg_volume=avg_volume):
            return "거래량을 동반한 장대음봉 발생"

    if market_rank > 100:
        return "거래대금 순위가 100위 밖으로 하락"

    if theme_rank is None or theme_rank > 3:
        return "테마 내 거래대금 3위 밖으로 밀림"

    drawdown = safe_ratio(snapshot.high_price - snapshot.current_price, snapshot.high_price) * 100
    if drawdown > 5.0:
        return "고점 대비 하락률이 5% 초과"

    if _declining_five_minute_highs(snapshot.minute_bars_5m):
        return "최근 5분 동안 고점이 계속 낮아짐"

    return None


def classify_gap(gap_pct: float, config: Config) -> str:
    if gap_pct <= 3.0:
        return "정상"
    if gap_pct <= 5.0:
        return "강한 후보(추격 위험)"
    if gap_pct <= config.max_gap_percent:
        return "고위험"
    return "확정 제외"


def evaluate_confirmation(
    snapshot: StockSnapshot,
    history: list[StockSnapshot],
    market_rank: int,
    theme_rank: int | None,
    rank_at_0925: int | None,
    theme_follower_count: int,
    config: Config,
) -> tuple[bool, ScoreBreakdown, str | None]:
    breakdown = calculate_leader_score(snapshot, history, theme_follower_count, config)

    gap = snapshot.gap_from_prev_close_pct
    if gap > config.max_gap_percent and snapshot.execution_strength < 100:
        return False, breakdown, "갭 상승률이 8%를 초과하고 추가 매수세가 약함"

    if snapshot.vs_open_pct < 0:
        return False, breakdown, "첫 급등 후 시가를 이탈함"

    if not snapshot.news_today and not snapshot.news_continuing:
        prices = [snap.current_price for snap in history]
        sustained = len(prices) < 2 or prices[-1] > prices[0]
        if not sustained:
            return False, breakdown, "뉴스나 재료가 전혀 없고 상승 지속성도 확인되지 않음"

    drawdown = safe_ratio(snapshot.high_price - snapshot.current_price, snapshot.high_price) * 100
    if drawdown > config.max_confirmation_drawdown_percent:
        return False, breakdown, "고점 대비 하락률이 3% 초과"

    bars = snapshot.minute_bars_1m
    if len(bars) >= 2:
        avg_volume = sum(bar.volume for bar in bars[:-1]) / len(bars[:-1])
        if bars[-1].is_bearish_long_candle(avg_volume=avg_volume):
            return False, breakdown, "거래량을 동반한 장대음봉 발생"

    if theme_follower_count == 0:
        return False, breakdown, "테마 내 후속 종목이 전혀 없음"

    if _declining_five_minute_highs(snapshot.minute_bars_5m):
        return False, breakdown, "거래대금은 크지만 고점이 계속 낮아짐"

    if market_rank > config.confirmation_trading_value_rank:
        return False, breakdown, "09:30 누적 거래대금이 시장 상위 30위 밖"

    if theme_rank is None or theme_rank > 2:
        return False, breakdown, "테마 또는 섹터 내 거래대금 1~2위 조건 미충족"

    if rank_at_0925 is not None and market_rank > rank_at_0925:
        return False, breakdown, "09:25~09:30 구간 거래대금 순위 악화"

    if len(history) >= 2:
        minutes_covered = (history[-1].timestamp - history[0].timestamp).total_seconds() / 60
        if minutes_covered < 5:
            return False, breakdown, "데이터가 최소 5분 이상 지속적으로 수집되지 않음"

    if breakdown.total < config.confirmation_min_score:
        return False, breakdown, "총점 75점 미만"

    return True, breakdown, None
