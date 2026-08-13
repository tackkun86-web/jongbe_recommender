# KiwoomProvider — 키움증권 OpenAPI+ (모의투자) 연동 — 설계 문서

## 배경 및 목적

`leader_watch`는 이미 `--provider real`로 한국투자증권(KIS) Developers API를 통한 실시간 시세 연동을 갖추고 있다 (`docs/superpowers/specs/2026-08-12-real-provider-kis-design.md`). 사용자는 KIS 실전 API 키 발급 전에, 이미 로그인/COM 연결까지 준비된 **키움증권 구형 OpenAPI+ 모의투자** 환경으로 먼저 실시간 데이터 연동을 테스트하고자 한다.

이 문서는 새로운 `--provider kiwoom` 옵션을 추가하기 위한 설계다. KIS 연동은 그대로 유지되며, 이번 작업은 완전히 별도의 새 provider를 추가하는 것이다.

## 범위 (1단계)

- `python main.py --provider kiwoom` 이 키움증권 OpenAPI+ 모의투자 환경에서 실시간 KOSPI/KOSDAQ 시세를 가져와 동작한다.
- 읽기 전용 시세 조회만 다룬다 — 주문/잔고/체결 등 매매 관련 TR은 절대 사용하지 않는다.
- KIS 연동과 동일하게, 20일 동시간대 평균 거래대금/거래량 및 당일 뉴스/공시 감지는 이번 범위에서 제외한다 (`avg_trading_value_same_time_20d`/`avg_volume_same_time_20d`는 `None`, `news_today`/`news_continuing`은 항상 `False`).
- 브릿지 프로세스 자체(32비트, COM, 로그인 흐름)의 자동화 테스트는 이 환경에서 불가능하다 — 수동 테스트 절차로 검증한다 (아래 "브릿지 수동 테스트 프로토콜" 참고).

## 왜 별도 프로세스인가

키움 OpenAPI+는 32비트 전용 COM/OCX 컨트롤이며, TR 응답은 `OnReceiveTrData` 콜백을 통해 Windows 메시지 루프 안에서 비동기로 도착한다. 이는 다음과 정면으로 충돌한다:

- `leader_watch`는 64비트 Python으로 실행되며, 동기적 `get_snapshot(now)` pull 모델을 전제로 설계되어 있다 (`leader_watch/providers/base.py`).
- 엔진(`engine.py`), 스코어링(`scoring.py`), 상태머신(`state_machine.py`) 등은 수정 대상이 아니다 (KIS 연동과 동일한 제약).

따라서 COM/메시지펌프/32비트 제약을 별도의 소형 브릿지 프로세스로 완전히 격리하고, 메인 앱은 그 브릿지를 로컬 HTTP로 호출하는 얇은 클라이언트만 갖는다 — KIS의 `client.py`와 동일한 패턴이다.

## 아키텍처

```
┌─────────────────────────────┐        HTTP (localhost)        ┌──────────────────────────────┐
│ kiwoom_bridge (32-bit)       │ <────────────────────────────  │ leader_watch (64-bit, 기존)    │
│ - win32com Dispatch          │  GET /ranking/trading-value    │ providers/kiwoom_provider.py  │
│ - Windows 메시지 펌프          │  GET /ranking/sector           │   KiwoomProvider              │
│ - OnReceiveTrData 콜백        │  GET /quote/{code}             │ providers/kiwoom/             │
│ - stdlib http.server          │  GET /minute-bars/{code}       │   config.py / client.py /      │
│ - 로그인은 수동/기존 방식 유지    │ ─────────────────────────────> │   mapping.py                   │
└─────────────────────────────┘        JSON 응답                └──────────────────────────────┘
```

- **`kiwoom_bridge/bridge.py`** (신규, 32비트 Python 전용, 이 저장소에는 포함되지만 64비트 venv에서는 실행하지 않음): 로그인된 COM 객체를 소유하고, TR 요청을 동기적으로 감싸 HTTP로 노출한다. 표준 라이브러리 `http.server`만 사용 — 32비트 환경에 새 pip 패키지 설치가 필요 없다.
- **`leader_watch/providers/kiwoom/`** (신규 서브패키지, KIS의 `providers/kis/`와 동일한 역할 분담):
  - `config.py` — `KiwoomConfig`, `load_kiwoom_config()`, `KiwoomConfigError`
  - `client.py` — `KiwoomBridgeClient`, `KiwoomApiError` (브릿지에 대한 `requests` 기반 HTTP 클라이언트)
  - `mapping.py` — 순수 함수: 브릿지 JSON → `StockSnapshot`/`MinuteBar`
