# RealProvider — 한국투자증권 KIS Developers API 연동 (1단계) — 설계 문서

## 배경 및 목적

`leader_watch/providers/real.py`는 09:00~10:30 오전 주도주 실시간 감시 시스템(`docs/superpowers/specs/2026-08-11-morning-leader-watch-design.md`)의 실 데이터 소스 스텁으로, 현재 `get_snapshot()` 호출 시 `NotImplementedError`만 던진다. 이번 작업은 이 스텁을 실제로 동작하는 `RealProvider`로 구현하여, `python main.py --provider real`이 한국투자증권(KIS) Developers Open API로부터 실시간 시세를 가져와 기존 `MarketDataProvider` 계약을 만족하도록 하는 것이다.

**절대 제약(기존 시스템과 동일)**: 이 시스템은 시장 데이터 분석과 Telegram/콘솔 알림만 수행한다. 주문 제출, 매수/매도, 계좌 잔고 변경 등 자동매매 관련 코드는 절대 작성하지 않는다. KIS API는 시세 조회와 주문 실행을 모두 지원하지만, 이 구현은 **읽기 전용(시세 조회) 엔드포인트만** 사용한다.

## 범위 (1단계)

다음 6가지만 이번 작업 범위에 포함한다:

1. 인증 + Rate limit 관리 (OAuth 토큰 발급/갱신, 초당 호출 제한 준수)
2. 감시 대상 유니버스 선정 (거래대금 상위 N종목 순위 조회)
3. 업종 순위 조회 (테마 대용 — 아래 "테마 대체" 절 참고)
4. 종목별 현재가/체결강도/OHLC 조회 (배치 조회로 rate limit 절약)
5. 1분봉 캐싱 (분 경계마다만 갱신, 5분봉은 1분봉 5개를 합쳐 직접 계산)
6. 제외 대상 플래그 소싱 (거래정지/관리종목/투자위험 — 가능한 범위에서, 실패 시 안전한 기본값)

**범위 밖(추후 별도 작업으로 진행)**:
- 20일 동시간대 평균 거래대금/거래량 (`avg_trading_value_same_time_20d`/`avg_volume_same_time_20d`) — `StockSnapshot`에서 `Optional`이라 없어도 시스템은 정상 동작하며, 해당 점수 가산 로직만 건너뛴다.
- 당일 뉴스/공시 감지 (`news_today`/`news_continuing`) — KIS API 범위 밖. 1단계에서는 항상 `False`로 설정 (뉴스 점수 축이 0점 처리되며, 다른 조건들로 흐름이 이어짐).

이 두 항목이 없어도 시스템이 죽지 않고 "점수가 낮게 나오는" 형태로 우아하게 저하되도록 이미 기존 `scoring.py`/`state_machine.py`가 설계되어 있음을 확인했다.

## 테마 대체: 업종(섹터) 순위 사용

기존 `state_machine.py`(이미 구현·리뷰 완료된 코드, 이번 작업에서 수정하지 않음)는 `theme_rank is None`일 때 조기 후보 등록·09:30 확정·약화/재회복 판정을 전부 하드 차단한다. KIS Open API는 종목별 "테마"(반도체/2차전지 같은 개념)와 테마별 거래대금 순위를 제공하는 엔드포인트가 없으므로, 이를 우회하기 위해:

- `StockSnapshot.theme` = 종목의 업종(섹터)명
- `StockSnapshot.theme_trading_value_rank` = 해당 업종 내 등락률/거래대금 순위

로 채워서 기존 상태 머신 로직을 그대로 통과시킨다. 완전히 동일한 개념은 아니지만("테마"는 업종보다 세분화된 경우가 많음), 동반 상승 신호로서 유사하게 작동한다는 전제다. 이후 진짜 테마 데이터 소스가 생기면 `real.py`의 이 매핑 부분만 교체하면 된다.

## 아키텍처

```
leader_watch/providers/
├── real.py                    # RealProvider(MarketDataProvider) — 얇은 오케스트레이터
└── kis/
    ├── __init__.py
    ├── auth.py                # OAuth 토큰 발급/캐싱/자동 갱신 (~24시간 유효)
    ├── config.py               # KIS 자격증명 + 동작 파라미터 (env 기반, load_kis_config())
    ├── client.py               # rate-limited HTTP 래퍼 + 개별 엔드포인트 호출 메서드
    │                           #   (거래대금순위조회, 업종순위조회, 배치시세조회, 분봉조회)
    └── mapping.py              # 순수 함수: KIS raw JSON dict → StockSnapshot/MinuteBar
```

