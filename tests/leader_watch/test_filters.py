# tests/leader_watch/test_filters.py
import datetime
from leader_watch.filters import is_excluded
from leader_watch.models import StockSnapshot


def _snapshot(name="정상전자", **overrides):
    base = dict(
        code="000001", name=name, market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 5),
        current_price=10000, prev_close=9800, open_price=9900,
        high_price=10100, low_price=9850, cum_volume=100_000,
        cum_trading_value=1_000_000_000, market_trading_value_rank=20,
        execution_strength=110.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def test_normal_stock_is_not_excluded():
    excluded, reason = is_excluded(_snapshot())
    assert excluded is False
    assert reason is None


def test_trading_halted_is_excluded():
    excluded, reason = is_excluded(_snapshot(is_trading_halted=True))
    assert excluded is True
    assert reason == "거래정지"


def test_administrative_issue_is_excluded():
    excluded, reason = is_excluded(_snapshot(is_administrative=True))
    assert excluded is True
    assert reason == "관리종목"


def test_investment_alert_is_excluded():
    excluded, reason = is_excluded(_snapshot(is_investment_alert=True))
    assert excluded is True
    assert reason == "투자위험종목"


def test_etf_etn_by_flag_is_excluded():
    excluded, reason = is_excluded(_snapshot(is_etf_etn=True))
    assert excluded is True
    assert reason == "ETF/ETN"


def test_etf_by_name_keyword_is_excluded():
    excluded, reason = is_excluded(_snapshot(name="KODEX 반도체"))
    assert excluded is True
    assert reason == "ETF/ETN"


def test_leverage_inverse_spac_by_name_is_excluded():
    for name in ["KODEX 코스닥150선물인버스", "삼성 2X레버리지", "한화플러스스팩3호"]:
        excluded, reason = is_excluded(_snapshot(name=name))
        assert excluded is True, name
        assert reason == "ETF/ETN"


def test_preferred_share_by_name_suffix_is_excluded():
    for name in ["삼성전자우", "LG화학우B"]:
        excluded, reason = is_excluded(_snapshot(name=name))
        assert excluded is True, name
        assert reason == "우선주"


def test_common_share_ending_in_woo_syllable_not_excluded():
    # "우" mid-name (not a preferred-share suffix pattern) must not be excluded.
    excluded, reason = is_excluded(_snapshot(name="우리금융지주"))
    assert excluded is False
    assert reason is None
