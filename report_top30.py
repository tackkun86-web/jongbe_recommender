import datetime
import sys

import requests

import data_fetcher
import filters
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


TOP_N = 50


def build_top50() -> list[dict]:
    seen = {}
    for sosok in (0, 1):
        for row in data_fetcher.get_top_stocks_by_trade_value(sosok):
            seen[row["code"]] = row
    rows = [r for r in seen.values() if not filters.is_etf_etn_spac(r["name"])]
    rows.sort(key=lambda r: r["trade_value_eok"], reverse=True)
    return rows[:TOP_N]


def build_theme_map() -> dict[str, str]:
    # code -> name of the single hottest (highest change_pct) theme it
    # belongs to among all themes it's a member of.
    best: dict[str, tuple[float, str]] = {}
    for theme in data_fetcher.get_all_themes():
        for member in data_fetcher.get_theme_members(theme["theme_no"]):
            code = member["code"]
            if code not in best or theme["change_pct"] > best[code][0]:
                best[code] = (theme["change_pct"], theme["name"])
    return {code: name for code, (_, name) in best.items()}


def format_message(rows: list[dict], theme_map: dict[str, str]) -> str:
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    lines = [f"\U0001F4CA 거래대금 상위 {TOP_N} ({today} 15:00 기준)"]
    for i, r in enumerate(rows, 1):
        theme = theme_map.get(r["code"])
        theme_part = f" [{theme}]" if theme else ""
        lines.append(
            f"{i}. {r['name']} ({r['change_pct']:+.2f}%) - {r['trade_value_eok']:,.0f}억{theme_part}"
        )
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    return resp.status_code == 200


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = build_top50()
    theme_map = build_theme_map()
    message = format_message(rows, theme_map)
    print(message)
    ok = send_telegram(message)
    print(f"telegram sent: {ok}")


if __name__ == "__main__":
    main()
