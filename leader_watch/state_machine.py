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
