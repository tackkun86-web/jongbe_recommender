import datetime
from leader_watch.config import load_config
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.scoring import calculate_leader_score

CFG = load_config(env={})


def _snapshot(**overrides):
    base = dict(
        code="005930", name="테스트전자", market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 15),
        current_price=10600, prev_close=10000, open_price=10200,
        high_price=10650, low_price=10150, cum_volume=2_000_000,
        cum_trading_value=25_000_000_000, market_trading_value_rank=5,
        execution_strength=140.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False,
        minute_bars_1m=[], minute_bars_5m=[],
        avg_trading_value_same_time_20d=4_000_000_000,
        avg_volume_same_time_20d=400_000,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def test_top_tier_stock_scores_near_max():
    bars = [
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 5), 10100, 10200, 10050, 10150, 300_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 10), 10150, 10300, 10200, 10250, 150_000),
        MinuteBar(datetime.datetime(2026, 8, 11, 9, 15), 10250, 10650, 10240, 10600, 320_000),
    ]
    snap = _snapshot(minute_bars_1m=bars)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=3, config=CFG)
    assert breakdown.trading_value == 30          # rank 5 -> top 10 tier, 5x avg volume/value
    assert breakdown.theme_leadership == 20        # theme rank 1
    assert breakdown.price_strength >= 20           # +5% change, open held, high renewed
    assert breakdown.news == 10                     # today's news
    assert breakdown.total <= 100
    assert breakdown.missing_categories == []


def test_no_theme_data_is_marked_missing_and_scored_zero():
    snap = _snapshot(theme=None, theme_trading_value_rank=None)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=0, config=CFG)
    assert breakdown.theme_leadership == 0
    assert "theme_leadership" in breakdown.missing_categories


def test_single_stock_theme_with_no_followers_is_penalized_vs_multi_follower():
    lonely = _snapshot(theme_trading_value_rank=1)
    breakdown_lonely = calculate_leader_score(lonely, history=[lonely], theme_follower_count=0, config=CFG)
    crowded = _snapshot(theme_trading_value_rank=1)
    breakdown_crowded = calculate_leader_score(crowded, history=[crowded], theme_follower_count=3, config=CFG)
    assert breakdown_lonely.theme_leadership < breakdown_crowded.theme_leadership


def test_open_price_breach_zeroes_price_strength():
    snap = _snapshot(current_price=10000, open_price=10200, high_price=10300)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=2, config=CFG)
    assert breakdown.price_strength == 0


def test_trading_value_rank_outside_100_scores_zero():
    snap = _snapshot(market_trading_value_rank=250, avg_trading_value_same_time_20d=None)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=1, config=CFG)
    assert breakdown.trading_value == 0


def test_no_news_scores_zero_news_category():
    snap = _snapshot(news_today=False, news_continuing=False)
    breakdown = calculate_leader_score(snap, history=[snap], theme_follower_count=1, config=CFG)
    assert breakdown.news == 0
