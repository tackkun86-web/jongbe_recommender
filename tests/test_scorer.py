import pandas as pd
from scorer import calculate_score


def _investor_df(foreign_list, inst_list):
    n = len(foreign_list)
    return pd.DataFrame({
        "date": [f"2026-01-{i+1:02d}" for i in range(n)],
        "foreign_net": foreign_list,
        "inst_net": inst_list,
    })


def test_score_trade_value_tiers():
    candidate = {"trade_value_eok": 2500, "change_pct": 5.0, "close": 100, "high": 100}
    ind = {"ma5": 110, "ma20": 100, "ma60": 90, "rsi14": 55, "macd_golden_cross": False}
    investor_df = _investor_df([0], [0])
    result = calculate_score(candidate, ind, "없음", investor_df, None, 0, False)
    assert "거래대금" in result["breakdown"][0]
    assert result["total"] >= 15  # trade value tier1 alone


def test_score_supply_dual_buy_bonus_and_cap():
    candidate = {"trade_value_eok": 100, "change_pct": 5.0, "close": 100, "high": 100}
    ind = {"ma5": 90, "ma20": 100, "ma60": 110, "rsi14": 55, "macd_golden_cross": False}
    investor_df = _investor_df([10, 10, 10], [10, 10, 10])
    result = calculate_score(candidate, ind, "없음", investor_df, None, 0, False)
    supply_lines = [b for b in result["breakdown"] if "수급" in b or "매수" in b]
    assert len(supply_lines) > 0
    assert result["total"] <= 105


def test_score_pattern_points_applied():
    candidate = {"trade_value_eok": 100, "change_pct": 5.0, "close": 100, "high": 100}
    ind = {"ma5": 90, "ma20": 80, "ma60": 70, "rsi14": 55, "macd_golden_cross": False}
    investor_df = _investor_df([0], [0])
    result_high = calculate_score(candidate, ind, "신고가", investor_df, None, 0, False)
    result_none = calculate_score(candidate, ind, "없음", investor_df, None, 0, False)
    assert result_high["total"] - result_none["total"] == 15


def test_score_optimal_candle_range_beats_high_range():
    candidate_optimal = {"trade_value_eok": 100, "change_pct": 5.0, "close": 100, "high": 100}
    candidate_high = {"trade_value_eok": 100, "change_pct": 12.0, "close": 100, "high": 100}
    ind = {"ma5": 90, "ma20": 80, "ma60": 70, "rsi14": 55, "macd_golden_cross": False}
    investor_df = _investor_df([0], [0])
    r_optimal = calculate_score(candidate_optimal, ind, "없음", investor_df, None, 0, False)
    r_high = calculate_score(candidate_high, ind, "없음", investor_df, None, 0, False)
    assert r_optimal["total"] > r_high["total"]
