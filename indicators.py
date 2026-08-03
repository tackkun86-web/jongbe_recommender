import pandas as pd


def calculate_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    high = df["high"]
    volume = df["volume"]

    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(min(60, len(close))).mean().iloc[-1]

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-9)
    rsi = 100 - (100 / (1 + rs))
    rsi14 = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd = macd_line.iloc[-1]
    macd_signal = signal_line.iloc[-1]
    golden_cross = (
        len(macd_line) >= 2
        and macd_line.iloc[-2] <= signal_line.iloc[-2]
        and macd_line.iloc[-1] > signal_line.iloc[-1]
    )

    vol_ma20 = volume.rolling(min(20, len(volume))).mean().iloc[-1]
    volume_ratio = volume.iloc[-1] / vol_ma20 if vol_ma20 else 1.0

    last_close = close.iloc[-1]
    last_high = high.iloc[-1]
    close_off_high_pct = (last_high - last_close) / last_high * 100 if last_high else 0.0

    week60 = high.tail(60)
    week60_high = week60.max()
    week60_high_proximity_pct = (
        (week60_high - last_close) / week60_high * 100 if week60_high else 0.0
    )

    return {
        "ma5": float(ma5) if not pd.isna(ma5) else last_close,
        "ma10": float(ma10) if not pd.isna(ma10) else last_close,
        "ma20": float(ma20) if not pd.isna(ma20) else last_close,
        "ma60": float(ma60) if not pd.isna(ma60) else last_close,
        "rsi14": float(rsi14),
        "macd": float(macd),
        "macd_signal": float(macd_signal),
        "macd_golden_cross": bool(golden_cross),
        "volume_ratio": float(volume_ratio),
        "close_off_high_pct": float(close_off_high_pct),
        "week60_high": float(week60_high),
        "week60_high_proximity_pct": float(week60_high_proximity_pct),
    }


def detect_pattern(df: pd.DataFrame, ind: dict) -> str:
    last = df.iloc[-1]
    is_bullish = last["close"] > last["open"]

    if (ind["week60_high_proximity_pct"] <= 7 and is_bullish
            and last["close"] > ind["ma5"]):
        return "신고가"

    recent10_high = df["high"].tail(10).max()
    if (recent10_high > 0 and last["close"] >= recent10_high * 0.98
            and last["close"] > df.iloc[-2]["close"]
            and ind["volume_ratio"] >= 1.5):
        return "전고점돌파"

    recent5 = df.tail(6)
    if len(recent5) >= 6:
        lead5 = recent5["close"].iloc[0:5]
        declining = (lead5.diff().dropna() <= 0).all() and lead5.iloc[0] > lead5.iloc[-1]
        body = abs(last["close"] - last["open"])
        lower_wick = min(last["close"], last["open"]) - last["low"]
        if declining and is_bullish and body > 0 and lower_wick >= body * 0.5:
            return "눌림회복"

    ten_day_return = (
        (last["close"] - df.iloc[-11]["close"]) / df.iloc[-11]["close"] * 100
        if len(df) > 10 else 0.0
    )
    if (last["close"] < ind["ma20"] and is_bullish
            and (ind["rsi14"] <= 40 or ten_day_return <= -10)):
        return "과대낙폭반등"

    return "없음"
