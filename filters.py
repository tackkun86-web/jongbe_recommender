from config import EXCLUDED_NAME_KEYWORDS, HARD_FILTERS


def is_etf_etn_spac(name: str) -> bool:
    return any(keyword in name for keyword in EXCLUDED_NAME_KEYWORDS)


def apply_hard_filters(candidate: dict) -> tuple[bool, str]:
    if is_etf_etn_spac(candidate["name"]):
        return False, "etf_etn_spac"
    if candidate["market_cap_eok"] < HARD_FILTERS["min_market_cap_eok"]:
        return False, "market_cap"
    change_pct = candidate["change_pct"]
    if (change_pct < HARD_FILTERS["min_daily_return_pct"]
            or change_pct > HARD_FILTERS["max_daily_return_pct"]
            or change_pct >= HARD_FILTERS["limit_up_pct"]):
        return False, "return_range"
    if candidate["trade_value_eok"] < HARD_FILTERS["min_trade_value_eok"]:
        return False, "trade_value"
    return True, ""


def apply_trend_filters(candidate: dict, ma5: float, ma20: float,
                         close: float, high: float) -> tuple[bool, str]:
    if ma5 < ma20:
        return False, "ma_reverse"
    if high > 0:
        off_high_pct = (high - close) / high * 100
        if off_high_pct > HARD_FILTERS["max_close_off_high_pct"]:
            return False, "close_off_high"
    return True, ""
