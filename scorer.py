from config import SCORE_WEIGHTS, NXT_SCORE_WEIGHTS, SECTOR_KEYWORDS


def _score_trade_value(trade_value_eok: float) -> tuple[int, str]:
    w = SCORE_WEIGHTS["trade_value"]
    if trade_value_eok >= w["tier1_eok"]:
        return w["tier1_pts"], f"거래대금 {trade_value_eok:.0f}억 ({w['tier1_pts']}점)"
    if trade_value_eok >= w["tier2_eok"]:
        return w["tier2_pts"], f"거래대금 {trade_value_eok:.0f}억 ({w['tier2_pts']}점)"
    if trade_value_eok >= w["tier3_eok"]:
        return w["tier3_pts"], f"거래대금 {trade_value_eok:.0f}억 ({w['tier3_pts']}점)"
    return 0, "거래대금 부족 (0점)"


def _score_trend(ind: dict, close: float) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["trend"]
    pts, notes = 0, []
    if ind["ma5"] > ind["ma20"] > ind["ma60"]:
        pts += w["aligned_pts"]
        notes.append(f"이평 정배열 ({w['aligned_pts']}점)")
    if close > ind["ma5"]:
        pts += w["above_ma5_pts"]
        notes.append(f"5일선 위 ({w['above_ma5_pts']}점)")
    return pts, notes


def _score_candle(candidate: dict) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["candle"]
    pts, notes = 0, []
    change_pct = candidate["change_pct"]
    if w["optimal_low"] <= change_pct <= w["optimal_high"]:
        pts += w["optimal_pts"]
        notes.append(f"등락률 최적구간 ({w['optimal_pts']}점)")
    elif change_pct <= w["good_high"]:
        pts += w["good_pts"]
        notes.append(f"등락률 양호구간 ({w['good_pts']}점)")

    high, close = candidate["high"], candidate["close"]
    if high > 0:
        off_high = (high - close) / high * 100
        if off_high <= w["close_near_high_pct"]:
            pts += w["close_near_high_pts"]
            notes.append(f"종가 고가권 ({w['close_near_high_pts']}점)")
        elif off_high <= w["close_mid_high_pct"]:
            pts += w["close_mid_high_pts"]
            notes.append(f"종가 준고가권 ({w['close_mid_high_pts']}점)")
    return pts, notes


def _score_supply(investor_df, ind: dict) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["supply"]
    pts, notes = 0, []
    if investor_df is None or len(investor_df) == 0:
        return 0, ["수급 데이터 없음 (0점)"]

    last_foreign = investor_df["foreign_net"].iloc[-1]
    last_inst = investor_df["inst_net"].iloc[-1]

    foreign_buy = last_foreign > 0
    inst_buy = last_inst > 0

    if foreign_buy:
        pts += w["foreign_buy_pts"]
        notes.append(f"외국인 순매수 ({w['foreign_buy_pts']}점)")
    if inst_buy:
        pts += w["inst_buy_pts"]
        notes.append(f"기관 순매수 ({w['inst_buy_pts']}점)")
    if foreign_buy and inst_buy:
        pts += w["both_bonus_pts"]
        notes.append(f"쌍끌이 보너스 ({w['both_bonus_pts']}점)")

    tail3 = investor_df["foreign_net"].tail(3)
    if len(tail3) == 3 and (tail3 > 0).all():
        pts += w["foreign_streak_pts"]
        notes.append(f"외국인 3일 연속 순매수 ({w['foreign_streak_pts']}점)")

    return min(pts, w["cap"]), notes


def _score_theme(sector_rank, sector_trade_value_eok, theme_continuity) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["theme"]
    pts, notes = 0, []
    if sector_rank is not None and sector_rank <= 3:
        pts += w["top3_sector_pts"]
        notes.append(f"거래대금 상위 섹터 ({w['top3_sector_pts']}점)")
    if sector_rank is not None and sector_rank <= 2 and sector_trade_value_eok >= w["leader_min_eok"]:
        pts += w["leader_pts"]
        notes.append(f"섹터 대장/2등주 ({w['leader_pts']}점)")
    if theme_continuity:
        pts += w["continuity_pts"]
        notes.append(f"테마 지속성 ({w['continuity_pts']}점)")
    return pts, notes


