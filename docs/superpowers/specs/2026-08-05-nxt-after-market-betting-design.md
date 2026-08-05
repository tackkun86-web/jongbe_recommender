# NXT 애프터마켓 종가베팅 분석 — 설계 문서

날짜: 2026-08-05

## 목적

`nxt_jongga_betting_prompt.md`의 분석 방법론을 기존 `jongbe_recommender`의
"nxt" 세션(평일 19:50 KST)에 반영한다. NXT 애프터마켓 흐름과 (자동 수집 가능한
범위 내) 미국 선행 신호를 종합해 익절 확률이 높은 종목을 선별하고, 조건이
나쁜 날에는 명시적으로 "오늘은 추천 없음"을 출력한다.

`close` 세션(15:10, 기존 정규장 점수계)은 이번 작업 범위에서 완전히 제외하고
그대로 유지한다.

## 범위

포함:
- 외부 입력 파일(`input/nxt_signals.json`) 스키마 정의 및 로더 — 사용자가
  증권사 HTS/API로 조회한 NXT 종목 시세, 해외 선물/ADR/야간선물/금리, 이벤트
  플래그를 19:50 이전에 직접 기록
- 네이버 자동 스크래핑 확장(`overseas.py`): 다우/나스닥/S&P 지수, USD/KRW
  환율, WTI유가
- 무추천(veto) 판정 로직(`veto.py`): 8개 조건 중 판정 가능한 항목만 평가,
  2개 이상 해당 시 즉시 "오늘은 추천 없음"
- NXT 전용 점수화(`scorer.calculate_nxt_score`, `config.NXT_SCORE_WEIGHTS`):
  A~G 7개 항목, 100점 만점 + 리스크 감점(-20)
- NXT 전용 리포트 마크다운 생성(`notifier.format_nxt_report`) 및
  `output/YYYYMMDD_nxt.md` 저장
- 테마 연속성 계산을 위한 과거 output JSON 조회 로직 확장(연속 등장일수)
- 결측 데이터의 "데이터 부족" 표시 원칙 전면 적용(추정 금지)

제외 (이번 라운드):
- NXT 실시간 시세의 완전 자동화(유료 포털 계약 필요) — 수동 입력 파일로 대체
- `close` 세션 로직/점수계/출력 변경
- 입력 파일을 텔레그램 등으로 자동 수신하는 기능(수동 파일 갱신 전제)
- 종목별 섹터의 정교한 분류(공식 GICS 등) — 종목명 키워드 매칭으로 근사

## 데이터 계층

### 입력 파일: `input/nxt_signals.json`

```json
{
  "date": "2026-08-05",
  "updated_at": "19:45",
  "overseas": {
    "sp500_futures_change_pct": null,
    "nasdaq_futures_change_pct": null,
    "sox_change_pct": null,
    "kospi200_night_futures_change_pct": null,
    "us_10y_yield_change_bp": null,
    "hynix_adr_change_pct": null,
    "samsung_adr_change_pct": null
  },
  "events": {
    "major_event_tomorrow": false,
    "event_desc": "",
    "geopolitical_shock": false
  },
  "nxt_stocks": [
    {"code": "000660", "name": "SK하이닉스", "nxt_price": 0, "nxt_change_pct": 0,
     "nxt_trade_value_eok": 0, "nxt_volume": 0, "buy_sell_ratio": 1.0}
  ]
}
```

- `overseas.*`, `events.*` 필드는 값이 없으면 `null`/`false`로 두고, 로더는
  이를 그대로 통과시킨다(추정하지 않음).
- **신선도 검사**: `date`가 오늘(KST 기준)과 다르거나 파일이 없으면 전체를
  "데이터 부족" 취급 — `overseas`/`events`는 전부 `null`/`false`, `nxt_stocks`는
  빈 리스트로 간주.
- `nxt_stocks`가 비어 있으면 후보군이 없으므로 스코어링 없이 바로
  "오늘은 추천 없음 (NXT 데이터 부족)"을 반환한다.
- 신규 모듈 `input_loader.py`: `load_nxt_signals() -> dict` (경로:
  `input/nxt_signals.json`, 프로젝트 루트 기준 고정 경로).

### 자동 스크래핑 확장: `overseas.py`

- `get_overseas_indices() -> dict`: 네이버 `finance.naver.com/world/`에서
  다우(DJI)/나스닥(NAS)/S&P(SPI) 지수 등락률, `finance.naver.com/marketindex/`에서
  USD/KRW 환율 등락률과 WTI유가 등락률을 스크래핑. 개별 항목 파싱 실패 시
  해당 필드만 `None` 처리(전체 실패로 확산하지 않음).
- 입력 파일의 수동 필드(선물/ADR/야간선물/금리)와 병합해 하나의
  `overseas_signals` dict로 리포트/veto/점수화에 전달.

## 무추천(veto) 판정: `veto.py`

```python
def check_veto_conditions(overseas: dict, kospi_change_pct: float | None,
                           events: dict, nxt_trade_value_ratio: float | None
                           ) -> tuple[bool, list[str]]:
    ...
```

- 8개 조건을 각각 True/False/None(판정 불가)으로 평가하고, `None`은 카운트에서
  제외한다.
