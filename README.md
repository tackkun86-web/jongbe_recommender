# jongbe_recommender

## 오전 주도주 실시간 감시 시스템 (09:00–10:30 KST)

`main.py`는 장 시작 직후 09:00~10:30 사이에 실시간으로 급등 종목을 감시하여,
09:00 직후 급등만으로 즉시 확정하지 않고 09:30까지 거래대금·테마 순위·시가
유지력·분봉 흐름을 검증한 뒤 "오전 주도주"로 1차 확정하는 시스템입니다.

**이 시스템은 시장 데이터 분석과 Telegram/콘솔 알림만 수행합니다. 주문 제출,
매수/매도, 계좌 잔고 변경 등 자동매매 기능은 전혀 포함하지 않습니다.**

### 실행 방법

```bash
# 시뮬레이션 (실제 데이터 없이 MockProvider로 전체 흐름 테스트, 콘솔 출력)
python main.py --provider mock --notifier console

# 실제 데이터 사용 시 (RealProvider 구현 필요 — 아래 "TODO" 참고)
python main.py --provider real --notifier telegram
```

옵션:
- `--provider {mock,real}` — 데이터 소스 선택 (기본값: mock)
- `--notifier {console,telegram}` — 알림 채널 선택 (기본값: console)
- `--single-tick` — 폴링 루프 대신 1회만 실행하고 종료 (테스트/수동 확인용)

### 기존 일일 배치 시스템 (15:10 장마감 / 19:50 NXT)

기존 배치는 그대로 유지되며, 실행 파일만 이동했습니다:

```bash
python run_daily_scheduler.py
```

### 설정값

`.env` 파일에서 아래 값을 조정할 수 있습니다 (`.env.example` 참고):

| 변수 | 기본값 | 설명 |
|---|---|---|
| EARLY_CANDIDATE_TIME | 09:05 | 조기 후보 판단 시작 시각 |
| EARLY_CANDIDATE_END_TIME | 09:10 | 조기 후보 판단 종료 시각 |
| CONFIRMATION_TIME | 09:30 | 오전 주도주 1차 확정 시각 |
| MONITORING_END_TIME | 10:30 | 주도력 감시 종료 시각 |
| EARLY_MIN_SCORE | 70 | 조기 후보 최소 점수 |
| CONFIRMATION_MIN_SCORE | 75 | 확정 최소 점수 |
| EARLY_TRADING_VALUE_RANK | 50 | 조기 후보 거래대금 순위 기준 |
| CONFIRMATION_TRADING_VALUE_RANK | 30 | 확정 거래대금 순위 기준 |
| MAX_GAP_PERCENT | 8 | 갭 상승률 확정 제외 기준 |
| MAX_CONFIRMATION_DRAWDOWN_PERCENT | 3 | 확정 시 고점 대비 하락 허용치 |
| MAX_WEAKNESS_DRAWDOWN_PERCENT | 5 | 주도력 약화 판단 하락 기준 |
| MIN_THEME_FOLLOWERS | 2 | 테마 동반 상승 최소 종목 수 |
| ALERT_COOLDOWN_SECONDS | 300 | 동일 알림 재발송 쿨다운(초) |
| POLL_INTERVAL_SECONDS | 2 | 데이터 폴링 주기(초) |
| MARKET_TIMEZONE | Asia/Seoul | 시간 기준 타임존 |
| STALE_THRESHOLD_SECONDS | 30 | 데이터 지연 판단 기준(초, 스펙 외 추가 설정) |
| SCORE_RENOTIFY_DELTA | 10 | 점수 변화 시 예외 재알림 기준(스펙 외 추가 설정) |
| LEADER_WATCH_DB_PATH | leader_watch/data/alerts.db | 알림 이력 SQLite 경로(스펙 외 추가 설정) |

### 휴장일 캘린더 갱신

`leader_watch/engine.py`의 `KRX_HOLIDAYS_2026`는 매년 수동으로 갱신해야 합니다.
외부 API 연동이 없으므로, 매년 말 다음 해의 한국거래소 휴장일을 확인하여 이
세트를 갱신하세요.

### 테스트

```bash
pytest tests/leader_watch/ -v   # 신규 시스템만
pytest -v                        # 전체 (기존 배치 포함)
```

### TODO / 실 데이터 연동 필요 사항

- `leader_watch/providers/real.py`의 `RealProvider`는 아직 구현되지 않았습니다.
  실시간 1분봉/5분봉/체결강도/거래대금순위를 제공하는 증권사 API(예: 한국투자증권
  Open API 등)를 선정한 뒤, 해당 클래스를 구현해야 `--provider real`이 동작합니다.
- 10:30 이후 "새로운 주도 테마 변화"에 대한 별도 알림 로직은 이번 범위에 포함되지
  않았습니다 (기존 확정 종목 상태 유지만 수행).
- 당일 뉴스/공시 데이터는 MockProvider 시나리오에 하드코딩되어 있으며, 실제
  뉴스/공시 API 연동은 `RealProvider` 구현 시 함께 처리해야 합니다.
- 휴장일 캘린더는 수동 갱신 방식입니다.
