# 텔레그램 메시지에 추천 이유/익절·손절 구간 추가 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `notifier.send_telegram()`이 각 추천 종목에 대해 추천 이유 상위 3개와 익절/손절 구간 전체를 텔레그램 메시지에 포함하도록 만든다.

**Architecture:** `notifier.py` 내부에 헬퍼 함수 `_top_reasons(details, n=3)`를 추가해 `pick["details"]` 문자열 리스트에서 `(N점)` 패턴을 파싱하고 점수 내림차순 상위 n개를 반환한다. `send_telegram()`은 이 헬퍼와 `pick["exit_rules"]`를 사용해 메시지 문자열을 조립한다. 다른 모듈은 변경하지 않는다.

**Tech Stack:** Python 3, pytest, requests (기존과 동일, 신규 의존성 없음)

## Global Constraints

- 변경 범위는 `notifier.py`와 `tests/test_notifier.py`로 한정한다. (스펙: "변경 범위")
- `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 미설정 시 `False` 반환, 요청 예외 시 `False` 반환하는 기존 동작은 그대로 유지한다. (스펙: "에러 처리")
- `details`가 빈 리스트면 "이유:" 줄을 생략한다. (스펙: "에러 처리")
- 가격 값은 천 단위 콤마로 포맷한다 (예: `61,500`). (스펙: "메시지 포맷")
- 종목이 없는 경우 기존 헤더 + "추천 종목 없음" 메시지를 유지한다. (스펙: "메시지 포맷")

---

### Task 1: `_top_reasons` 헬퍼와 확장된 `send_telegram` 메시지 포맷

**Files:**
- Modify: `notifier.py` (새 함수 `_top_reasons` 추가, `send_telegram` 내부 메시지 조립 로직 수정)
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: 기존 `SAMPLE_RESULT` 픽스처 구조 (`pick["details"]`: `list[str]`, `pick["exit_rules"]`: `dict` with keys `take_profit_1`, `take_profit_2`, `stop_loss_tight`, `stop_loss_max`, `time_cut`, `strategy`)
- Produces:
  - `notifier._top_reasons(details: list[str], n: int = 3) -> list[str]` — `details`에서 점수 내림차순 상위 n개 문자열을 원래 형식(`"설명 (N점)"`) 그대로 반환. 점수를 파싱할 수 없는 항목은 0점으로 취급.
  - `notifier.send_telegram(result: dict) -> bool` — 기존 시그니처 유지, 반환값 의미도 동일.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_notifier.py`에 다음 테스트들을 추가한다 (기존 import/`SAMPLE_RESULT` 재사용):

```python
def test_top_reasons_sorts_by_score_desc():
    details = [
        "거래대금 500억 (5점)",
        "이평 정배열 (15점)",
        "외국인 순매수 (10점)",
        "수급 데이터 없음 (0점)",
    ]
    result = notifier._top_reasons(details, n=3)
    assert result == [
        "이평 정배열 (15점)",
        "외국인 순매수 (10점)",
        "거래대금 500억 (5점)",
    ]


def test_top_reasons_handles_unparseable_score():
    details = ["점수 없는 항목", "이평 정배열 (15점)"]
    result = notifier._top_reasons(details, n=3)
    assert result[0] == "이평 정배열 (15점)"
    assert "점수 없는 항목" in result


def test_top_reasons_empty_list_returns_empty():
    assert notifier._top_reasons([], n=3) == []


def test_send_telegram_includes_reasons_and_exit_rules(monkeypatch):
    monkeypatch.setattr(notifier, "TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setattr(notifier, "TELEGRAM_CHAT_ID", "dummy-chat")

    captured = {}

    class FakeResp:
        status_code = 200

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    sent = notifier.send_telegram(SAMPLE_RESULT)

    assert sent is True
    text = captured["json"]["text"]
    assert "SK하이닉스" in text
    assert "거래대금 8500억 (15점)" in text
    assert "1,614,010" in text
    assert "1,645,350" in text
    assert "1,535,660" in text
    assert "1,504,320" in text
    assert "시초가 갭상승 시 익절" in text
    assert "10:00" in text


def test_send_telegram_omits_reason_line_when_details_empty(monkeypatch):
    monkeypatch.setattr(notifier, "TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setattr(notifier, "TELEGRAM_CHAT_ID", "dummy-chat")

    result = json.loads(json.dumps(SAMPLE_RESULT))
    result["picks"][0]["details"] = []

    captured = {}

    class FakeResp:
        status_code = 200

    def fake_post(url, json, timeout):
        captured["json"] = json
        return FakeResp()

    monkeypatch.setattr(notifier.requests, "post", fake_post)

    notifier.send_telegram(result)
    text = captured["json"]["text"]
    assert "이유:" not in text
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/test_notifier.py -v`
Expected: `test_top_reasons_*`는 `AttributeError: module 'notifier' has no attribute '_top_reasons'`로 실패. `test_send_telegram_includes_reasons_and_exit_rules`, `test_send_telegram_omits_reason_line_when_details_empty`는 현재 메시지에 이유/익절/손절 텍스트가 없어 `assert` 실패.

- [ ] **Step 3: 구현**

`notifier.py`의 `send_telegram` 함수를 다음으로 교체하고, 바로 위에 `_top_reasons`, `re` import를 추가한다:

```python
import json
import os
import re
import sys
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

```python
def _top_reasons(details: list[str], n: int = 3) -> list[str]:
    def score_of(text: str) -> int:
        m = re.search(r"\((\d+)점\)", text)
        return int(m.group(1)) if m else 0

    return sorted(details, key=score_of, reverse=True)[:n]
```

```python
def send_telegram(result: dict) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    lines = [f"종가베팅 추천 ({result['date']})"]
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
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `pytest tests/test_notifier.py -v`
Expected: 전체 PASS (기존 3개 + 신규 5개, 총 8개 테스트)

- [ ] **Step 5: 전체 테스트 스위트 실행 (회귀 확인)**

Run: `pytest -v`
Expected: 전체 PASS (다른 모듈에 영향 없음 확인)

- [ ] **Step 6: 커밋**

```bash
git add notifier.py tests/test_notifier.py
git commit -m "feat: include recommendation reasons and exit rules in telegram message"
```