- **`leader_watch/providers/kiwoom_provider.py`** (신규, `providers/real.py`와 동일한 역할): `KiwoomProvider(MarketDataProvider)` — 캐싱/차등 갱신 정책은 `RealProvider`와 동일하게 재사용 (거래대금/업종 순위는 느린 주기로 캐시, 시세는 매 틱 새로 조회, 분봉은 새 분(minute)마다 1회만 조회, 최근 N개 봉만 스냅샷에 복사해서 담아 스코어링 쪽 별칭(aliasing) 문제를 피한다 — KIS 연동 최종 리뷰에서 발견된 패턴을 처음부터 반영).

## 브릿지 HTTP 프로토콜

로컬호스트 전용 바인딩(`127.0.0.1`), 공유 비밀 토큰으로 최소한의 방어:

- 모든 요청에 헤더 `X-Bridge-Token: <KIWOOM_BRIDGE_TOKEN>` 필요. 토큰 불일치 시 `401`.
- 브릿지는 `KIWOOM_BRIDGE_PORT`(기본값 지정)로 바인딩.

| 엔드포인트 | 매핑 TR (검증 필요, ASSUMPTION) | 응답 |
|---|---|---|
| `GET /ranking/trading-value?count=N` | 거래대금상위 조회 TR | `[{"code": str, "name": str, "rank": int}, ...]` |
| `GET /ranking/sector` | 업종별 순위 TR | `[{"name": str, "rank": int}, ...]` |
| `GET /quote/{code}` | 주식기본정보/현재가 TR | `{"current_price": num, "open": num, "high": num, "low": num, "prev_close": num, "volume": int, "trading_value": num, "sector": str, "status": str, ...}` |
| `GET /minute-bars/{code}?reference_time=HHMMSS` | 분봉차트 조회 TR (opt10080 계열) | `[{"time": "HHMMSS", "open": num, "high": num, "low": num, "close": num, "volume": int}, ...]` (최신 순) |

정상 응답은 `200` + JSON. TR 실패/타임아웃/미로그인 등은 `503` + `{"error": "..."}`. 각 TR 호출은 브릿지 내부에서 `threading.Event`로 `OnReceiveTrData` 콜백을 기다리며, 10초 타임아웃 시 `503`을 반환한다 (무한 대기 금지).

## 데이터 흐름 & 캐싱 정책

`RealProvider`(KIS)와 동일한 정책을 그대로 재사용한다:

