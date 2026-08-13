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
| KIS_APP_KEY | (없음, 필수) | KIS Developers API 앱키 (--provider real 사용 시 필수) |
| KIS_APP_SECRET | (없음, 필수) | KIS Developers API 앱시크릿 (--provider real 사용 시 필수) |
| KIS_ENV | real | KIS 계정 환경 (real=실전투자, paper=모의투자) |
| KIS_UNIVERSE_SIZE | 100 | 거래대금 상위 몇 종목까지 추적할지 |
| KIS_RANKING_REFRESH_SECONDS | 20 | 거래대금/업종 순위 갱신 주기(초) |
| KIS_MAX_REQUESTS_PER_SECOND | 15 | KIS API 초당 최대 호출 수 (보수적 기본값, 계정 등급에 맞춰 조정) |
| KIWOOM_BRIDGE_URL | http://127.0.0.1:8000 | kiwoom_bridge 프로세스 주소 (--provider kiwoom 사용 시) |
| KIWOOM_BRIDGE_TOKEN | (없음, 필수) | kiwoom_bridge와 공유하는 인증 토큰 (--provider kiwoom 사용 시 필수) |
| KIWOOM_UNIVERSE_SIZE | 100 | 거래대금 상위 몇 종목까지 추적할지 (kiwoom_bridge 경유) |
| KIWOOM_RANKING_REFRESH_SECONDS | 20 | 거래대금/업종 순위 갱신 주기(초) (kiwoom_bridge 경유) |

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

- `leader_watch/providers/real.py`의 `RealProvider`는 한국투자증권(KIS) Developers
  Open API로 구현되어 있습니다 (`.env`에 `KIS_APP_KEY`/`KIS_APP_SECRET` 설정 필요).
  단, 정확한 TR_ID/필드명 일부는 검증되지 않은 가정입니다 — 자세한 내용은
  `docs/superpowers/specs/2026-08-12-real-provider-kis-design.md`의
  "구현 중 반드시 검증해야 할 가정" 절 및 `leader_watch/providers/kis/mapping.py`의
  주석을 참고하세요. 20일 동시간대 평균 거래대금/거래량과 당일 뉴스/공시 감지는
  이번 범위에 포함되지 않았습니다(아래 항목 참고).
- `leader_watch/providers/kiwoom_provider.py`의 `KiwoomProvider`는 별도의
  32비트 `kiwoom_bridge` 프로세스(키움증권 OpenAPI+)를 통해 동작합니다.
  `kiwoom_bridge/README.md`에 따라 32비트 환경에서 `kiwoom_bridge/bridge.py`를
  먼저 실행한 뒤 `--provider kiwoom`을 사용하세요. `kiwoom_bridge/tr_client.py`의
  TR코드/필드명은 검증되지 않은 가정입니다 — 자세한 내용은
  `docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md`를 참고하세요.
  20일 동시간대 평균 거래대금/거래량과 당일 뉴스/공시 감지는 이번 범위에
  포함되지 않았습니다 (KIS 연동과 동일).
- `avg_trading_value_same_time_20d`/`avg_volume_same_time_20d`(20일 동시간대 평균
  거래대금/거래량)는 `RealProvider`에서 항상 `None`으로 채워집니다 — 점수 가산
  로직이 자동으로 건너뛰므로 시스템은 정상 동작하지만, 5배/3배 이상 거래대금 증가
  가산점은 받을 수 없습니다. 별도 작업으로 일봉 시세 조회 API 기반 계산 로직을
  추가해야 합니다.
- 10:30 이후 "새로운 주도 테마 변화"에 대한 별도 알림 로직은 이번 범위에 포함되지
  않았습니다 (기존 확정 종목 상태 유지만 수행).
- 당일 뉴스/공시 데이터는 MockProvider 시나리오에 하드코딩되어 있으며, 실제
  뉴스/공시 API 연동은 `RealProvider` 구현 시 함께 처리해야 합니다.
- 휴장일 캘린더는 수동 갱신 방식입니다.
