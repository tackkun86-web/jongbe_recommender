import json
import os
import re
import sys
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def print_to_terminal(result: dict) -> str:
    lines = []
    date_str = result["date"]
    header_suffix = f" {result['time']} · {result['session_label']}" if result.get("session_label") else ""
    lines.append(f"=== 종가베팅 추천 ({date_str}{header_suffix}) ===")
    kospi = result["market"]["kospi"]
    kosdaq = result["market"]["kosdaq"]
    lines.append(
        f"시장 상황: 코스피 {kospi.get('change_pct')}% | 코스닥 {kosdaq.get('change_pct')}%"
    )
    if result.get("session") != "nxt":
        lines.append("야간선물/미국장: 데이터 없음 (미구현)")
    lines.append("")

    if not result["picks"]:
        lines.append("추천 종목 없음 (조건 충족 종목이 없습니다)")
    for pick in result["picks"]:
        max_score = 100 if pick.get("market") == "NXT" else 105
        lines.append(f"[추천 {pick['rank']}] [{pick['code']}] {pick['name']} | 점수: {pick['score']}/{max_score}")
        lines.append(f"   패턴: {pick['pattern']}")
        lines.append(f"   현재가: {pick['current_price']:,.0f}원 | 등락률: {pick['daily_return']:+.2f}%")
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
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="replace").decode(encoding))
    return text


