# jongbe_recommender

## 종가베팅 종목 추천 배치 (15:10 장마감 / 19:50 NXT)

장마감 및 NXT 시간대에 종가베팅 후보 종목을 분석하여 Telegram으로 추천 메시지를
발송하는 배치 시스템입니다.

**이 시스템은 시장 데이터 분석과 Telegram 알림만 수행합니다. 주문 제출,
매수/매도, 계좌 잔고 변경 등 자동매매 기능은 전혀 포함하지 않습니다.**

### 실행 방법

```bash
python run_daily_scheduler.py
```

평일 15:10(장마감)과 19:50(NXT)에 자동으로 분석을 실행하고 결과를 Telegram으로
발송합니다.

수동으로 1회 실행하려면:

```bash
python run_daily.py close   # 장마감 세션
python run_daily.py nxt     # NXT 세션
```

### 설정값

`.env` 파일에 아래 값을 설정하세요 (`.env.example` 참고):

| 변수 | 설명 |
|---|---|
| TELEGRAM_BOT_TOKEN | Telegram 봇 토큰 |
| TELEGRAM_CHAT_ID | 메시지를 받을 채팅 ID |

그 외 필터/스코어링 기준은 `config.py`에 정의되어 있습니다.

### 테스트

```bash
pytest -v
```