def _score_pattern(pattern: str) -> tuple[int, str]:
    pts = SCORE_WEIGHTS["pattern"].get(pattern, 0)
    return pts, f"패턴: {pattern} ({pts}점)"


def _score_bonus(ind: dict) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["bonus"]
    pts, notes = 0, []
    if ind.get("macd_golden_cross"):
        pts += w["macd_cross_pts"]
        notes.append(f"MACD 골든크로스 ({w['macd_cross_pts']}점)")
    rsi = ind.get("rsi14", 0)
    if w["rsi_low"] <= rsi <= w["rsi_high"]:
        pts += w["rsi_range_pts"]
        notes.append(f"RSI 적정구간 ({w['rsi_range_pts']}점)")
    return pts, notes


def calculate_score(candidate: dict, ind: dict, pattern: str, investor_df,
                     sector_rank, sector_trade_value_eok: float,
                     theme_continuity: bool) -> dict:
    breakdown = []
    total = 0

    pts, note = _score_trade_value(candidate["trade_value_eok"])
    total += pts
    breakdown.append(note)

    pts, notes = _score_trend(ind, candidate["close"])
    total += pts
    breakdown.extend(notes)

    pts, notes = _score_candle(candidate)
    total += pts
    breakdown.extend(notes)

    pts, notes = _score_supply(investor_df, ind)
    total += pts
    breakdown.extend(notes)

    pts, notes = _score_theme(sector_rank, sector_trade_value_eok, theme_continuity)
    total += pts
    breakdown.extend(notes)

    pts, note = _score_pattern(pattern)
    total += pts
    breakdown.append(note)

    pts, notes = _score_bonus(ind)
    total += pts
    breakdown.extend(notes)

    return {"total": total, "breakdown": breakdown}


def _score_nxt_flow(nxt_change_pct: float, nxt_trade_value_eok: float) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["nxt_flow"]
    if nxt_trade_value_eok < w["min_trade_value_eok"]:
        return w["thin_pts"], f"NXT 거래대금 부족 ({w['thin_pts']}점)"
    if nxt_change_pct >= w["t1_pct"]:
        return w["t1_pts"], f"NXT 상승률 {nxt_change_pct:.1f}% ({w['t1_pts']}점)"
    if nxt_change_pct >= w["t2_pct"]:
        return w["t2_pts"], f"NXT 상승률 {nxt_change_pct:.1f}% ({w['t2_pts']}점)"
    if nxt_change_pct >= w["t3_pct"]:
        return w["t3_pts"], f"NXT 상승률 {nxt_change_pct:.1f}% ({w['t3_pts']}점)"
    if nxt_change_pct >= 0:
        return w["t4_pts"], f"NXT 상승률 {nxt_change_pct:.1f}% ({w['t4_pts']}점)"
    return 0, f"NXT 하락 {nxt_change_pct:.1f}% (0점)"


def _score_nxt_supply(investor_df) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["supply"]
    if investor_df is None or len(investor_df) == 0:
        return 0, "수급 데이터 없음 (0점)"
    last_foreign = investor_df["foreign_net"].iloc[-1]
    last_inst = investor_df["inst_net"].iloc[-1]
    foreign_buy = last_foreign > 0
    inst_buy = last_inst > 0
    if foreign_buy and inst_buy:
        return w["both_pts"], f"외국인+기관 동반 순매수 ({w['both_pts']}점)"
    if foreign_buy or inst_buy:
        return w["single_pts"], f"단일 순매수 ({w['single_pts']}점)"
    if last_foreign == 0 and last_inst == 0:
        return w["flat_pts"], f"수급 보합 ({w['flat_pts']}점)"
    return w["sell_pts"], "순매도 (0점)"


def _score_nxt_theme(streak_days: int) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["theme"]
    if streak_days >= 2:
        return w["streak_pts"], f"테마 지속 {streak_days}일차 ({w['streak_pts']}점)"
    if streak_days == 1:
        return w["single_day_pts"], f"당일 발생 테마 ({w['single_day_pts']}점)"
    return w["none_pts"], "테마 연속성 없음 (0점)"


