# 종가베팅 종목 추천 시스템 — 설계 문서

날짜: 2026-08-03

## 목적

매일 평일 15:10 KST(장 마감 20분 전)에 자동 실행되어, 네이버 증권 데이터만으로
당일 종가베팅 후보 5종목을 선정하고 종목별 익절/손절 기준을 제시하는 시스템.
API 키 불필요, 순수 웹 스크래핑 기반.

## 범위

포함:
- 하드 필터 → 기술적 지표 → 패턴 감지 → 점수화 → 상위 5종목 선정
- 종목별 익절/손절 규칙 생성 (패턴별 차등)
- 터미널 출력 + JSON 저장 + 텔레그램 알림 (봇 토큰/챗ID 환경변수 없으면 no-op)
- `schedule` 라이브러리 기반 상주 프로세스 스케줄링 (평일 15:10 KST)
- 코스피/코스닥 지수 수집 (네이버 증권)

제외 (이번 라운드):
- 슬랙 알림
- 백테스트 모듈 (`backtest.py`)
- 야간선물/미국장 실시간 수집 — 출력 스키마에 필드는 존재하되 값은
  `null` / "데이터 없음 (미구현)" 플레이스홀더로 고정

## 프로젝트 위치

`c:/Users/tackk/jongbe_recommender/` — 기존 `shorts_bot`과 무관한 독립 신규 프로젝트.

```
jongbe_recommender/
├── config.py
├── data_fetcher.py
├── filters.py
├── indicators.py
├── scorer.py
├── risk_manager.py
├── recommender.py
├── notifier.py
├── scheduler.py
├── main.py
├── requirements.txt
├── tests/
│   ├── test_indicators.py
│   ├── test_filters.py
│   └── test_scorer.py
├── output/           # 일별 JSON 결과 저장
└── logs/             # 실행 로그
```

## 데이터 흐름

1. `data_fetcher.get_top_stocks_by_trade_value(sosok, pages)` +
   `get_top_gainers(sosok, pages)` 를 KOSPI(0)/KOSDAQ(1) 각각에 대해 호출,
   상위 30 거래대금 + 상위 30 상승률 종목을 code 기준으로 합쳐 후보군 생성.
2. `filters.apply_hard_filters(candidate)` 로 다음을 즉시 제외:
   - ETF/ETN/스팩/리츠/인버스/레버리지 (종목명 키워드 매칭)
   - 관리종목/거래정지/정리매매 (네이버 페이지의 경고 문구로 판별, 불가 시 스킵 처리)
   - 시가총액 1,000억 미만
   - 당일 등락률 <3% 또는 >15% (상한가 포함 제외)
   - 당일 거래대금 500억 미만
3. 생존 종목에 대해 개별 상세 수집:
   - `get_stock_daily_data(code)` — 최근 60거래일 OHLCV
   - `get_investor_data(code)` — 최근 5거래일 외국인/기관 순매매
   - `get_stock_summary(code)` — 시가총액, 52주 고/저, PER 등
   - 이평 역배열(ma5<ma20) 또는 종가가 고가 대비 -3% 초과 하락한 종목은 이 단계에서 추가 제외.
4. `indicators.calculate_indicators(df)` 로 MA5/10/20/60, RSI14, MACD/Signal,
   거래량비율(당일/20일평균), 종가위치(고가 대비), 52주 신고가 근접도 계산.
5. `indicators.detect_pattern(df, indicators)` 로 4개 패턴 중 하나 판정
   (우선순위: 신고가 > 전고점돌파 > 눌림회복 > 과대낙폭반등 > 없음).
6. `scorer.calculate_score(candidate, indicators, pattern, investor_data, sector_rank)`
   로 A~F 항목 + 보조지표 가산 합산 (최대 105점).
7. 총점 50점 이상 종목만 남기고 점수 내림차순 정렬, 상위 5개 선택.
8. `risk_manager.generate_exit_rules(pattern, current_price)` 로 종목별
   1차/2차 익절가, 타이트/마지노선 손절가, 시간컷 문자열, 전략 설명 생성.