**분리 이유:**
- `mapping.py`는 순수 함수로 분리하여 실제 HTTP 없이 "이런 KIS 응답이 오면 이런 StockSnapshot이 나와야 한다"를 유닛 테스트로 검증 가능 (`mock_scenarios.py` 테스트와 같은 패턴).
- `client.py`는 `requests`를 모킹해서 테스트 (기존 `leader_watch/notifiers/telegram.py` 테스트와 같은 패턴).
- `real.py`는 캐싱/차등 갱신 로직만 담당하며 `client`/`mapping`을 조합.

**자격증명**: 리포지토리 루트 `config.py`가 `TELEGRAM_BOT_TOKEN`을 갖는 것과 별개로, `KIS_APP_KEY`/`KIS_APP_SECRET`/`KIS_ENV`(real|paper)는 `.env`의 신규 항목으로 추가하고 `kis/config.py`에서 직접 읽는다 (`leader_watch.config.Config`는 전략 파라미터용이라 자격증명과 분리 유지).

## 데이터 흐름 & 캐싱 정책 (옵션 B: 캐싱/차등 갱신, 스레드 없음)

`RealProvider.get_snapshot(now)`가 매 틱(기본 `poll_interval_seconds`=2초) 호출될 때:

1. **토큰 확인**: 만료 임박 시(`kis/auth.py`) 자동 갱신, 아니면 캐시된 토큰 재사용.
2. **유니버스/순위 갱신** — 캐시가 `KIS_RANKING_REFRESH_SECONDS`(기본 20초)보다 오래됐을 때만: 거래대금 상위 N종목(`KIS_UNIVERSE_SIZE`, 기본 100) 순위 조회.
3. **업종 순위 갱신** — 위와 같은 주기로: 업종별 순위 조회 → 종목의 업종코드와 매핑.
4. **가격/체결강도 배치 조회** — 매 틱마다 항상: 유니버스 종목을 30개씩(가정, 검증 필요) 묶어 배치 시세 조회.
5. **분봉 갱신** — 종목별로 "마지막으로 가져온 분"과 `now`의 분이 다를 때만 새 1분봉 1개를 가져와 캐시에 추가. 5분봉은 1분봉 5개를 합쳐 직접 계산 (별도 API 호출 없음).
6. **조립**: 위 데이터를 `mapping.py`로 `StockSnapshot` 리스트로 변환. `timestamp`는 KIS 응답의 실제 체결시각을 사용한다 (`datetime.now()` 사용 금지 — `engine.py`의 staleness 체크가 이 값에 의존).

`get_snapshot()`은 이 모든 단계를 동기적으로 수행한 뒤 리스트를 반환한다. 별도 백그라운드 스레드는 두지 않는다(옵션 B 채택, 옵션 C의 백그라운드 스레드+캐시 방식은 1단계 범위에서 과도한 복잡도로 판단해 배제).

**Rate limit**: `kis/client.py` 내부에 sleep 기반 스로틀러 — 기본 초당 15건(`KIS_MAX_REQUESTS_PER_SECOND`, 보수적 기본값, 실제 계정 등급에 맞춰 조정 가능). 개별 엔드포인트 호출은 각각 `leader_watch/engine.py`의 기존 `call_with_retry`로 감싸 실패 시 지수 백오프 재시도한다 (순환 참조 없음: `engine.py`는 `providers/real.py`를 import하지 않으므로 `providers/real.py` 또는 `kis/client.py`가 `from leader_watch.engine import call_with_retry`를 import하는 것은 단방향).

## 오류 처리 & 제외 플래그