def _match_sector_signal(name: str, overseas: dict) -> tuple[float | None, str]:
    for entry in SECTOR_KEYWORDS:
        if any(kw in name for kw in entry["keywords"]):
            return overseas.get(entry["signal"]), entry["label"]
    sp = overseas.get("sp500_futures_change_pct")
    nq = overseas.get("nasdaq_futures_change_pct")
    vals = [v for v in (sp, nq) if v is not None]
    if vals:
        return sum(vals) / len(vals), "S&P/나스닥 평균"
    return None, "매칭 실패"


def _score_nxt_overseas(name: str, overseas: dict) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["overseas"]
    signal, label = _match_sector_signal(name, overseas)
    if signal is None:
        return 0, f"해외 선행 신호 데이터 부족 ({label}) (0점)"
    if signal > w["flat_band_pct"]:
        return w["up_pts"], f"해외 선행 신호 상승 ({label} {signal:+.2f}%) ({w['up_pts']}점)"
    if signal >= -w["flat_band_pct"]:
        return w["flat_pts"], f"해외 선행 신호 보합 ({label} {signal:+.2f}%) ({w['flat_pts']}점)"
    return w["down_pts"], f"해외 선행 신호 하락 ({label} {signal:+.2f}%) (0점)"


def _score_nxt_technical(ind: dict, close: float) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["technical"]
    if ind["week60_high_proximity_pct"] <= w["proximity_pct"]:
        return w["breakout_pts"], f"전고점 근접/돌파 임박 ({w['breakout_pts']}점)"
    if close > ind["ma5"]:
        return w["above_ma_pts"], f"5일선 위 ({w['above_ma_pts']}점)"
    return w["below_ma_pts"], "이평선 하단 (0점)"


def _gap_up_frequency_pct(df) -> float | None:
    if len(df) < 6:
        return None
    tail = df.tail(6).reset_index(drop=True)
    ups = sum(
        1 for i in range(1, len(tail))
        if tail.loc[i, "open"] > tail.loc[i - 1, "close"]
    )
    return ups / (len(tail) - 1) * 100


def _score_nxt_gap(df) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["gap"]
    freq = _gap_up_frequency_pct(df)
    if freq is None:
        return 0, "갭상승 빈도 데이터 부족 (0점)"
    if freq >= w["freq_high_pct"]:
        return w["freq_high_pts"], f"갭상승 빈도 {freq:.0f}% ({w['freq_high_pts']}점)"
    if freq >= w["freq_mid_pct"]:
        return w["freq_mid_pts"], f"갭상승 빈도 {freq:.0f}% ({w['freq_mid_pts']}점)"
    return w["freq_low_pts"], f"갭상승 빈도 {freq:.0f}% (0점)"


def _score_nxt_risk(overseas: dict, daily_change_pct: float) -> tuple[int, list[str]]:
    w = NXT_SCORE_WEIGHTS["risk"]
    pts, notes = 0, []
    night = overseas.get("kospi200_night_futures_change_pct")
    if night is not None and night < 0:
        pts += w["night_futures_pts"]
        notes.append(f"야간선물 하락 ({w['night_futures_pts']}점)")
    fx = overseas.get("usd_krw_change_pct")
    if fx is not None and fx >= 1.0:
        pts += w["fx_surge_pts"]
        notes.append(f"환율 급등 ({w['fx_surge_pts']}점)")
    sp = overseas.get("sp500_futures_change_pct")
    if sp is not None and sp < 0:
        pts += w["us_futures_pts"]
        notes.append(f"미국 선물 하락 ({w['us_futures_pts']}점)")
    if daily_change_pct is not None and daily_change_pct >= 10.0:
        pts += w["overheat_pts"]
        notes.append(f"당일 상승률 과다 ({w['overheat_pts']}점)")
    return max(pts, w["cap"]), notes


def calculate_nxt_score(candidate: dict, ind: dict, df, investor_df,
                         overseas: dict, theme_streak_days: int) -> dict:
    breakdown = []
    total = 0

    pts, note = _score_nxt_flow(candidate["nxt_change_pct"], candidate["nxt_trade_value_eok"])
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_supply(investor_df)
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_theme(theme_streak_days)
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_overseas(candidate["name"], overseas)
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_technical(ind, candidate["close"])
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_gap(df)
    total += pts
    breakdown.append(note)

    pts, notes = _score_nxt_risk(overseas, candidate["daily_change_pct"])
    total += pts
    breakdown.extend(notes)

    return {"total": total, "breakdown": breakdown}
