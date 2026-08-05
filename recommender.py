import json
import os
from datetime import datetime

import data_fetcher
import filters
import indicators
import input_loader
import overseas
import veto
from scorer import calculate_score, calculate_nxt_score
from risk_manager import generate_exit_rules, generate_nxt_exit_rules
from config import SCORE_WEIGHTS, NXT_SCORE_WEIGHTS

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
    files = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith("_close.json"))
    if not files:
        return set()
    try:
        with open(os.path.join(OUTPUT_DIR, files[-1]), encoding="utf-8") as f:
            prev = json.load(f)
        return {p["code"] for p in prev.get("picks", [])}
    except Exception:
        return set()


def _nxt_theme_streak(code: str, max_days: int = 5) -> int:
    if not os.path.isdir(OUTPUT_DIR):
        return 0
    today = datetime.now().strftime("%Y%m%d")
    files = sorted(
        f for f in os.listdir(OUTPUT_DIR)
        if f.endswith("_nxt.json") and not f.startswith(today)
    )
    streak = 0
    for filename in reversed(files[-max_days:]):
        try:
            with open(os.path.join(OUTPUT_DIR, filename), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            break
        codes = {p["code"] for p in data.get("picks", [])}
        if code in codes:
            streak += 1
        else:
            break
    return streak


def _load_recent_nxt_totals(max_days: int = 5) -> list[float]:
    if not os.path.isdir(OUTPUT_DIR):
        return []
    today = datetime.now().strftime("%Y%m%d")
    files = sorted(
        f for f in os.listdir(OUTPUT_DIR)
        if f.endswith("_nxt.json") and not f.startswith(today)
    )
    totals = []
    for filename in files[-max_days:]:
        try:
            with open(os.path.join(OUTPUT_DIR, filename), encoding="utf-8") as f:
                data = json.load(f)
            total = data.get("nxt_total_trade_value_eok")
            if total is not None:
                totals.append(total)
        except Exception:
            continue
    return totals


def _build_fallback_nxt_stocks() -> list[dict]:
    try:
        universe = _build_candidate_universe()
    except Exception:
        return []
    stocks = []
    for candidate in universe:
        hard_pass, _ = filters.apply_hard_filters({
            "name": candidate["name"],
            "market_cap_eok": candidate["market_cap_eok"],
            "change_pct": candidate["change_pct"],
            "trade_value_eok": candidate["trade_value_eok"],
        })
        if not hard_pass:
            continue
        stocks.append({
            "code": candidate["code"],
            "name": candidate["name"],
            "nxt_price": candidate["price"],
            "nxt_change_pct": candidate["change_pct"],
            "nxt_trade_value_eok": candidate["trade_value_eok"],
            "nxt_volume": candidate.get("volume", 0),
            "buy_sell_ratio": 1.0,
        })
    return stocks


def _evaluate_nxt_candidate(stock: dict, overseas_signals: dict):
    if stock.get("nxt_price") is None or stock.get("nxt_change_pct") is None:
        return None
    try:
        df = data_fetcher.get_stock_daily_data(stock["code"], days_needed=60)
        if len(df) < 20:
            return None
        investor_df = data_fetcher.get_investor_data(stock["code"], days_needed=5)
    except Exception:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    daily_change_pct = ((last["close"] - prev["close"]) / prev["close"] * 100
                         if prev["close"] else 0.0)
    daily_trade_value_eok = last["volume"] * last["close"] / 1e8

    candidate = {
        "name": stock["name"],
        "nxt_change_pct": stock.get("nxt_change_pct", 0),
        "nxt_trade_value_eok": stock.get("nxt_trade_value_eok", 0),
        "close": last["close"],
        "daily_change_pct": daily_change_pct,
        "daily_trade_value_eok": daily_trade_value_eok,
    }

    hard_pass, _ = filters.apply_nxt_hard_filters(candidate)
    if not hard_pass:
        return None

    ind = indicators.calculate_indicators(df)
    pattern = indicators.detect_pattern(df, ind)
    streak_days = _nxt_theme_streak(stock["code"])

    score_result = calculate_nxt_score(candidate, ind, df, investor_df, overseas_signals, streak_days)
    nxt_price = stock.get("nxt_price", last["close"])
    exit_rules = generate_nxt_exit_rules(nxt_price)

    return {
        "code": stock["code"],
        "name": stock["name"],
        "market": "NXT",
        "current_price": nxt_price,
        "daily_return": daily_change_pct,
        "trade_value_yuk": daily_trade_value_eok,
        "nxt_change_pct": candidate["nxt_change_pct"],
        "nxt_trade_value_yuk": candidate["nxt_trade_value_eok"],
        "pattern": pattern,
        "score": score_result["total"],
        "details": score_result["breakdown"],
        "exit_rules": exit_rules,
        "passed_threshold": score_result["total"] >= NXT_SCORE_WEIGHTS["recommend_threshold"],
    }


def run_nxt_analysis() -> dict:
    input_data = input_loader.load_nxt_signals(path=input_loader.DEFAULT_PATH)
    used_fallback = False
    if not input_data["nxt_stocks"]:
        input_data["nxt_stocks"] = _build_fallback_nxt_stocks()
        used_fallback = True

    market_index = data_fetcher.get_market_index()
    kospi_change_pct = market_index.get("kospi", {}).get("change_pct")

    recent_totals = _load_recent_nxt_totals()
    today_total = sum(s.get("nxt_trade_value_eok", 0) for s in input_data["nxt_stocks"])
    nxt_trade_value_ratio_pct = None
    if len(recent_totals) >= 5:
        avg = sum(recent_totals) / len(recent_totals)
        nxt_trade_value_ratio_pct = (today_total / avg * 100) if avg else None

    overseas_signals = {**overseas.get_overseas_indices(), **input_data["overseas"]}

    blocked, veto_reasons = veto.check_veto_conditions(
        overseas_signals, kospi_change_pct, input_data["events"], nxt_trade_value_ratio_pct
    )

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "session": "nxt",
        "session_label": SESSION_LABELS.get("nxt", "nxt"),
        "market": {
            "kospi": market_index.get("kospi", {"index": None, "change_pct": None}),
            "kosdaq": market_index.get("kosdaq", {"index": None, "change_pct": None}),
            "overseas": overseas_signals,
        },
        "nxt_total_trade_value_eok": today_total,
        "nxt_data_source": "fallback_regular_session" if used_fallback else "input_file",
        "veto_blocked": blocked,
        "veto_reasons": veto_reasons,
        "picks": [],
    }

    if blocked or not input_data["nxt_stocks"]:
        return result

    picks = []
    for stock in input_data["nxt_stocks"]:
        try:
            pick = _evaluate_nxt_candidate(stock, overseas_signals)
        except Exception:
            pick = None
        if pick is not None:
            picks.append(pick)

    picks.sort(key=lambda p: p["score"], reverse=True)
    top_picks = [p for p in picks if p["passed_threshold"]][:NXT_SCORE_WEIGHTS["top_n"]]
    for i, pick in enumerate(top_picks, start=1):
        pick["rank"] = i
        del pick["passed_threshold"]

    result["picks"] = top_picks
    return result


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
    if session == "nxt":
        return run_nxt_analysis()
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
