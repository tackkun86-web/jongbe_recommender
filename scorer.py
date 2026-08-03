from config import SCORE_WEIGHTS


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
