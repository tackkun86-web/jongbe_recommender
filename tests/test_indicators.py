import pandas as pd
from indicators import calculate_indicators, detect_pattern


def _df_from_closes(closes, highs=None, opens=None, lows=None, volumes=None):
    n = len(closes)
    highs = highs or [c * 1.01 for c in closes]
    opens = opens or [c * 0.99 for c in closes]
    lows = lows or [c * 0.98 for c in closes]
    volumes = volumes or [1_000_000] * n
    dates = [f"2026-01-{i+1:02d}" for i in range(n)]
    return pd.DataFrame({
        "date": dates, "close": closes, "open": opens,
        "high": highs, "low": lows, "volume": volumes,
    })


def test_calculate_indicators_ma_values():
    closes = [100] * 55 + [110, 111, 112, 113, 114]  # last 5 trend up
    df = _df_from_closes(closes)
    ind = calculate_indicators(df)
    assert round(ind["ma5"], 1) == round(sum(closes[-5:]) / 5, 1)
    assert round(ind["ma20"], 1) == round(sum(closes[-20:]) / 20, 1)
    assert ind["ma5"] > ind["ma20"]  # uptrend at the tail


def test_calculate_indicators_close_off_high_pct():
    df = _df_from_closes([100, 105], highs=[100, 110])
    ind = calculate_indicators(df)
    assert round(ind["close_off_high_pct"], 2) == round((110 - 105) / 110 * 100, 2)


def test_calculate_indicators_rsi_bounds():
    closes = list(range(100, 130))  # steadily rising -> RSI near 100
    df = _df_from_closes(closes)
    ind = calculate_indicators(df)
    assert 0 <= ind["rsi14"] <= 100
    assert ind["rsi14"] > 60


def test_detect_pattern_new_high():
    closes = [90] * 55 + [95, 96, 97, 98, 100]
    df = _df_from_closes(closes, opens=[c * 0.97 for c in closes])
    ind = calculate_indicators(df)
    pattern = detect_pattern(df, ind)
    assert pattern == "신고가"


def test_detect_pattern_none_for_flat_stock():
    closes = [100] * 60
    df = _df_from_closes(closes)
    ind = calculate_indicators(df)
    pattern = detect_pattern(df, ind)
    assert pattern == "없음"
