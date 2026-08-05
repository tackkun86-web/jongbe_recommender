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


from scorer import calculate_nxt_score, _gap_up_frequency_pct, _match_sector_signal


def _gap_df():
    # 6 rows -> 5 gap comparisons; opens all above previous close = 100% gap-up frequency
    return pd.DataFrame({
        "date": [f"2026-01-{i+1:02d}" for i in range(6)],
        "close": [100, 101, 102, 103, 104, 105],
        "open": [99, 101.5, 102.5, 103.5, 104.5, 105.5],
        "high": [101, 102, 103, 104, 105, 106],
        "low": [98, 100, 101, 102, 103, 104],
        "volume": [1_000_000] * 6,
    })


def test_gap_up_frequency_all_gap_ups():
    freq = _gap_up_frequency_pct(_gap_df())
    assert freq == 100.0


def test_gap_up_frequency_returns_none_with_insufficient_history():
    df = _gap_df().head(3)
    assert _gap_up_frequency_pct(df) is None


def test_match_sector_signal_finds_semiconductor_keyword():
    signal, label = _match_sector_signal("SK하이닉스", {"sox_change_pct": -1.2})
    assert signal == -1.2
    assert "SOX" in label


def test_match_sector_signal_falls_back_to_average():
    signal, label = _match_sector_signal(
        "알수없는종목", {"sp500_futures_change_pct": 0.4, "nasdaq_futures_change_pct": 0.2}
    )
    assert abs(signal - 0.3) < 1e-9
    assert "평균" in label


def test_match_sector_signal_returns_none_when_no_data():
    signal, label = _match_sector_signal("알수없는종목", {})
    assert signal is None


def test_calculate_nxt_score_full_breakdown():
    candidate = {"name": "SK하이닉스", "nxt_change_pct": 6.0, "nxt_trade_value_eok": 300,
                 "close": 250_000, "daily_change_pct": 5.0}
    ind = {"ma5": 240_000, "ma20": 230_000, "week60_high_proximity_pct": 3.0}
    investor_df = _investor_df([10, 10, 10], [10, 10, 10])
    overseas = {"sox_change_pct": 1.0, "kospi200_night_futures_change_pct": 0.2,
                "sp500_futures_change_pct": 0.3, "usd_krw_change_pct": 0.1}
    result = calculate_nxt_score(candidate, ind, _gap_df(), investor_df, overseas, theme_streak_days=2)
    assert result["total"] > 0
    assert any("NXT 상승률" in b for b in result["breakdown"])
    assert any("동반 순매수" in b for b in result["breakdown"])
    assert any("테마 지속" in b for b in result["breakdown"])


def test_calculate_nxt_score_applies_risk_penalty_and_caps():
    candidate = {"name": "알수없는종목", "nxt_change_pct": -2.0, "nxt_trade_value_eok": 0.1,
                 "close": 10_000, "daily_change_pct": 12.0}
    ind = {"ma5": 10_500, "ma20": 11_000, "week60_high_proximity_pct": 20.0}
    investor_df = _investor_df([-10], [-10])
    overseas = {"kospi200_night_futures_change_pct": -1.0, "usd_krw_change_pct": 1.0,
                "sp500_futures_change_pct": -1.0}
    result = calculate_nxt_score(candidate, ind, _gap_df().head(3), investor_df, overseas,
                                  theme_streak_days=0)
    risk_lines = [b for b in result["breakdown"] if "하락" in b or "급등" in b or "과다" in b]
    assert len(risk_lines) >= 3
