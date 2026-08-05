from config import VETO_THRESHOLDS


def check_veto_conditions(overseas: dict, kospi_change_pct: float | None,
                           events: dict, nxt_trade_value_ratio_pct: float | None
                           ) -> tuple[bool, list[str]]:
    t = VETO_THRESHOLDS
    conditions = []

    v = overseas.get("kospi200_night_futures_change_pct")
    conditions.append((None if v is None else v <= t["night_futures_pct"],
                        "코스피200 야간선물 -0.5% 이상 하락"))

    v = overseas.get("sp500_futures_change_pct")
    conditions.append((None if v is None else v <= t["sp500_futures_pct"],
                        "S&P500 선물 -0.5% 이상 하락"))

    v = overseas.get("usd_krw_change_pct")
    conditions.append((None if v is None else v >= t["fx_change_pct"],
                        "원/달러 환율 +0.5% 이상 급등"))

    v = overseas.get("sox_change_pct")
    conditions.append((None if v is None else v <= t["sox_pct"],
                        "필라델피아 반도체지수 선물 -1% 이상 하락"))

    conditions.append((None if kospi_change_pct is None else kospi_change_pct <= t["kospi_close_pct"],
                        "코스피 -1.5% 이상 하락 마감"))

    conditions.append((bool(events.get("major_event_tomorrow", False)),
                        "익일 주요 경제지표/FOMC 등 고변동성 이벤트 예정"))

    v = nxt_trade_value_ratio_pct
    conditions.append((None if v is None else v < t["nxt_trade_value_ratio_pct"],
                        "NXT 애프터마켓 거래대금 직전 5일 평균 대비 50% 미만"))

    conditions.append((bool(events.get("geopolitical_shock", False)),
                        "돌발 지정학적 악재"))

    reasons = [label for matched, label in conditions if matched]
    return len(reasons) >= t["min_conditions"], reasons
