import json
import os
from datetime import datetime

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "input", "nxt_signals.json")

_EMPTY_OVERSEAS = {
    "sp500_futures_change_pct": None,
    "nasdaq_futures_change_pct": None,
    "sox_change_pct": None,
    "kospi200_night_futures_change_pct": None,
    "us_10y_yield_change_bp": None,
    "hynix_adr_change_pct": None,
    "samsung_adr_change_pct": None,
}
_EMPTY_EVENTS = {"major_event_tomorrow": False, "event_desc": "", "geopolitical_shock": False}


def _empty_signals() -> dict:
    return {
        "date": None,
        "overseas": dict(_EMPTY_OVERSEAS),
        "events": dict(_EMPTY_EVENTS),
        "nxt_stocks": [],
    }


def load_nxt_signals(path: str = DEFAULT_PATH, today: str | None = None) -> dict:
    today = today or datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(path):
        return _empty_signals()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _empty_signals()
    if data.get("date") != today:
        return _empty_signals()

    merged = _empty_signals()
    merged["date"] = data.get("date")
    merged["overseas"].update(data.get("overseas") or {})
    merged["events"].update(data.get("events") or {})
    merged["nxt_stocks"] = data.get("nxt_stocks") or []
    return merged