- True인 조건이 2개 이상이면 `(True, [사유 목록])` 반환 → 상위 호출부는 즉시
  "오늘은 추천 없음"으로 종료.
- NXT 총 거래대금 비율은 `output/` 폴더의 최근 5개 `*_nxt.json`에서
  거래대금 합계 평균을 구해 오늘 값과 비교(직전 데이터가 5개 미만이면 이 조건은
  판정 불가로 스킵).

## NXT 전용 점수화

`config.py`에 `NXT_SCORE_WEIGHTS` 추가, `scorer.py`에 `calculate_nxt_score()` 추가.

| 항목 | 배점 | 데이터 소스 |
|---|---|---|
| A. NXT 애프터마켓 흐름 | 25 | 입력파일 `nxt_change_pct`(구간별), 거래대금 미동반 상승 감점 |
| B. 정규장 수급 | 20 | 기존 `data_fetcher.get_investor_data` 재사용 |
| C. 테마 연속성 | 20 | 과거 `output/*_nxt.json` 연속 등장일수(1일=10, 2일+=20) |
| D. 해외 선행 신호 연동 | 15 | 종목명 키워드 → 프롬프트의 미국/한국 섹터 매핑표 → 해당 신호(SOX 등), 매칭 실패 시 S&P/나스닥 평균 |
| E. 기술적 자리 | 15 | 기존 `indicators.py`(전고점 근접, 이평 정배열) 재사용 |
| F. 시가갭 확률 | 5 | 기존 60일 OHLCV로 최근 5일 갭상승(시가>전일종가) 빈도 |
| G. 리스크 감점 | -20 (최대) | 야간선물/환율/미국선물 하락 각 -5, 당일 상승률 +10%↑ -5 |

- 70점 미만은 최종 후보에서 제외. 70점 이상이 0개면 "오늘은 추천 없음".
- 70점 이상 종목은 점수 순 정렬 후 최대 5종목.
- 1차 필터(거래대금, NXT거래대금 비중 3%↑, 관리종목/투자경고 등, 상한가 제외)는
  기존 `filters.py`를 재사용하되 NXT 세션 전용 파라미터를 추가한다.

## 매매 시나리오 (익절/손절)

`risk_manager.py`에 `generate_nxt_exit_rules()` 추가 — 프롬프트 Step4 템플릿의
시나리오(진입 타겟가, 추격 금지가, 1차/2차 익절, 손절가, 09:00/09:10/10:00 대응)를
그대로 생성. 기존 `generate_exit_rules()`(패턴 기반, close 세션용)는 변경하지 않음.

## 리포트 출력

- `notifier.py`에 `format_nxt_report(result) -> str` 추가: 프롬프트 Step4의
  마크다운 템플릿(시장 요약표, NXT 애프터마켓 요약, 코스피200 야간선물,
  추천 종목별 상세+시나리오, 익일 대응 체크리스트, 손절 원칙, 면책) 그대로 생성.
- `output/YYYYMMDD_nxt.md`로 저장(기존 JSON 저장은 유지).
- 텔레그램은 기존처럼 축약 요약(종목/점수/핵심 사유/익절·손절가) + "상세 리포트는
  output 폴더 확인" 문구로 유지 — 메시지 길이 제한 고려, 이번 라운드에서
  텔레그램 메시지 포맷 자체는 확장하지 않는다.
- 무추천 시: 터미널/JSON/마크다운/텔레그램 전부 "오늘은 추천 없음"과 해당 사유
  목록을 표시.

## 에러 처리 원칙

- 결측 필드는 어디서든 "데이터 부족"으로 표시하고 추정하지 않는다(점수 계산 시
  해당 항목 0점 처리 + breakdown에 "데이터 부족" 명시).
- 개별 종목 처리 중 예외 발생 시 해당 종목만 스킵(기존 `_evaluate_candidate`
  패턴 유지).
- `overseas.py`의 개별 스크래핑 실패는 해당 필드만 `None`, 전체 실행을
  막지 않는다.

## 세션 분기

`recommender.run_analysis(session=...)` 내부에서 `session == "nxt"`일 때만
새 경로(입력파일 로드 → veto 체크 → NXT 후보군 구성 → NXT 점수화 → NXT
리포트)를 타도록 분기. `session == "close"`는 기존 코드 경로를 그대로 호출한다.

## 테스트 방침

- `input_loader.py`: 정상 파일, 파일 없음, 날짜 불일치, 필드 누락 케이스
- `overseas.py`: HTML 파싱 성공/실패(mock) 케이스
- `veto.py`: 조건 0/1/2개 이상 해당 케이스, `None` 판정 제외 확인
- `scorer.calculate_nxt_score`: 항목별 배점 경계값, 리스크 감점 상한(-20) 확인
- `risk_manager.generate_nxt_exit_rules`: 시나리오 필드 존재 확인
- `notifier.format_nxt_report`: 추천 있음/없음 두 케이스 스냅샷성 검증(주요 섹션
  포함 여부)
- `recommender.run_analysis(session="nxt")`: veto 조기 종료 케이스, 정상 케이스
  통합 테스트(기존 mock 패턴 재사용)
