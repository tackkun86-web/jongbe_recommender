import json
import os
from datetime import datetime

import data_fetcher
import filters
import indicators
from scorer import calculate_score
from risk_manager import generate_exit_rules
from config import SCORE_WEIGHTS

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

SESSION_LABELS = {
    "close": "정규장 마감",
    "nxt": "넥스트레이드(NXT) 마감",
}


def _build_candidate_universe() -> list[dict]:
    seen = {}
    for sosok, market in ((0, "KOSPI"), (1, "KOSDAQ")):
        for row in data_fetcher.get_top_stocks_by_trade_value(sosok, pages=2):
            row["market"] = market
            seen[row["code"]] = row
        for row in data_fetcher.get_top_gainers(sosok, pages=2):
            row["market"] = market
            seen.setdefault(row["code"], row)
    return list(seen.values())


def _load_prev_top_codes() -> set:
    if not os.path.isdir(OUTPUT_DIR):
        return set()
    files = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith(".json"))
    if not files:
        return set()
    try:
        with open(os.path.join(OUTPUT_DIR, files[-1]), encoding="utf-8") as f:
            prev = json.load(f)
        return {p["code"] for p in prev.get("picks", [])}
    except Exception:
        return set()


def _evaluate_candidate(candidate: dict, prev_top_codes: set):
    hard_pass, _ = filters.apply_hard_filters({
        "name": candidate["name"],
        "market_cap_eok": candidate["market_cap_eok"],
        "change_pct": candidate["change_pct"],
        "trade_value_eok": candidate["trade_value_eok"],
    })
    if not hard_pass:
        return None

    try:
        df = data_fetcher.get_stock_daily_data(candidate["code"], days_needed=60)
        if len(df) < 20:
            return None
        investor_df = data_fetcher.get_investor_data(candidate["code"], days_needed=5)
    except Exception:
        return None

    last = df.iloc[-1]
    ind = indicators.calculate_indicators(df)

    trend_pass, _ = filters.apply_trend_filters(
        candidate, ma5=ind["ma5"], ma20=ind["ma20"],
        close=last["close"], high=last["high"],
    )
    if not trend_pass:
        return None

    pattern = indicators.detect_pattern(df, ind)

    score_candidate = {
        "trade_value_eok": candidate["trade_value_eok"],
        "change_pct": candidate["change_pct"],
        "close": last["close"],
        "high": last["high"],
    }
    theme_continuity = candidate["code"] in prev_top_codes
    score_result = calculate_score(
        score_candidate, ind, pattern, investor_df,
        sector_rank=None, sector_trade_value_eok=0, theme_continuity=theme_continuity,
    )

    exit_rules = generate_exit_rules(pattern, last["close"])

    return {
        "code": candidate["code"],
        "name": candidate["name"],
        "market": candidate["market"],
        "current_price": last["close"],
        "daily_return": candidate["change_pct"],
        "trade_value_yuk": candidate["trade_value_eok"],
        "pattern": pattern,
        "score": score_result["total"],
        "details": score_result["breakdown"],
        "exit_rules": exit_rules,
        "passed_threshold": score_result["total"] >= SCORE_WEIGHTS["recommend_threshold"],
    }


def run_analysis(session: str = "close") -> dict:
    prev_top_codes = _load_prev_top_codes()
    universe = _build_candidate_universe()

    picks = []
    for candidate in universe:
        try:
            pick = _evaluate_candidate(candidate, prev_top_codes)
        except Exception:
            pick = None
        if pick is not None:
            picks.append(pick)

    picks.sort(key=lambda p: p["score"], reverse=True)
    qualified = [p for p in picks if p["passed_threshold"]]
    top_picks = qualified[:SCORE_WEIGHTS["top_n"]]
    if len(top_picks) < SCORE_WEIGHTS["min_recommend"]:
        chosen_ids = {id(p) for p in top_picks}
        fallback = [p for p in picks if id(p) not in chosen_ids]
        top_picks += fallback[: SCORE_WEIGHTS["min_recommend"] - len(top_picks)]
    for i, pick in enumerate(top_picks, start=1):
        pick["rank"] = i
        del pick["passed_threshold"]

    market_index = data_fetcher.get_market_index()

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "session": session,
        "session_label": SESSION_LABELS.get(session, session),
        "market": {
            "kospi": market_index.get("kospi", {"index": None, "change_pct": None}),
            "kosdaq": market_index.get("kosdaq", {"index": None, "change_pct": None}),
            "us_market": None,
            "overnight_futures": None,
        },
        "picks": top_picks,
    }
