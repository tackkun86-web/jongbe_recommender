# 09:00~10:30 오전 주도주 실시간 감시 시스템 — 설계 문서

## 배경 및 목적

기존 `jongbe_recommender`는 장마감(15:10)/NXT(19:50) 일일 배치로 다음날 후보를 추천하는 시스템이다. 이번 작업은 그와 별개로, **장 시작 직후(09:00~10:30) 실시간으로 급등 종목을 감시하여, 09:00 직후 급등만으로 즉시 확정하지 않고 09:30까지 거래대금·테마 순위·시가 유지력·분봉 흐름을 검증한 뒤 "오전 주도주"로 1차 확정**하는 신규 서브시스템을 구축하는 것이다.

**절대 제약**: 이 시스템은 시장 데이터 분석과 Telegram/콘솔 알림만 수행한다. 주문 제출, 매수/매도, 계좌 잔고 변경 등 자동매매 관련 코드는 절대 작성하지 않는다. (기존 코드베이스에는 이런 코드가 전혀 없음을 확인했으며, 이 불변 조건을 신규 코드에서도 유지한다.)

## 기존 코드베이스와의 관계

- 기존 `recommender.py`/`scorer.py`/`filters.py`/`notifier.py`/`scheduler.py`(일일 배치)는 **수정하지 않고 그대로 유지**한다. 단, `main.py`가 현재 이 배치의 진입점이므로, 신규 시스템의 진입점으로 교체하고 기존 배치 실행은 `run_daily_scheduler.py`(신규 파일, `scheduler.start()` 호출만 이관)로 옮긴다.
- 기존 시스템에는 실시간 데이터 소스(증권사 API), provider 추상화, SQLite, 타임존 처리, 관리종목/거래정지/우선주 필터가 전혀 없다. 이번 작업에서 이 모두를 신규 패키지 내에 새로 구축한다. 기존 `data_fetcher.py`(네이버 스크래핑)는 실시간 지표(1분봉/체결강도/거래대금순위)를 제공하지 못하므로 재사용하지 않는다.

## 실 데이터 소스에 대한 결정

현재 실시간 데이터를 제공할 증권사 API 연동이 없다. 이번 작업 범위는 **`MockProvider`로 전체 흐름을 완성**하는 것이며, `RealProvider`는 인터페이스 계약만 구현하고 실제 API 호출부는 `NotImplementedError` + 명확한 TODO 주석으로 남긴다 (사용자가 추후 실제 증권사 API 연동 시 이 클래스만 구현하면 되도록).

## 아키텍처

```
leader_watch/
├── __init__.py
├── config.py            # .env 기반 설정 (전체 env var 목록은 "설정값" 절 참고)
├── models.py             # StockSnapshot, CandidateState, ScoreBreakdown, Phase 등 dataclass/enum
├── providers/
│   ├── base.py            # MarketDataProvider(ABC): get_snapshot(codes) -> list[StockSnapshot]
│   ├── mock.py            # MockProvider — 시나리오 기반 09:00~10:30 재생
│   ├── mock_scenarios.py  # 종목별 분단위 시나리오 데이터
│   └── real.py            # RealProvider — 인터페이스만, 호출부 NotImplementedError+TODO
├── notifiers/
│   ├── base.py            # AlertNotifier(ABC): send(alert: Alert) -> bool
│   ├── console.py         # 콘솔 출력 구현
│   └── telegram.py        # 기존 notifier.py의 텔레그램 전송 로직 이관/재사용
├── filters.py             # 거래정지/관리종목/투자위험/ETF/ETN/인버스/레버리지/스팩/우선주 제외
├── scoring.py             # 5개 카테고리 점수 계산 (합계 100점)
├── state_machine.py       # Phase별 후보 상태 전이 로직 (순수 함수 위주, 단위 테스트 용이)
├── store.py               # SQLite 알림 이력 / 후보 상태 영속화, 재시작 복구
├── alerts.py              # 알림 본문 포맷터 (조기후보/탈락/확정/약화/재회복/대장주변경)
└── engine.py              # 폴링 루프, KST 시간 판정, 휴장일 체크, 오케스트레이션

tests/leader_watch/         # 신규 테스트 (아래 "테스트 계획" 참고)
```