- **인증 실패**: 토큰 발급이 `call_with_retry` 재시도 후에도 실패하면 예외를 그대로 전파한다. `engine.py`의 `run()`은 이미 예외를 잡아 로깅 후 다음 틱으로 넘어가도록 구현되어 있다(이전 fix wave에서 처리 완료, 이번 작업에서 재사용).
- **부분 실패 허용**: 배치 조회 중 일부 종목의 시세 조회가 실패해도 해당 종목만 이번 틱에서 제외하고 나머지는 정상 반환한다 (전체를 실패시키지 않음).
- **제외 플래그(거래정지/관리종목/투자위험)**: KIS 시세 응답의 상태 구분 코드 필드에서 매핑을 시도한다. 단, 정확한 필드명/코드값은 실제 계정으로 구현 단계에서 검증한다. 명확히 인식된 코드만 `True`로 표시하고, 불명확하거나 매핑 실패한 경우는 `False`로 두는 보수적(화이트리스트) 방식을 취한다 — 필터를 통과시켜 알림이 나가는 쪽보다, 확실한 경우만 걸러내는 쪽으로 설계한다.
- **ETF/우선주**: KIS 필드가 불확실해도 기존 `leader_watch/filters.py`의 종목명 기반 휴리스틱이 이미 폴백으로 동작하므로 크게 문제 없다 (이번 작업에서 `filters.py`는 수정하지 않음).

## 구현 중 반드시 검증해야 할 가정

다음 항목들은 실제 KIS 계정/문서 없이 이 설계 단계에서 정확히 단정할 수 없어 "가정"으로 기록하며, 구현 단계에서 실제 API 응답으로 검증한다:

- 정확한 TR_ID 및 엔드포인트 경로 (OAuth 토큰 발급, 거래대금순위조회, 업종순위조회, 배치시세조회, 분봉조회)
- 배치 시세 조회 1회당 최대 종목 수 (가정: 30개)
- 거래정지/관리종목/투자위험 여부를 나타내는 정확한 필드명과 코드값
- 체결강도 필드가 시세 응답에 직접 포함되는지 여부 (없으면 대체 계산 방법 필요)
- 실전투자 계정의 실제 초당 호출 제한

## 신규 환경변수

```
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ENV=real                          # real | paper
KIS_UNIVERSE_SIZE=100
KIS_RANKING_REFRESH_SECONDS=20
KIS_MAX_REQUESTS_PER_SECOND=15
```

`.env.example`에 추가하고 README의 설정값 표에도 반영한다. 기존 `leader_watch.config.Config`(전략 파라미터)는 변경하지 않는다.

## 테스트 계획

- `mapping.py`: 순수 함수 → KIS 응답 형태의 dict를 직접 넣어 `StockSnapshot`/`MinuteBar`로 정확히 변환되는지 검증 (네트워크 없음).
- `client.py`: `requests`를 모킹, rate limiter는 가짜 시계(fake clock)로 검증.
- `auth.py`: 토큰 발급/만료/자동 갱신 로직을 모킹된 응답으로 검증.
- `real.py`: `KisClient`를 가짜(fake/stub)로 주입하여 캐싱/차등 갱신 로직(예: "20초 이내 재호출 시 순위 API를 다시 안 부른다", "새 분이 시작될 때만 분봉을 갱신한다", "일부 종목 조회 실패 시 나머지는 정상 반환한다")을 검증 — 실제 KIS 계정 없이 전부 테스트 가능해야 한다.
- 기존 `MarketDataProvider` 인터페이스, `--provider {mock,real}` CLI 구조, `test_providers_real.py`(기존 2개 테스트: 인스턴스화 가능 + `get_snapshot` 미호출 시 예외 없음)는 변경하지 않되, `get_snapshot`을 실제로 호출하는 경로에 대한 신규 테스트를 추가한다.
- **실계좌 통합 테스트는 이 작업 범위에 포함하지 않는다** — 모든 자동 테스트는 모킹된 HTTP 응답으로 동작해야 하며, 실제 KIS 서버 호출은 사용자가 수동으로 `--provider real`을 실행해 검증한다.

## 기존 코드베이스와의 관계

- `leader_watch/providers/base.py`(`MarketDataProvider` 인터페이스), `leader_watch/engine.py`, `leader_watch/state_machine.py`, `leader_watch/scoring.py`, `leader_watch/filters.py`, `leader_watch/models.py`는 **수정하지 않는다**. `engine.py`의 `call_with_retry`만 재사용(import)한다.
- `leader_watch/providers/mock.py`/`mock_scenarios.py`(시뮬레이션용)는 그대로 유지되며 이번 작업과 무관하다.
- 리포지토리 루트의 `recommender.py`/`scorer.py`/`filters.py`/`notifier.py`/`scheduler.py`/`data_fetcher.py`는 이번 작업과 무관하며 수정하지 않는다.