9. `notifier.notify(result)` 가 터미널 출력 + `output/YYYYMMDD.json` 저장 +
   (환경변수 설정 시) 텔레그램 메시지 전송을 수행.

## 섹터/테마 처리 (재료·테마 15점 항목)

네이버 증권에는 공식 "테마" API가 없으므로, 후보군 수집 시 확보한 거래대금 상위
종목 리스트를 기준으로 근사 처리:
- 당일 거래대금 상위 30위 안에서, 동일 산업(업종) 코드가 있으면 그룹핑하여
  "업종 내 거래대금 순위"를 계산 (네이버 `sise_market_sum` 업종 정보 또는
  종목 요약 페이지의 업종명 사용).
- 업종 내 거래대금 상위 3위 = "거래대금 상위 섹터 Top 3 소속" 8점.
- 업종 내 1~2위 & 거래대금 1,000억 이상 = "대장주/2등주" 5점.
- "테마 2일 이상 지속"은 전일 대비 동일 종목이 전일 거래대금 상위 리스트에도
  있었는지로 근사 판정 (전일 데이터는 당일 실행 시점에 캐시된 이전 실행
  JSON 출력 파일(`output/`)에서 조회; 없으면 0점 처리).

## 수급 데이터 (D. 25점)

- `get_investor_data`로 최근 5거래일 외국인/기관 순매매량(주식수, 부호만 사용)
  확보.
- 외국인 3일 연속 순매수는 최근 3거래일 모두 양수인지로 판정.
- 프로그램 순매수는 네이버에서 별도 페이지 크롤링이 번거로우므로 스펙대로
  "데이터 미제공 시 생략" — 0점 처리하고 총점 만점 캡은 25점 유지.

## 에러 처리

- 개별 종목 fetch 실패(네트워크/파싱 오류)는 해당 종목만 로그 남기고 후보군에서
  제외 — 전체 실행은 계속 진행.
- `sise_day` 파싱 실패 시 `frgn` 페이지의 종가/거래량 컬럼으로 최소 데이터 대체
  시도, 그마저 실패하면 스킵.
- 네이버 요청 간 0.1초 sleep, `User-Agent` 헤더 고정, `resp.encoding='euc-kr'`.
- 스케줄러 루프 내 `run_analysis()` 예외는 catch하여 로그 남기고 다음 스케줄까지
  프로세스 유지 (크래시로 상주 프로세스가 죽지 않도록).

## 알림 (텔레그램)

- 환경변수 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` 가 모두 설정된 경우에만
  `notifier.send_telegram()` 이 Bot API로 메시지 전송 (터미널 출력과 동일한
  요약 텍스트, HTML 파싱 모드).
- 둘 중 하나라도 없으면 조용히 스킵 (에러 아님).

## 스케줄링

- `scheduler.py` 가 `schedule` 라이브러리로 월~금 15:10 KST에 `recommender.run_analysis()`
  호출을 등록, `while True: schedule.run_pending(); time.sleep(30)` 루프.
- `main.py` 실행 시: 즉시 1회 `run_analysis()` 실행 후 결과 출력 → 이어서
  스케줄러 루프 진입 (상주 프로세스, PC 실행 중일 때만 동작 — 사용자 확인 완료).

## 테스트 전략

네트워크 호출 없이 고정 fixture DataFrame으로:
- `test_indicators.py`: MA/RSI/MACD 계산값 검증(알려진 입력→기대값), 4개
  패턴 각각 감지되는 synthetic OHLCV 케이스, 패턴 미해당 케이스.
- `test_filters.py`: 각 하드 필터 조건이 개별적으로 종목을 제외/통과시키는지.
- `test_scorer.py`: 각 항목(A~F)별 점수 계산 및 총점/캡(25점, 105점) 검증.

## 의존성

`requests`, `beautifulsoup4`, `lxml`, `pandas`, `schedule`, `python-dotenv`
(텔레그램 토큰 등 `.env` 로드용).
