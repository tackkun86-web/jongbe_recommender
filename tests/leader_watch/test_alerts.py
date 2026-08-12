import datetime
from leader_watch.alerts import (
    format_confirmation,
    format_early_candidate,
    format_leader_change,
    format_recovery,
    format_rejection,
    format_weakness,
)
from leader_watch.models import ScoreBreakdown, StockSnapshot


def _snapshot(**overrides):
    base = dict(
        code="005930", name="테스트전자", market="KOSPI",
        timestamp=datetime.datetime(2026, 8, 11, 9, 10),
        current_price=10600, prev_close=10000, open_price=10200,
        high_price=10650, low_price=10150, cum_volume=2_000_000,
        cum_trading_value=25_000_000_000, market_trading_value_rank=5,
        execution_strength=140.0, theme="반도체", theme_trading_value_rank=1,
        news_today=True, news_continuing=False,
    )
    base.update(overrides)
    return StockSnapshot(**base)


def _breakdown():
    return ScoreBreakdown(trading_value=30, theme_leadership=20, price_strength=20, minute_flow=10, news=10, basis=["근거1", "근거2", "근거3"])


def test_early_candidate_alert_has_required_sections():
    title, body = format_early_candidate(_snapshot(), _breakdown(), market_rank=5, theme_rank=1)
    assert title == "[09:10 조기 주도주 후보]"
    assert "테스트전자(005930)" in body
    assert "90/100" in body
    assert "아직 오전 주도주 확정 전" in body
    assert "자동주문을 실행하지 않음" in body


def test_rejection_alert_has_reason():
    title, body = format_rejection(_snapshot(), score=45.0, reason="고점 대비 하락률 5% 초과")
    assert title == "[주도주 후보 탈락]"
    assert "고점 대비 하락률 5% 초과" in body
    assert "45/100" in body


def test_confirmation_alert_never_says_final_leader():
    title, body = format_confirmation(
        _snapshot(), _breakdown(),
        extras={
            "gap_tier": "정상",
            "rank_change_vs_0910": "5위 -> 3위 (개선)",
            "theme_follower_count": 3,
            "open_held": True, "first_high_held": True,
            "pullback_volume_down": True, "rebreak_high": True, "rank_maintained": True,
        },
    )
    assert title == "[09:30 오전 주도주 1차 확정]"
    assert "당일 최종 주도주" not in body
    assert "오전 주도주로 1차 확정" in body
    assert "오후 장에서 주도권이 변경될 수 있음" in body
    assert "갭 등급: 정상" in body


def test_confirmation_alert_renders_gap_tier_for_high_risk_gap():
    _, body = format_confirmation(_snapshot(), _breakdown(), extras={"gap_tier": "고위험"})
    assert "갭 등급: 고위험" in body


def test_confirmation_alert_falls_back_when_gap_tier_missing():
    _, body = format_confirmation(_snapshot(), _breakdown(), extras={})
    assert "갭 등급: 확인 불가" in body


def test_weakness_alert_shows_before_after():
    title, body = format_weakness(
        _snapshot(current_price=10100), prev_score=80.0, curr_score=68.0,
        prev_rank=5, curr_rank=35, prev_theme_rank=1, curr_theme_rank=4,
        drawdown_from_high_pct=5.3,
        reasons=["고점 대비 하락률 5% 초과", "거래대금 순위 30위 밖으로 하락"],
    )
    assert title == "[주도력 약화]"
    assert "80/100 -> 68/100" in body
    assert "5위 -> 35위" in body
    assert "5.30%" in body
    assert "다른 테마 또는 종목으로 주도권 이동 가능" in body


def test_recovery_alert_present():
    title, body = format_recovery(_snapshot(), score=78.0)
    assert title == "[주도력 재회복]"
    assert "78/100" in body


def test_leader_change_alert_has_basis():
    title, body = format_leader_change(
        theme="로봇", timestamp="2026-08-11 09:45:00",
        old_name="기존대장주", old_code="000001",
        new_name="신규도전자", new_code="000002",
        old_rank=6, new_rank=2, reasons=["거래대금 우위 3회 연속 유지", "상승률 우위", "시가/돌파선 유지"],
    )
    assert title == "[테마 대장주 변경 감지]"
    assert "2026-08-11 09:45:00" in body
    assert "기존대장주(000001)" in body
    assert "신규도전자(000002)" in body
    assert "6위" in body and "2위" in body
