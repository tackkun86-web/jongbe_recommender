"""Alert body formatters — exact wording required by the spec (§2, §4, §5)."""
from __future__ import annotations

from leader_watch.models import ScoreBreakdown, StockSnapshot

_DISCLAIMER = "본 알림은 투자 추천이 아닌 조건 충족 알림이며 자동주문을 실행하지 않음"


def _kst(snapshot: StockSnapshot) -> str:
    return snapshot.timestamp.strftime("%Y-%m-%d %H:%M:%S")


def format_early_candidate(snapshot: StockSnapshot, breakdown: ScoreBreakdown, market_rank: int, theme_rank: int) -> tuple[str, str]:
    title = "[09:10 조기 주도주 후보]"
    basis_lines = "\n".join(f"- {line}" for line in breakdown.basis[:3]) or "- 조건 충족 확인"
    body = f"""종목: {snapshot.name}({snapshot.code})
시장: {snapshot.market}
기준시각: {_kst(snapshot)}

현재가: {snapshot.current_price}
등락률: {snapshot.change_pct:.2f}%
시가 대비: {snapshot.vs_open_pct:.2f}%
시초가 갭: {snapshot.gap_from_prev_close_pct:.2f}%

누적 거래대금: {snapshot.cum_trading_value / 1e8:.1f}억 원
거래대금 순위: {market_rank}위
체결강도: {snapshot.execution_strength}
테마: {snapshot.theme}
테마 내 순위: {theme_rank}위
현재 점수: {breakdown.total:.0f}/100

판단 근거:
{basis_lines}

상태:
아직 오전 주도주 확정 전
09:30까지 거래대금과 시가 지지 여부 재확인 필요

주의:
{_DISCLAIMER}"""
    return title, body


def format_rejection(snapshot: StockSnapshot, score: float, reason: str) -> tuple[str, str]:
    title = "[주도주 후보 탈락]"
    body = f"""종목: {snapshot.name}({snapshot.code})
기준시각: {_kst(snapshot)}
현재 점수: {score:.0f}/100
탈락 사유: {reason}"""
    return title, body


def format_confirmation(snapshot: StockSnapshot, breakdown: ScoreBreakdown, extras: dict) -> tuple[str, str]:
    title = "[09:30 오전 주도주 1차 확정]"
    yn = lambda flag: "예" if flag else "아니오"  # noqa: E731
    basis_lines = "\n".join(f"- {line}" for line in breakdown.basis[:4]) or "- 조건 충족 확인"
    body = f"""종목: {snapshot.name}({snapshot.code})
시장: {snapshot.market}
기준시각: {_kst(snapshot)}

현재가: {snapshot.current_price}
등락률: {snapshot.change_pct:.2f}%
시가 대비: {snapshot.vs_open_pct:.2f}%
시초가 갭: {snapshot.gap_from_prev_close_pct:.2f}%
갭 등급: {extras.get("gap_tier", "확인 불가")}

누적 거래대금: {snapshot.cum_trading_value / 1e8:.1f}억 원
거래대금 순위: {snapshot.market_trading_value_rank}위
09:10 대비 순위: {extras.get("rank_change_vs_0910", "확인 불가")}
체결강도: {snapshot.execution_strength}

테마: {snapshot.theme}
테마 내 순위: {snapshot.theme_trading_value_rank}위
상승 중인 테마 종목 수: {extras.get("theme_follower_count", 0)}개
주도주 점수: {breakdown.total:.0f}/100

분봉 확인:
- 시가 지지: {yn(extras.get("open_held"))}
- 첫 고점 유지: {yn(extras.get("first_high_held"))}
- 눌림 시 거래량 감소: {yn(extras.get("pullback_volume_down"))}
- 직전 고점 재돌파: {yn(extras.get("rebreak_high"))}
- 거래대금 순위 유지: {yn(extras.get("rank_maintained"))}

판단 근거:
{basis_lines}

해석:
09:30 기준 오전 주도주로 1차 확정
오후 장에서 주도권이 변경될 수 있음

주의:
{_DISCLAIMER}"""
    return title, body


def format_weakness(
    snapshot: StockSnapshot, prev_score: float, curr_score: float,
    prev_rank: int, curr_rank: int, prev_theme_rank: int, curr_theme_rank: int,
    drawdown_from_high_pct: float, reasons: list[str],
) -> tuple[str, str]:
    title = "[주도력 약화]"
    reason_lines = "\n".join(f"- {line}" for line in reasons) or "- 확인 필요"
    body = f"""종목: {snapshot.name}({snapshot.code})
기준시각: {_kst(snapshot)}

현재가: {snapshot.current_price}
등락률: {snapshot.change_pct:.2f}%
고점 대비 하락률: {drawdown_from_high_pct:.2f}%

점수: {prev_score:.0f}/100 -> {curr_score:.0f}/100
거래대금 순위: {prev_rank}위 -> {curr_rank}위
테마 내 순위: {prev_theme_rank}위 -> {curr_theme_rank}위

약화 사유:
{reason_lines}

상태:
오전 주도력 약화
다른 테마 또는 종목으로 주도권 이동 가능"""
    return title, body


def format_recovery(snapshot: StockSnapshot, score: float) -> tuple[str, str]:
    title = "[주도력 재회복]"
    body = f"""종목: {snapshot.name}({snapshot.code})
기준시각: {_kst(snapshot)}
현재가: {snapshot.current_price}
현재 점수: {score:.0f}/100

상태:
주도력 약화 조건에서 회복하여 조건을 다시 충족함"""
    return title, body


def format_leader_change(
    theme: str, timestamp: str, old_name: str, old_code: str, new_name: str, new_code: str,
    old_rank: int, new_rank: int, reasons: list[str],
) -> tuple[str, str]:
    title = "[테마 대장주 변경 감지]"
    reason_lines = "\n".join(f"- {line}" for line in reasons) or "- 확인 필요"
    body = f"""테마: {theme}
기준시각: {timestamp}

기존 대장주: {old_name}({old_code})
새 대장주 후보: {new_name}({new_code})

기존 종목 거래대금 순위: {old_rank}위
신규 종목 거래대금 순위: {new_rank}위

변경 근거:
{reason_lines}"""
    return title, body