`main.py`는 `argparse`로 `--provider {mock,real}` (필수 또는 기본값 mock), `--notifier {console,telegram}` (기본값 console)을 받아 `leader_watch.engine.run(provider, notifier)`를 호출한다.

## 시간 처리

모든 시간 판단은 `datetime.now(ZoneInfo("Asia/Seoul"))` 기준으로 한다. 휴장일 판정은 별도 API 의존 없이 `config.py` 내 `KRX_HOLIDAYS` 하드코딩 세트(연 1회 수동 갱신, 갱신 방법을 README에 기록) + 주말(`weekday() >= 5`) 체크로 처리한다. 휴장일/주말에는 엔진이 즉시 종료(또는 대기 후 재확인)하며 어떤 알림도 발송하지 않는다.

## 상태 머신 (Phase)

```
INIT_COLLECT     09:00–09:05  데이터만 수집. 확정/후보 알림 없음.
EARLY_CANDIDATE  09:05–09:10  조건 충족 종목을 "조기 주도주 후보" 등록+알림 (최소 2회 연속 데이터 갱신에서 조건 유지해야 등록).
VALIDATION       09:10–09:30  후보 계속 추적. 탈락 조건 충족 시 1회성 탈락 알림 후 후보 제외.
CONFIRMATION     09:30 정각   전체 후보 재평가 → 필수조건+점수 75점 이상 종목만 "오전 주도주 1차 확정" 알림.
MONITORING       09:30–10:30  확정 종목의 주도력 약화/재회복 감시 + 테마 대장주 변경 감지.
POST_MONITORING  10:30 이후   이번 범위에서는 신규 알림 로직 없음(요구사항상 "별도 처리"이며 확장 여지로 TODO에 남김). 엔진은 정상 종료.
```

각 종목의 `CandidateState`는 `code, name, phase, status(active/rejected/confirmed/weakened/recovered), score_history, rank_history, theme_rank_history, last_alert_by_type`를 보유하고 매 폴링 틱마다 SQLite와 동기화된다. Phase 전이 로직은 순수 함수(`decide_early_candidate(...)`, `check_rejection(...)`, `evaluate_confirmation(...)`, `check_weakness(...)`, `check_recovery(...)`, `detect_leader_change(...)`)로 분리하여 스냅샷 히스토리를 입력받아 판정 결과+근거 리스트를 반환하도록 만들어, 테스트가 엔진 전체를 구동하지 않고 함수 단위로 검증 가능하게 한다.

## 점수 계산 (scoring.py)

요구사항 §3 그대로 5개 카테고리를 각각 함수로 분리:
- `score_trading_value(snapshot) -> (points, basis)` — 최대 30점
- `score_theme_leadership(snapshot, theme_snapshot) -> (points, basis)` — 최대 20점
- `score_price_strength(snapshot, history) -> (points, basis)` — 최대 25점
- `score_minute_flow(history) -> (points, basis)` — 최대 15점
- `score_news(snapshot) -> (points, basis)` — 최대 10점

`calculate_leader_score(...)`가 합산해 `ScoreBreakdown(total, categories, missing_data_categories, confidence)`를 반환한다. 결측 카테고리는 "확인 불가"로 표기하고 `confidence`를 낮춰 알림 본문에 신뢰도 저하를 표시한다. 모든 비율/순위 계산은 0-division 가드(`safe_ratio`)를 공용으로 사용한다.

## SQLite 스키마 (store.py)

```sql
CREATE TABLE IF NOT EXISTS candidates (
  code TEXT NOT NULL,
  date TEXT NOT NULL,           -- YYYY-MM-DD (KST)
  name TEXT,
  phase TEXT,
  status TEXT,
  score REAL,
  updated_at TEXT,
  PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL,
  date TEXT NOT NULL,
  alert_type TEXT NOT NULL,     -- early_candidate/rejected/confirmed/weakened/recovered/leader_change
  score REAL,
  sent_at TEXT NOT NULL         -- ISO8601 KST
);

CREATE INDEX IF NOT EXISTS idx_alerts_dedup ON alerts(code, alert_type, date);
```

