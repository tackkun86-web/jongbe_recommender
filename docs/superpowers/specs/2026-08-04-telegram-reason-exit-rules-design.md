# 텔레그램 메시지에 추천 이유 및 익절/손절 구간 추가 (설계)

## 배경

`recommender.py`가 생성하는 각 추천(`pick`)에는 이미 추천 이유(`pick["details"]`,
scorer의 breakdown)와 익절/손절 구간(`pick["exit_rules"]`, risk_manager 산출)이
포함되어 있다. `notifier.print_to_terminal`은 이 정보를 모두 출력하지만,
`notifier.send_telegram`은 종목명/점수/패턴만 전송하고 있어 텔레그램으로는
추천 이유와 익절/손절 구간을 확인할 수 없다.

## 목표

`send_telegram`이 보내는 메시지에 종목별로:
1. 추천 이유 요약 (상위 3개)
2. 익절/손절 구간 전체 (1차/2차 익절, 타이트/마지노선 손절, 전략, 시간컷)

를 포함시킨다.

## 변경 범위

- `notifier.py`의 `send_telegram()` 함수만 수정한다.
- `recommender.py`, `scorer.py`, `risk_manager.py`는 필요한 데이터를 이미
  생성하고 있으므로 변경하지 않는다.

## 메시지 포맷

종목이 없는 경우 헤더 + "추천 종목 없음" 메시지를 유지한다.

종목이 있는 경우, 종목당 다음 형식으로 출력한다:

```
1. [005930] 삼성전자 - 87점 (눌림목)
   이유: 거래대금 500억 (20점), 이평 정배열 (15점), 외국인 순매수 (10점)
   익절: 1차 61,500 / 2차 63,000
   손절: 타이트 58,000 / 마지노선 56,500
   전략: 분할익절 후 홀딩 (시간컷 14:50)
```

- **추천 이유**: `pick["details"]`는 이미 `scorer.calculate_score`가 채점 순서대로
  붙인 문자열 리스트이며, 각 문자열 끝에 `(N점)` 형태로 점수가 포함되어 있다.
  이 점수를 파싱해 내림차순 정렬한 뒤 상위 3개만 콤마로 이어붙여 표시한다.
  점수를 파싱할 수 없는 항목(예: "수급 데이터 없음 (0점)")은 0점으로 취급한다.
- **익절/손절**: `pick["exit_rules"]`의 `take_profit_1`, `take_profit_2`,
  `stop_loss_tight`, `stop_loss_max`, `strategy`, `time_cut`을 모두 그대로 사용한다
  (가격은 천 단위 콤마 포맷).
- 날짜 헤더("종가베팅 추천 (YYYY-MM-DD)")와 기존 메시지 구조(종목 리스트를
  줄바꿈으로 연결)는 유지한다.

## 에러 처리

- 기존과 동일하게 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 미설정 시 `False` 반환,
  요청 중 예외 발생 시 `False` 반환하는 동작은 변경하지 않는다.
- `details` 리스트가 비어 있으면 "이유: " 줄 자체를 생략한다.

## 테스트

`tests/test_notifier.py`에 케이스 추가:
- `send_telegram` 호출 시 `requests.post`에 전달되는 메시지 텍스트에 이유 상위 3개
  문자열과 익절/손절 가격이 모두 포함되는지 확인 (requests는 mock 처리).
- `details`가 빈 리스트인 경우 "이유:" 줄이 생략되는지 확인.

## 범위 밖

- 터미널 출력(`print_to_terminal`) 포맷 변경 없음.
- 메시지 전송 방식(HTML/Markdown parse_mode 등) 변경 없음.
