from filters import is_etf_etn_spac, apply_hard_filters, apply_trend_filters, apply_nxt_trade_ratio_filter, apply_nxt_hard_filters


def test_is_etf_etn_spac_detects_keyword():
    assert is_etf_etn_spac("KODEX 200") is True
    assert is_etf_etn_spac("삼성전자") is False
    assert is_etf_etn_spac("TIGER 2차전지테마") is True


def test_apply_hard_filters_passes_valid_candidate():
    candidate = {"name": "삼성전자", "market_cap_eok": 4_500_000,
                 "change_pct": 5.2, "trade_value_eok": 8500}
    passed, reason = apply_hard_filters(candidate)
    assert passed is True
    assert reason == ""


def test_apply_hard_filters_rejects_low_market_cap():
    candidate = {"name": "잡주", "market_cap_eok": 500,
                 "change_pct": 5.0, "trade_value_eok": 600}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "market_cap"


def test_apply_hard_filters_rejects_low_return():
    candidate = {"name": "종목", "market_cap_eok": 2000,
                 "change_pct": 1.5, "trade_value_eok": 600}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "return_range"


def test_apply_hard_filters_rejects_limit_up():
    candidate = {"name": "종목", "market_cap_eok": 2000,
                 "change_pct": 29.5, "trade_value_eok": 600}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "return_range"


def test_apply_hard_filters_rejects_low_trade_value():
    candidate = {"name": "종목", "market_cap_eok": 2000,
                 "change_pct": 5.0, "trade_value_eok": 100}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "trade_value"


def test_apply_hard_filters_rejects_etf_name():
    candidate = {"name": "KODEX 반도체", "market_cap_eok": 5000,
                 "change_pct": 5.0, "trade_value_eok": 1000}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "etf_etn_spac"


def test_apply_trend_filters_rejects_ma_reverse_alignment():
    passed, reason = apply_trend_filters({}, ma5=100, ma20=110, close=101, high=105)
    assert passed is False
    assert reason == "ma_reverse"


def test_apply_trend_filters_rejects_close_far_below_high():
    passed, reason = apply_trend_filters({}, ma5=110, ma20=100, close=95, high=100)
    assert passed is False
    assert reason == "close_off_high"


def test_apply_trend_filters_passes_healthy_candidate():
    passed, reason = apply_trend_filters({}, ma5=110, ma20=100, close=99, high=100)
    assert passed is True
    assert reason == ""


def test_apply_nxt_trade_ratio_filter_passes_above_threshold():
    passed, reason = apply_nxt_trade_ratio_filter(nxt_trade_value_eok=30, daily_trade_value_eok=500)
    assert passed is True
    assert reason == ""


def test_apply_nxt_trade_ratio_filter_rejects_below_threshold():
    passed, reason = apply_nxt_trade_ratio_filter(nxt_trade_value_eok=5, daily_trade_value_eok=500)
    assert passed is False
    assert reason == "nxt_trade_ratio"


def test_apply_nxt_hard_filters_passes_valid_candidate():
    candidate = {"name": "SK하이닉스", "daily_trade_value_eok": 8500,
                 "daily_change_pct": 5.0, "nxt_trade_value_eok": 300}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is True
    assert reason == ""


def test_apply_nxt_hard_filters_rejects_etf_name():
    candidate = {"name": "KODEX 반도체", "daily_trade_value_eok": 8500,
                 "daily_change_pct": 5.0, "nxt_trade_value_eok": 300}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is False
    assert reason == "etf_etn_spac"


def test_apply_nxt_hard_filters_rejects_low_daily_trade_value():
    candidate = {"name": "종목", "daily_trade_value_eok": 100,
                 "daily_change_pct": 5.0, "nxt_trade_value_eok": 300}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is False
    assert reason == "trade_value"


def test_apply_nxt_hard_filters_rejects_limit_up():
    candidate = {"name": "종목", "daily_trade_value_eok": 8500,
                 "daily_change_pct": 29.5, "nxt_trade_value_eok": 300}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is False
    assert reason == "limit_up"


def test_apply_nxt_hard_filters_rejects_thin_nxt_trade_value():
    candidate = {"name": "종목", "daily_trade_value_eok": 8500,
                 "daily_change_pct": 5.0, "nxt_trade_value_eok": 5}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is False
    assert reason == "nxt_trade_ratio"