def save_json(result: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    session = result.get("session", "close")
    filename = f"{result['date'].replace('-', '')}_{session}.json"
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


def _top_reasons(details: list[str], n: int = 3) -> list[str]:
    def score_of(text: str) -> int:
        m = re.search(r"\((\d+)점\)", text)
        return int(m.group(1)) if m else 0

    return sorted(details, key=score_of, reverse=True)[:n]


def send_telegram(result: dict) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    header_suffix = f" {result['time']} · {result['session_label']}" if result.get("session_label") else ""
    lines = [f"종가베팅 추천 ({result['date']}{header_suffix})"]
    if not result["picks"]:
        lines.append("")
        lines.append("추천 종목 없음")
    for pick in result["picks"]:
        lines.append(
            f"{pick['rank']}. [{pick['code']}] {pick['name']} - {pick['score']}점 ({pick['pattern']})"
        )
        if pick["details"]:
            reasons = ", ".join(_top_reasons(pick["details"]))
            lines.append(f"   이유: {reasons}")
        er = pick["exit_rules"]
        lines.append(
            f"   익절: 1차 {er['take_profit_1']:,} / 2차 {er['take_profit_2']:,}"
        )
        lines.append(
            f"   손절: 타이트 {er['stop_loss_tight']:,} / 마지노선 {er['stop_loss_max']:,}"
        )
        lines.append(f"   전략: {er['strategy']} (시간컷 {er['time_cut']})")
    message = "\n".join(lines)
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def format_nxt_report(result: dict) -> str:
    lines = [f"# {result['date']} NXT 종가베팅 추천 리포트", f"## 발행 시각: {result['time']} KST", ""]

    if result.get("nxt_data_source") == "fallback_regular_session":
        lines.append(
            "> ⚠️ NXT 입력 데이터(`input/nxt_signals.json`) 없음 — 정규장 상승률/거래대금 "
            "상위 종목으로 대체하여 분석했습니다. 실제 NXT 애프터마켓 체결가와 다를 수 있습니다."
        )
        lines.append("")

    overseas_data = result["market"].get("overseas", {})
    lines.append("## 1. 시장 요약")
    lines.append("")
    lines.append("### 해외 선행 신호")
    lines.append("| 지표 | 등락률 |")
    lines.append("|---|---|")
    fields = [
        ("S&P500 지수", "sp500_change_pct"), ("나스닥 지수", "nasdaq_change_pct"),
        ("다우 지수", "dow_change_pct"),
        ("S&P500 선물", "sp500_futures_change_pct"), ("나스닥100 선물", "nasdaq_futures_change_pct"),
        ("SOX(반도체) 선물", "sox_change_pct"), ("코스피200 야간선물", "kospi200_night_futures_change_pct"),
        ("SK하이닉스 ADR", "hynix_adr_change_pct"), ("삼성전자 ADR", "samsung_adr_change_pct"),
        ("미국 10년물 금리(bp)", "us_10y_yield_change_bp"),
        ("원/달러 환율", "usd_krw_change_pct"), ("WTI 유가", "wti_change_pct"),
    ]
    def _fmt_pct(value):
        return "데이터 부족" if value is None else f"{value:+.2f}%"

    for label, key in fields:
        value = overseas_data.get(key)
        if key == "us_10y_yield_change_bp":
            display = "데이터 부족" if value is None else f"{value:+.1f}bp"
        else:
            display = _fmt_pct(value)
        lines.append(f"| {label} | {display} |")
    lines.append("")

    kospi = result["market"]["kospi"]
    kosdaq = result["market"]["kosdaq"]
    lines.append("### 코스피/코스닥")
    lines.append(f"- 코스피: {_fmt_pct(kospi.get('change_pct'))} / 코스닥: {_fmt_pct(kosdaq.get('change_pct'))}")
    lines.append("")

    total = result.get("nxt_total_trade_value_eok")
    lines.append("### NXT 애프터마켓 요약")
    lines.append(f"- 관찰 종목 합산 거래대금: {total if total is not None else '데이터 부족'}억원")
    lines.append("")

    lines.append("## 2. 추천 종목")
    lines.append("")
    if result.get("veto_blocked") or not result["picks"]:
        lines.append("**오늘은 추천 없음**")
        lines.append("")
        if result.get("veto_blocked") and result.get("veto_reasons"):
            lines.append("무추천 사유:")
            for reason in result["veto_reasons"]:
                lines.append(f"- {reason}")
            lines.append("")
        elif not result.get("veto_blocked"):
            lines.append("기준 점수(70점) 이상 종목 없음")
            lines.append("")
    else:
        for pick in result["picks"]:
            lines.append(f"### 종목 {pick['rank']}: {pick['name']} ({pick['code']}) - {pick['score']}점")
            lines.append("")
            lines.append(f"- NXT가: {pick['current_price']:,.0f}원 (NXT 등락률 {pick['nxt_change_pct']:+.2f}%)")
            lines.append(f"- NXT 거래대금: {pick['nxt_trade_value_yuk']:.0f}억")
            lines.append(f"- 당일 KRX 등락률: {pick['daily_return']:+.2f}%")
            lines.append("")
            lines.append("**매수 근거:**")
            for detail in pick["details"]:
                lines.append(f"- {detail}")
            lines.append("")
            er = pick["exit_rules"]
            lines.append("**매매 시나리오:**")
            lines.append(f"- 진입 타겟가: {er['entry_target']:,}원")
            lines.append(f"- 추격 금지가: {er['no_chase_price']:,}원")
            lines.append(f"- 1차 익절: {er['take_profit_1']:,}원 / 2차 익절: {er['take_profit_2']:,}원")
            lines.append(f"- 손절: 타이트 {er['stop_loss_tight']:,}원 / 마지노선 {er['stop_loss_max']:,}원")
            lines.append(f"- 09:00 시나리오: {er['scenario_0900']}")
            lines.append(f"- 09:10 시나리오: {er['scenario_0910']}")
            lines.append(f"- 10:00 시간컷: {er['scenario_1000']}")
            lines.append("")

    lines.append("## 3. 주의사항")
    lines.append("")
    lines.append("### 익일 대응 체크리스트")
    for item in [
        "미국 본장 개장 후 선물 방향 재확인",
        "한국 연동 섹터(반도체, AI, 방산 등) 흐름 확인",
        "익일 NXT 프리마켓 방향 확인",
        "시가 단일가 확인 후 최종 매도 여부 결정",
    ]:
        lines.append(f"- [ ] {item}")
    lines.append("")
    lines.append("### 손절 원칙")
    lines.append("1. -4% 손절: 매수가 대비 -4% 도달 시 즉시 시장가 매도")
    lines.append("2. 10:00 시간컷: 슈팅 미출현 시 전량 정리")
    lines.append("3. 신규 악재 시 칼손절: 시초가 시장가 즉시 매도")
    lines.append("")
    lines.append("### 면책")
    lines.append(
        "본 리포트는 데이터 기반 분석 결과이며, 투자를 권유하는 것이 아닙니다. "
        "모든 투자의 최종 판단과 책임은 투자자 본인에게 있습니다."
    )
    return "\n".join(lines)


def save_nxt_markdown(result: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{result['date'].replace('-', '')}_nxt.md"
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_nxt_report(result))
    return path


def notify(result: dict) -> None:
    print_to_terminal(result)
    save_json(result)
    if result.get("session") == "nxt":
        save_nxt_markdown(result)
    send_telegram(result)
