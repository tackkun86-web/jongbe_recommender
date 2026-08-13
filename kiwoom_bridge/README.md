# kiwoom_bridge — 실행 및 수동 테스트 절차

**32비트 Python + pywin32 전용.** 메인 `leader_watch` 앱(64비트)과는 별도의
프로세스/환경에서 실행합니다.

## 실행

1. 같은 32비트 Python 환경에서:
   ```
   set KIWOOM_BRIDGE_PORT=8000
   set KIWOOM_BRIDGE_TOKEN=<메인 앱 .env 의 KIWOOM_BRIDGE_TOKEN 과 동일한 값>
   python bridge.py
   ```
   `bridge.py`를 실행하면 `KiwoomTrClient` 생성 시점에 키움 OpenAPI+ 로그인
   창이 자동으로 뜹니다. 창이 나타나면 ID/비밀번호/공동인증서로 평소처럼
   로그인하세요 — `OnEventConnect`로 로그인 성공이 확인된 뒤에 브릿지가
   HTTP 요청을 받기 시작합니다. 로그인 창이 뜨지 않거나 30초 안에 로그인이
   완료되지 않으면 브릿지가 오류를 내며 종료됩니다.
2. `[kiwoom_bridge] listening on http://127.0.0.1:8000` 로그가 뜨면 준비 완료입니다.

## 수동 테스트 절차

아래를 순서대로 실행하며 응답을 확인합니다 (`<token>`은 위에서 설정한 값으로 교체):

1. `curl -H "X-Bridge-Token: <token>" http://127.0.0.1:8000/health`
   → `{"status": "ok"}` 확인.
2. `curl -H "X-Bridge-Token: <token>" "http://127.0.0.1:8000/ranking/trading-value?count=5"`
   → 5개 종목의 JSON 배열, 각 항목에 `code`/`name`/`rank` 확인.
3. `curl -H "X-Bridge-Token: <token>" http://127.0.0.1:8000/ranking/sector`
   → 업종 배열, 각 항목에 `name`/`rank` 확인.
4. `curl -H "X-Bridge-Token: <token>" http://127.0.0.1:8000/quote/005930`
   (실제 보유/조회 가능한 종목코드로 교체) → `current_price`/`open`/`high`/`low`/
   `prev_close`/`volume`/`trading_value`/`sector`/`market`/`status` 필드 확인.
5. `curl -H "X-Bridge-Token: <token>" "http://127.0.0.1:8000/minute-bars/005930?reference_time=093000"`
   → 분봉 배열, 각 항목에 `time`/`open`/`high`/`low`/`close`/`volume` 확인.
6. 존재하지 않는 종목코드로 4번을 반복 → HTTP `503` + `{"error": "..."}` 확인
   (트레이스백으로 브릿지 프로세스가 죽지 않아야 함).
7. 잘못된 토큰으로 아무 요청이나 실행 → HTTP `401` 확인.

## 응답 필드가 다를 경우

3-5번에서 확인한 실제 응답 필드명이 `kiwoom_bridge/tr_client.py` 상단의
`ASSUMPTION` 주석이 달린 상수(`_F_*`, `_TR_*`, `_STATUS_MAP`)와 다르면, 그
상수들만 실제 값으로 수정하세요. `_request_tr`/`get_*` 메서드의 로직 자체는
바꿀 필요가 없습니다.
