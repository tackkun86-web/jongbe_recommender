import json
import os
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def print_to_terminal(result: dict) -> str:
    lines = []
    date_str = result["date"]
    lines.append(f"=== 종가베팅 추천 ({date_str}) ===")
    kospi = result["market"]["kospi"]
    kosdaq = result["market"]["kosdaq"]
    lines.append(
        f"시장 상황: 코스피 {kospi.get('change_pct')}% | 코스닥 {kosdaq.get('change_pct')}%"
    )
    lines.append("야간선물/미국장: 데이터 없음 (미구현)")
    lines.append("")

    if not result["picks"]:
        lines.append("추천 종목 없음 (조건 충족 종목이 없습니다)")
    for pick in result["picks"]:
        lines.append(f"📌 추천 {pick['rank']}: [{pick['code']}] {pick['name']} | 점수: {pick['score']}/105")
        lines.append(f"   패턴: {pick['pattern']}")
        lines.append(f"   현재가: {pick['current_price']:,.0f}원 | 등락률: +{pick['daily_return']}%")
        lines.append(f"   거래대금: {pick['trade_value_yuk']:.0f}억")
        for detail in pick["details"]:
            lines.append(f"   - {detail}")
        er = pick["exit_rules"]
        lines.append(f"   - 익절: 1차 {er['take_profit_1']:,}원 / 2차 {er['take_profit_2']:,}원")
        lines.append(f"   - 손절: 타이트 {er['stop_loss_tight']:,}원 / 마지노선 {er['stop_loss_max']:,}원")
        lines.append(f"   - 전략: {er['strategy']} (시간컷 {er['time_cut']})")
        lines.append("")

    lines.append("[주의] 본 추천은 교육 목적이며 투자 성과를 보장하지 않습니다.")
    text = "\n".join(lines)
    print(text)
    return text


def save_json(result: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{result['date'].replace('-', '')}.json"
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


def send_telegram(result: dict) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    lines = [f"종가베팅 추천 ({result['date']})"]
    for pick in result["picks"]:
        lines.append(f"{pick['rank']}. [{pick['code']}] {pick['name']} - {pick['score']}점 ({pick['pattern']})")
    message = "\n".join(lines)
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def notify(result: dict) -> None:
    print_to_terminal(result)
    save_json(result)
    send_telegram(result)