- 거래대금순위/업종순위: `KIWOOM_RANKING_REFRESH_SECONDS` 주기로만 갱신, 그 사이는 캐시 사용. 신선도 판단은 틱의 `now` 기준(실제 wall-clock 아님 — 결정론적 테스트 가능).
- 시세(quote): 매 틱마다 추적 종목 전체에 대해 새로 조회.
- 분봉: 종목별로 새로운 분(minute)이 시작된 첫 틱에서만 조회, 그 전 완료된 분을 요청 (KIS 최종 리뷰에서 발견된 "진행 중인 분 조회" 버그를 처음부터 피한다).
- 스냅샷에 담기는 `minute_bars_1m`은 누적 캐시의 **복사본**이며 고정된 최근 N개 창(window)으로 제한한다 — 원본 리스트 객체를 그대로 넘기지 않는다 (KIS 최종 리뷰 Critical #1과 동일한 함정을 사전에 방지).

## 오류 처리

- 브릿지가 아예 떠 있지 않음(connection refused): `KiwoomProvider` 생성자 또는 최초 호출 시 명확한 한국어 에러 메시지와 함께 `KiwoomConfigError`류 예외로 표면화 — `main.py`가 KIS의 `KisConfigError`와 동일한 방식으로 잡아서 트레이스백 없이 종료 코드 1 반환.
- 개별 종목의 시세/분봉 조회 실패(`KiwoomApiError`, 매핑 중 `KeyError`/`ValueError`/`TypeError`): 해당 종목만 건너뛰고 나머지는 정상 반환 (부분 실패 허용 — KIS와 동일 원칙).
- 브릿지 쪽 `requests` 수준 네트워크 예외는 `KiwoomApiError`로 정규화한다 (KIS 최종 리뷰 Important #3에서 다룬 문제를 처음부터 반영).

## 구현 중 반드시 검증해야 할 가정

다음은 모두 실제 키움 OpenAPI+ 문서/테스트로 검증이 필요한 가정이며, 구현 시 이름이 있는 상수 + `ASSUMPTION` 주석으로 남긴다:

- 거래대금상위 TR의 정확한 TR코드와 요청/응답 필드명
- 업종별 순위 TR의 정확한 TR코드와 요청/응답 필드명 (KIS와 마찬가지로 "테마" 대체재로 사용)
- 주식기본정보/현재가 TR의 정확한 필드명 (현재가, 시가, 고가, 저가, 전일대비, 누적거래량, 누적거래대금, 종목상태)
- 분봉차트 TR의 정확한 TR코드, 응답에서 봉이 최신순인지 여부
- 종목상태코드(관리종목/투자위험/거래정지)를 나타내는 필드와 값 집합
- 시장 구분(KOSPI vs KOSDAQ)이 응답에 포함되는지, 포함 안 되면 KIS와 동일하게 임시로 단일 시장 라벨 사용

## 신규 환경변수

메인 앱 쪽 (64비트, `.env`):

```
KIWOOM_BRIDGE_URL=http://127.0.0.1:8000
KIWOOM_BRIDGE_TOKEN=
KIWOOM_UNIVERSE_SIZE=100
KIWOOM_RANKING_REFRESH_SECONDS=20
```

브릿지 쪽 (32비트 환경, 별도 실행 시 환경변수 또는 자체 설정):

```
KIWOOM_BRIDGE_PORT=8000
KIWOOM_BRIDGE_TOKEN=       # 메인 앱과 동일한 값이어야 함
```

## 테스트 계획

64비트 쪽(`leader_watch/providers/kiwoom/`, `providers/kiwoom_provider.py`)은 KIS와 동일한 방식으로 완전히 자동화 테스트한다 — `requests.get`을 `unittest.mock.patch`로 모킹, 실제 네트워크/브릿지 없이 전체 스위트 통과. 캐싱 창(window), 부분 실패 허용, 별칭 방지(리스트 복사) 등은 KIS 최종 리뷰에서 나온 회귀 테스트 패턴을 처음부터 동일하게 적용한다.

브릿지(32비트, COM 의존)는 이 환경에서 자동화 불가 — 아래 수동 테스트 절차로 검증한다.

## 브릿지 수동 테스트 프로토콜

사용자가 32비트 환경에서 직접 수행:

1. 키움 OpenAPI+ 로그인 완료 후 `kiwoom_bridge/bridge.py` 실행.
2. `curl -H "X-Bridge-Token: <token>" http://127.0.0.1:8000/ranking/trading-value?count=5` — JSON 배열, 5개 종목 확인.
3. 같은 방식으로 `/ranking/sector`, `/quote/{실제 종목코드}`, `/minute-bars/{종목코드}?reference_time=HHMMSS` 확인.
4. 존재하지 않는 종목코드로 `/quote/{code}` 호출 시 `503` + 에러 메시지 확인 (트레이스백으로 프로세스가 죽지 않아야 함).
5. 위 응답 필드명이 "구현 중 반드시 검증해야 할 가정" 절의 가정과 일치하는지 대조 — 다르면 `mapping.py`의 상수만 수정.

## 기존 코드베이스와의 관계

- `leader_watch/providers/real.py`(KIS)는 전혀 건드리지 않는다 — `--provider real`은 그대로 동작.
- `main.py`의 `--provider` 선택지에 `"kiwoom"`을 추가하고, `KiwoomConfigError`를 `KisConfigError`와 나란히 처리.
- `leader_watch/engine.py`, `state_machine.py`, `scoring.py`, `filters.py`, `models.py`, `providers/base.py`, `providers/mock.py`, `providers/mock_scenarios.py`, 저장소 루트의 `recommender.py`/`scorer.py`/`filters.py`/`notifier.py`/`scheduler.py`/`data_fetcher.py` — 모두 수정하지 않는다 (KIS 연동과 동일한 제약).
- `kiwoom_bridge/`는 저장소에 코드로는 포함하되(버전관리 대상, 리뷰 가능), 64비트 CI/테스트 스위트의 실행 대상이 아님을 문서화한다 (예: README에 "32비트 전용, 별도 실행" 명시).
