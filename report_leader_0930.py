import datetime
import sys

import requests

import data_fetcher
import filters
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TOP_THEMES = 5
TOP_STOCKS_PER_THEME = 3
MIN_UP_COUNT = 2


def build_leader_report() -> list[dict]:
    themes = [t for t in data_fetcher.get_theme_ranking() if t["up_count"] >= MIN_UP_COUNT]
    themes.sort(key=lambda t: t["change_pct"], reverse=True)

    report = []
    for theme in themes[:TOP_THEMES]:
        members = [m for m in data_fetcher.get_theme_members(theme["theme_no"])
                   if not filters.is_etf_etn_spac(m["name"])]
        members.sort(key=lambda m: m["change_pct"], reverse=True)
        report.append({
            "name": theme["name"],
            "change_pct": theme["change_pct"],
            "up_count": theme["up_count"],
            "down_count": theme["down_count"],
            "stocks": members[:TOP_STOCKS_PER_THEME],
        })
    return report


def format_message(report: list[dict]) -> str:
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    lines = [f"\U0001F4C8 오전 주도테마·주도주 ({today} 09:30 기준)"]
    for i, theme in enumerate(report, 1):
        lines.append(
            f"\n{i}. {theme['name']} ({theme['change_pct']:+.2f}%) "
            f"[상승 {theme['up_count']} / 하락 {theme['down_count']}]"
        )
        for stock in theme["stocks"]:
            lines.append(f"   - {stock['name']} ({stock['change_pct']:+.2f}%)")
    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
    return resp.status_code == 200


def run() -> None:
    report = build_leader_report()
    message = format_message(report)
    print(message)
    ok = send_telegram(message)
    print(f"telegram sent: {ok}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run()


if __name__ == "__main__":
    main()