재시작 시 오늘(KST) 날짜의 `candidates`/`alerts` 레코드를 로드해 메모리 상태를 복원한다. 쿨다운(`ALERT_COOLDOWN_SECONDS`) 및 "점수 10점 이상 변화 시 예외 재알림" 판단은 동일 `(code, alert_type, date)`의 마지막 `sent_at`/직전 발송 시점 점수를 조회해 처리한다.

## 에러 처리

- Provider 호출은 최대 3회 재시도, 지수 백오프(0.5s → 1s → 2s)로 감싼다.
- 스냅샷 `timestamp`가 `now`보다 `STALE_THRESHOLD_SECONDS`(기본 30초, config화) 이상 오래되면 해당 종목은 이번 틱에서 스킵하고 경고 로그만 남긴다(알림 발송 안 함).
- 필터 대상(거래정지/관리종목/투자위험/ETF/ETN/인버스/레버리지/스팩/우선주)은 `filters.py`에서 후보 진입 전에 원천 제외한다. 우선주는 종목명이 "우"/"우B" 등으로 끝나는 패턴으로 판정한다(기존 코드에 없던 것을 신규 추가).

## 설정값 (env var)

요구사항 §7에 나열된 전체 항목을 `leader_watch/config.py`가 로드한다. 시간 문자열은 `datetime.time`으로 파싱, 나머지는 float/int 캐스팅 + 기본값. 기존 `.env`의 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`는 그대로 재사용하고, `.env.example`에 신규 항목을 추가한다.

## 알림 포맷 (alerts.py)

요구사항 §2, §4, §5에 명시된 6종 알림(조기후보/탈락/확정/약화/재회복/대장주변경) 템플릿을 그대로 구현한다. 모든 알림에 데이터 기준시각(KST), 점수, 판단 근거를 반드시 포함한다. 09:30 확정 알림은 "당일 최종 주도주"라는 표현을 쓰지 않고 "오전 주도주 1차 확정"/"09:30 기준 주도주"/"오후 주도권 변경 가능" 문구를 사용한다.

## MockProvider 시나리오

`providers/mock_scenarios.py`에 최소 다음 8개 시나리오를 종목별 분단위 스냅샷 리스트로 하드코딩한다:
1. 정상 확정 후 10:30까지 유지
2. 조기 후보이나 09:30 이전 시가 이탈로 탈락
3. 갭 8% 초과로 확정 제외
4. 09:30 시점 거래대금 30위 밖으로 확정 실패
5. 09:30 확정 후 고점 대비 5% 초과 하락으로 약화 알림
6. 동일 테마 내 대장주 변경(3회 연속 우위)
7. 데이터 지연(오래된 timestamp)으로 알림 스킵
8. 휴장일(캘린더 등록일)로 전체 스킵

## 테스트 계획

요구사항 §9의 13개 항목을 각각 `tests/leader_watch/`에 매핑:
1~11 → `state_machine.py`의 순수 함수 단위 테스트 (스냅샷 히스토리를 직접 구성해 입력)
12 (네트워크 오류/지연) → `FlakyProvider` 테스트 더블로 재시도/백오프 및 stale 스킵 검증
13 (주말/휴장일) → `engine.py`의 날짜 가드 직접 테스트

추가로 `test_integration_mock_run.py`에서 MockProvider + ConsoleNotifier로 09:00~10:30 전체 시나리오를 구동하는 스모크 테스트를 둔다.

## 범위 밖 (TODO로 명시)

- `RealProvider`의 실제 증권사 API 연동 (사용할 API가 아직 미정)
- 10:30 이후 "새로운 주도 테마 변화" 별도 처리 로직의 구체 알림 설계
- 휴장일 캘린더의 자동 갱신(현재는 수동 하드코딩)
- 당일 뉴스/공시 데이터의 실제 소스 연동 (Mock에서는 시나리오에 하드코딩)
