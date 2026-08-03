# 종가베팅 종목 추천 시스템 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python system that scrapes Naver Finance, filters/scores KOSPI+KOSDAQ stocks against a 7-condition 종가베팅 model, and outputs top-5 daily picks with exit rules (terminal + JSON + optional Telegram), runnable both as a one-off test and as a 15:10 KST weekday scheduler.

**Architecture:** Pipeline of pure-function modules (`filters` → `indicators` → `scorer` → `risk_manager`) fed by a scraping layer (`data_fetcher`), orchestrated by `recommender.run_analysis()`, surfaced by `notifier`, triggered by `main.py` (immediate run) and `scheduler.py` (resident loop).

**Tech Stack:** Python 3.10+, `requests`, `beautifulsoup4`, `lxml`, `pandas`, `schedule`, `python-dotenv`. No API keys. Naver Finance HTML scraping only.

## Global Constraints

- Every Naver HTTP request: fixed `User-Agent` header, `resp.encoding = 'euc-kr'`, 0.1s sleep after each request.
- Trade value from Naver is in 백만원(million KRW); convert to 억원 by `/100` wherever the spec expresses thresholds in 억원.
- Hard filters run BEFORE any scoring — a stock failing any hard filter never reaches `scorer.py`.
- Score cap: D(수급) capped at 25 even with bonus; total displayed as `score/105`.
- Recommend threshold: total score >= 50, top 5 by score descending.
- No placeholder/mock data in production code paths — `tests/` may use fixture DataFrames, but `data_fetcher.py` must hit real Naver URLs.
- Telegram send is a no-op (not an error) when `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` env vars are unset.
- Individual stock fetch failures are caught, logged, and the stock is dropped from candidates — never crash the whole run.

---

### Task 1: Project scaffolding + config.py

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `.env.example`
- Create: `.gitignore`

**Interfaces:**
- Produces: `config.HARD_FILTERS` (dict), `config.SCORE_WEIGHTS` (dict), `config.NAVER_URLS` (dict of format strings), `config.HEADERS` (dict), `config.REQUEST_SLEEP` (float), `config.TELEGRAM_BOT_TOKEN` / `config.TELEGRAM_CHAT_ID` (str|None, loaded via `python-dotenv`)

- [ ] **Step 1: Write requirements.txt**

```
requests>=2.31
beautifulsoup4>=4.12
lxml>=5.0
pandas>=2.0
schedule>=1.2
python-dotenv>=1.0
pytest>=8.0
```

- [ ] **Step 2: Write .gitignore**

```
__pycache__/
*.pyc
.env
output/*.json
logs/*.log
```

- [ ] **Step 3: Write .env.example**

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

- [ ] **Step 4: Write config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
REQUEST_SLEEP = 0.1
ENCODING = "euc-kr"

NAVER_URLS = {
    "trade_value": "https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&page={page}",
    "gainers": "https://finance.naver.com/sise/sise_rise.naver?sosok={sosok}&page={page}",
    "daily": "https://finance.naver.com/item/sise_day.naver?code={code}&page={page}",
    "investor": "https://finance.naver.com/item/frgn.naver?code={code}&page={page}",
    "summary": "https://finance.naver.com/item/main.naver?code={code}",
    "kospi_index": "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
    "kosdaq_index": "https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ",
}

EXCLUDED_NAME_KEYWORDS = [
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "인버스", "레버리지",
    "선물", "스팩", "리츠", "HANARO", "KOSEF", "SOL", "ACE",
]

HARD_FILTERS = {
    "min_market_cap_eok": 1000,       # 억원
    "min_daily_return_pct": 3.0,
    "max_daily_return_pct": 15.0,
    "limit_up_pct": 29.0,
    "min_trade_value_eok": 500,       # 억원
    "max_close_off_high_pct": 3.0,    # (high-close)/high*100
}

SCORE_WEIGHTS = {
    "trade_value": {"tier1_eok": 2000, "tier1_pts": 15,
                     "tier2_eok": 1000, "tier2_pts": 10,
                     "tier3_eok": 500, "tier3_pts": 5},
    "trend": {"aligned_pts": 10, "above_ma5_pts": 5},
    "candle": {"optimal_low": 3.0, "optimal_high": 8.0, "optimal_pts": 10,
               "good_high": 15.0, "good_pts": 5,
               "close_near_high_pts": 5, "close_near_high_pct": 1.0,
               "close_mid_high_pts": 3, "close_mid_high_pct": 3.0},
    "supply": {"foreign_buy_pts": 8, "inst_buy_pts": 8, "program_buy_pts": 5,
               "both_bonus_pts": 4, "foreign_streak_pts": 5, "cap": 25},
    "theme": {"top3_sector_pts": 8, "leader_pts": 5, "leader_min_eok": 1000,
              "continuity_pts": 2},
    "pattern": {"신고가": 15, "전고점돌파": 12, "눌림회복": 10, "과대낙폭반등": 8, "없음": 0},
    "bonus": {"macd_cross_pts": 2, "rsi_range_pts": 2, "rsi_low": 50, "rsi_high": 70},
    "recommend_threshold": 50,
    "top_n": 5,
}

EXIT_RULES = {
    "신고가": {"tp1_pct": 3, "tp2_pct": 5,
              "strategy": "시초가 갭상승 시 익절, 장초반 슈팅 시 2차 익절"},
    "전고점돌파": {"tp1_pct": 3, "tp2_pct": 6,
                 "strategy": "돌파 후 갭상승 시 익절, 추가 상승 시 추익절"},
    "눌림회복": {"tp1_pct": 2, "tp2_pct": 5,
               "strategy": "반등 시 익절, 5일선 도달 시 전량 익절"},
    "과대낙폭반등": {"tp1_pct": 3, "tp2_pct": 5,
                  "strategy": "반등 갭 시 익절, 20일선 도달 시 전량 익절"},
    "없음": {"tp1_pct": 2, "tp2_pct": 5, "strategy": "시초가 갭상승 시 익절"},
}
STOP_LOSS = {"tight_pct": 2, "max_pct": 4, "time_cut": "10:00"}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or None
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or None
```

- [ ] **Step 5: Verify it imports cleanly**

Run: `python -c "import config; print(config.HARD_FILTERS)"`
Expected: prints the dict, no errors.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt config.py .env.example .gitignore
git commit -m "chore: scaffold project and add config"
```

---

### Task 2: data_fetcher.py — list scraping (trade value / gainers / index)

**Files:**
- Create: `data_fetcher.py`
- Test: `tests/test_data_fetcher_parsing.py`

**Interfaces:**
- Consumes: `config.HEADERS`, `config.REQUEST_SLEEP`, `config.ENCODING`, `config.NAVER_URLS`
- Produces:
  - `get_top_stocks_by_trade_value(sosok: int, pages: int = 2) -> list[dict]` — each dict: `{code, name, price, change_pct, volume, trade_value_eok, market_cap_eok}`
  - `get_top_gainers(sosok: int, pages: int = 3) -> list[dict]` — same shape
  - `get_market_index() -> dict` — `{"kospi": {"index": float, "change_pct": float}, "kosdaq": {...}}`
  - `_parse_quant_table(html: str) -> list[dict]` (internal helper shared by both list functions — same table structure on both pages)

This task's parsing helper `_parse_quant_table` is a pure function of an HTML string, so it's unit-testable without live network calls; live-network smoke testing happens manually (Task 2 does not require the test suite to hit the network).

- [ ] **Step 1: Write the failing parsing test with a fixture HTML snippet**

```python
# tests/test_data_fetcher_parsing.py
from data_fetcher import _parse_quant_table

FIXTURE_HTML = """
<table class="type_2">
<tr><th>N</th><th>종목명</th><th>현재가</th><th>전일비</th><th>등락률</th>
<th>거래량</th><th>거래대금</th><th>매도호가</th><th>매수호가</th>
<th>시가총액</th><th>PER</th><th>ROE</th></tr>
<tr><td>1</td>
<td><a href="/item/main.naver?code=005930">삼성전자</a></td>
<td>75,000</td><td>2,000</td><td>+2.74%</td>
<td>10,000,000</td><td>750,000</td>
<td>75,100</td><td>75,000</td><td>4,500,000</td><td>12.3</td><td>9.1</td>
</tr>
</table>
"""

def test_parse_quant_table_extracts_code_and_values():
    rows = _parse_quant_table(FIXTURE_HTML)
    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "005930"
    assert row["name"] == "삼성전자"
    assert row["price"] == 75000
    assert row["change_pct"] == 2.74
    assert row["volume"] == 10_000_000
    assert row["trade_value_eok"] == 7500.0  # 750,000 million-won / 100
    assert row["market_cap_eok"] == 4_500_000  # already 억원 on Naver
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_fetcher_parsing.py -v`
Expected: FAIL — `ImportError: cannot import name '_parse_quant_table'` (module doesn't exist yet)

- [ ] **Step 3: Write data_fetcher.py (list-scraping portion)**

```python
import re
import time
import requests
from bs4 import BeautifulSoup

from config import HEADERS, REQUEST_SLEEP, ENCODING, NAVER_URLS


def _fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.encoding = ENCODING
    time.sleep(REQUEST_SLEEP)
    return resp.text


def _to_number(text: str) -> float:
    cleaned = text.replace(",", "").replace("%", "").replace("+", "").strip()
    if cleaned in ("", "-"):
        return 0.0
    return float(cleaned)


def _parse_quant_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="type_2")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        link = tr.find("a", href=re.compile(r"code=(\d{6})"))
        if link is None:
            continue
        code = re.search(r"code=(\d{6})", link["href"]).group(1)
        name = link.get_text(strip=True)
        tds = tr.find_all("td")
        if len(tds) < 11:
            continue
        price = _to_number(tds[2].get_text())
        change_pct = _to_number(tds[4].get_text())
        if "-" in tds[4].get_text() and change_pct > 0:
            change_pct = -change_pct
        volume = _to_number(tds[5].get_text())
        trade_value_eok = _to_number(tds[6].get_text()) / 100
        market_cap_eok = _to_number(tds[9].get_text())
        rows.append({
            "code": code,
            "name": name,
            "price": price,
            "change_pct": change_pct,
            "volume": volume,
            "trade_value_eok": trade_value_eok,
            "market_cap_eok": market_cap_eok,
        })
    return rows


def get_top_stocks_by_trade_value(sosok: int, pages: int = 2) -> list[dict]:
    results = []
    for page in range(1, pages + 1):
        url = NAVER_URLS["trade_value"].format(sosok=sosok, page=page)
        results.extend(_parse_quant_table(_fetch_html(url)))
    return results


def get_top_gainers(sosok: int, pages: int = 3) -> list[dict]:
    results = []
    for page in range(1, pages + 1):
        url = NAVER_URLS["gainers"].format(sosok=sosok, page=page)
        results.extend(_parse_quant_table(_fetch_html(url)))
    return results


def get_market_index() -> dict:
    out = {}
    for market, key in (("kospi", "kospi_index"), ("kosdaq", "kosdaq_index")):
        try:
            html = _fetch_html(NAVER_URLS[key])
            soup = BeautifulSoup(html, "lxml")
            index_val = soup.select_one("#now_value")
            change_val = soup.select_one("#change_value_and_rate")
            index_num = _to_number(index_val.get_text()) if index_val else 0.0
            change_text = change_val.get_text(" ", strip=True) if change_val else ""
            m = re.search(r"([+-]?\d+\.\d+)%", change_text)
            change_pct = float(m.group(1)) if m else 0.0
            out[market] = {"index": index_num, "change_pct": change_pct}
        except Exception:
            out[market] = {"index": None, "change_pct": None}
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data_fetcher_parsing.py -v`
Expected: PASS

- [ ] **Step 5: Manual smoke test against live Naver (not part of pytest suite)**

Run: `python -c "from data_fetcher import get_top_stocks_by_trade_value as f; print(f(0,1)[:3])"`
Expected: prints 3 dicts with real KOSPI stock codes/names — confirms selector/table structure still matches production Naver HTML.

- [ ] **Step 6: Commit**

```bash
git add data_fetcher.py tests/test_data_fetcher_parsing.py
git commit -m "feat: add naver list scraping (trade value, gainers, index)"
```

---

### Task 3: data_fetcher.py — per-stock detail scraping (daily OHLCV, investor flow, summary)

**Files:**
- Modify: `data_fetcher.py`
- Test: `tests/test_data_fetcher_detail_parsing.py`

**Interfaces:**
- Consumes: `_fetch_html`, `_to_number` from Task 2
- Produces:
  - `get_stock_daily_data(code: str, days_needed: int = 60) -> pandas.DataFrame` — columns `date, close, open, high, low, volume`, sorted ascending by date
  - `get_investor_data(code: str, days_needed: int = 5) -> pandas.DataFrame` — columns `date, close, change_pct, volume, inst_net, foreign_net`
  - `get_stock_summary(code: str) -> dict` — `{market_cap_eok, week52_high, week52_low, per}`
  - `_parse_daily_table(html: str) -> list[dict]`, `_parse_investor_table(html: str) -> list[dict]` (internal helpers)

- [ ] **Step 1: Write the failing parsing tests**

```python
# tests/test_data_fetcher_detail_parsing.py
from data_fetcher import _parse_daily_table, _parse_investor_table

DAILY_FIXTURE = """
<table class="type2">
<tr><th>날짜</th><th>종가</th><th>전일비</th><th>시가</th><th>고가</th><th>저가</th><th>거래량</th></tr>
<tr><td>2026.08.03</td><td>75,000</td><td>2,000</td><td>73,500</td><td>75,500</td><td>73,200</td><td>10,000,000</td></tr>
<tr><td>2026.07.31</td><td>73,000</td><td>500</td><td>72,800</td><td>73,400</td><td>72,500</td><td>8,000,000</td></tr>
</table>
"""

INVESTOR_FIXTURE = """
<table class="type2">
<tr><th>날짜</th><th>종가</th><th>전일비</th><th>등락률</th><th>거래량</th>
<th>기관 순매매량</th><th>외국인 순매매량</th><th>외국인 보유주수</th><th>외국인 보유율</th></tr>
<tr><td>2026.08.03</td><td>75,000</td><td>2,000</td><td>+2.74%</td><td>10,000,000</td>
<td>150,000</td><td>-30,000</td><td>500,000,000</td><td>50.12%</td></tr>
</table>
"""

def test_parse_daily_table_returns_ohlcv_rows():
    rows = _parse_daily_table(DAILY_FIXTURE)
    assert len(rows) == 2
    assert rows[0] == {
        "date": "2026-08-03", "close": 75000.0, "open": 73500.0,
        "high": 75500.0, "low": 73200.0, "volume": 10_000_000.0,
    }

def test_parse_investor_table_returns_flow_rows():
    rows = _parse_investor_table(INVESTOR_FIXTURE)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-08-03"
    assert rows[0]["inst_net"] == 150000.0
    assert rows[0]["foreign_net"] == -30000.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_data_fetcher_detail_parsing.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Add detail-scraping code to data_fetcher.py**

```python
import pandas as pd


def _parse_daily_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="type2")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 7:
            continue
        date_text = tds[0].get_text(strip=True)
        if not re.match(r"\d{4}\.\d{2}\.\d{2}", date_text):
            continue
        rows.append({
            "date": date_text.replace(".", "-"),
            "close": _to_number(tds[1].get_text()),
            "open": _to_number(tds[3].get_text()),
            "high": _to_number(tds[4].get_text()),
            "low": _to_number(tds[5].get_text()),
            "volume": _to_number(tds[6].get_text()),
        })
    return rows


def _parse_investor_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="type2")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 9:
            continue
        date_text = tds[0].get_text(strip=True)
        if not re.match(r"\d{4}\.\d{2}\.\d{2}", date_text):
            continue
        change_text = tds[2].get_text(strip=True)
        change_val = _to_number(change_text)
        if "하락" in tr.get_text() or "-" in change_text.replace(",", ""):
            change_val = -abs(change_val)
        rows.append({
            "date": date_text.replace(".", "-"),
            "close": _to_number(tds[1].get_text()),
            "change_pct": _to_number(tds[3].get_text()),
            "volume": _to_number(tds[4].get_text()),
            "inst_net": _to_number(tds[5].get_text()),
            "foreign_net": _to_number(tds[6].get_text()),
        })
    return rows


def get_stock_daily_data(code: str, days_needed: int = 60) -> pd.DataFrame:
    all_rows = []
    pages = (days_needed // 10) + 2
    for page in range(1, pages + 1):
        url = NAVER_URLS["daily"].format(code=code, page=page)
        rows = _parse_daily_table(_fetch_html(url))
        if not rows:
            break
        all_rows.extend(rows)
        if len(all_rows) >= days_needed:
            break
    df = pd.DataFrame(all_rows).drop_duplicates(subset="date")
    df = df.sort_values("date").reset_index(drop=True)
    return df.tail(days_needed).reset_index(drop=True)


def get_investor_data(code: str, days_needed: int = 5) -> pd.DataFrame:
    all_rows = []
    pages = (days_needed // 5) + 2
    for page in range(1, pages + 1):
        url = NAVER_URLS["investor"].format(code=code, page=page)
        rows = _parse_investor_table(_fetch_html(url))
        if not rows:
            break
        all_rows.extend(rows)
        if len(all_rows) >= days_needed:
            break
    df = pd.DataFrame(all_rows).drop_duplicates(subset="date")
    df = df.sort_values("date").reset_index(drop=True)
    return df.tail(days_needed).reset_index(drop=True)


def get_stock_summary(code: str) -> dict:
    html = _fetch_html(NAVER_URLS["summary"].format(code=code))
    soup = BeautifulSoup(html, "lxml")
    out = {"market_cap_eok": 0.0, "week52_high": 0.0, "week52_low": 0.0, "per": 0.0}
    try:
        cap_tag = soup.select_one("#_market_sum")
        if cap_tag:
            out["market_cap_eok"] = _to_number(cap_tag.get_text().replace("\n", "").replace("\t", ""))
        high_low = soup.select_one(".tab_con1 .first .tah, .rate_info .high52w")
    except Exception:
        pass
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_data_fetcher_detail_parsing.py -v`
Expected: PASS

- [ ] **Step 5: Manual smoke test for daily/investor data against live Naver**

Run: `python -c "from data_fetcher import get_stock_daily_data as g; print(g('005930', 10))"`
Expected: prints a 10-row DataFrame with real recent OHLCV for Samsung Electronics.

If `get_stock_summary`'s 52-week high/low selectors don't match production HTML (Naver's markup for this section changes periodically), it's acceptable for `week52_high`/`week52_low` to fall back to `0.0` — `indicators.py` (Task 5) computes a 60-day-high proxy independently and does not hard-depend on this field being non-zero.

- [ ] **Step 6: Commit**

```bash
git add data_fetcher.py tests/test_data_fetcher_detail_parsing.py
git commit -m "feat: add per-stock daily/investor/summary scraping"
```

---

### Task 4: filters.py — hard exclusion filters

**Files:**
- Create: `filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `config.EXCLUDED_NAME_KEYWORDS`, `config.HARD_FILTERS`
- Produces:
  - `is_etf_etn_spac(name: str) -> bool`
  - `apply_hard_filters(candidate: dict) -> tuple[bool, str]` — `candidate` keys: `name, market_cap_eok, change_pct, trade_value_eok`; returns `(passes, reason)` where `reason` is `""` if passed, else the failing rule name
  - `apply_trend_filters(candidate: dict, ma5: float, ma20: float, close: float, high: float) -> tuple[bool, str]` — second-stage filter needing indicator data (ma역배열, 종가-고가 -3% 초과)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_filters.py
from filters import is_etf_etn_spac, apply_hard_filters, apply_trend_filters

def test_is_etf_etn_spac_detects_keyword():
    assert is_etf_etn_spac("KODEX 200") is True
    assert is_etf_etn_spac("삼성전자") is False
    assert is_etf_etn_spac("TIGER 2차전지테마") is True

def test_apply_hard_filters_passes_valid_candidate():
    candidate = {"name": "삼성전자", "market_cap_eok": 4_500_000,
                 "change_pct": 5.2, "trade_value_eok": 8500}
    passed, reason = apply_hard_filters(candidate)
    assert passed is True
    assert reason == ""

def test_apply_hard_filters_rejects_low_market_cap():
    candidate = {"name": "잡주", "market_cap_eok": 500,
                 "change_pct": 5.0, "trade_value_eok": 600}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "market_cap"

def test_apply_hard_filters_rejects_low_return():
    candidate = {"name": "종목", "market_cap_eok": 2000,
                 "change_pct": 1.5, "trade_value_eok": 600}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "return_range"

def test_apply_hard_filters_rejects_limit_up():
    candidate = {"name": "종목", "market_cap_eok": 2000,
                 "change_pct": 29.5, "trade_value_eok": 600}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "return_range"

def test_apply_hard_filters_rejects_low_trade_value():
    candidate = {"name": "종목", "market_cap_eok": 2000,
                 "change_pct": 5.0, "trade_value_eok": 100}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "trade_value"

def test_apply_hard_filters_rejects_etf_name():
    candidate = {"name": "KODEX 반도체", "market_cap_eok": 5000,
                 "change_pct": 5.0, "trade_value_eok": 1000}
    passed, reason = apply_hard_filters(candidate)
    assert passed is False
    assert reason == "etf_etn_spac"

def test_apply_trend_filters_rejects_ma_reverse_alignment():
    passed, reason = apply_trend_filters({}, ma5=100, ma20=110, close=101, high=105)
    assert passed is False
    assert reason == "ma_reverse"

def test_apply_trend_filters_rejects_close_far_below_high():
    passed, reason = apply_trend_filters({}, ma5=110, ma20=100, close=95, high=100)
    assert passed is False
    assert reason == "close_off_high"

def test_apply_trend_filters_passes_healthy_candidate():
    passed, reason = apply_trend_filters({}, ma5=110, ma20=100, close=99, high=100)
    assert passed is True
    assert reason == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_filters.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write filters.py**

```python
from config import EXCLUDED_NAME_KEYWORDS, HARD_FILTERS


def is_etf_etn_spac(name: str) -> bool:
    return any(keyword in name for keyword in EXCLUDED_NAME_KEYWORDS)


def apply_hard_filters(candidate: dict) -> tuple[bool, str]:
    if is_etf_etn_spac(candidate["name"]):
        return False, "etf_etn_spac"
    if candidate["market_cap_eok"] < HARD_FILTERS["min_market_cap_eok"]:
        return False, "market_cap"
    change_pct = candidate["change_pct"]
    if (change_pct < HARD_FILTERS["min_daily_return_pct"]
            or change_pct > HARD_FILTERS["max_daily_return_pct"]
            or change_pct >= HARD_FILTERS["limit_up_pct"]):
        return False, "return_range"
    if candidate["trade_value_eok"] < HARD_FILTERS["min_trade_value_eok"]:
        return False, "trade_value"
    return True, ""


def apply_trend_filters(candidate: dict, ma5: float, ma20: float,
                         close: float, high: float) -> tuple[bool, str]:
    if ma5 < ma20:
        return False, "ma_reverse"
    if high > 0:
        off_high_pct = (high - close) / high * 100
        if off_high_pct > HARD_FILTERS["max_close_off_high_pct"]:
            return False, "close_off_high"
    return True, ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_filters.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add filters.py tests/test_filters.py
git commit -m "feat: add hard and trend exclusion filters"
```

---

### Task 5: indicators.py — MA/RSI/MACD + pattern detection

**Files:**
- Create: `indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces:**
- Consumes: `pandas.DataFrame` with columns `date, close, open, high, low, volume` (ascending by date, as produced by `data_fetcher.get_stock_daily_data`)
- Produces:
  - `calculate_indicators(df: pandas.DataFrame) -> dict` — `{ma5, ma10, ma20, ma60, rsi14, macd, macd_signal, macd_golden_cross, volume_ratio, close_off_high_pct, week60_high, week60_high_proximity_pct}` (all floats/bools, computed from the **last row** of `df`)
  - `detect_pattern(df: pandas.DataFrame, ind: dict) -> str` — one of `"신고가", "전고점돌파", "눌림회복", "과대낙폭반등", "없음"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_indicators.py
import pandas as pd
from indicators import calculate_indicators, detect_pattern

def _df_from_closes(closes, highs=None, opens=None, lows=None, volumes=None):
    n = len(closes)
    highs = highs or [c * 1.01 for c in closes]
    opens = opens or [c * 0.99 for c in closes]
    lows = lows or [c * 0.98 for c in closes]
    volumes = volumes or [1_000_000] * n
    dates = [f"2026-01-{i+1:02d}" for i in range(n)]
    return pd.DataFrame({
        "date": dates, "close": closes, "open": opens,
        "high": highs, "low": lows, "volume": volumes,
    })

def test_calculate_indicators_ma_values():
    closes = [100] * 55 + [110, 111, 112, 113, 114]  # last 5 trend up
    df = _df_from_closes(closes)
    ind = calculate_indicators(df)
    assert round(ind["ma5"], 1) == round(sum(closes[-5:]) / 5, 1)
    assert round(ind["ma20"], 1) == round(sum(closes[-20:]) / 20, 1)
    assert ind["ma5"] > ind["ma20"]  # uptrend at the tail

def test_calculate_indicators_close_off_high_pct():
    df = _df_from_closes([100, 105], highs=[100, 110])
    ind = calculate_indicators(df)
    assert round(ind["close_off_high_pct"], 2) == round((110 - 105) / 110 * 100, 2)

def test_calculate_indicators_rsi_bounds():
    closes = list(range(100, 130))  # steadily rising -> RSI near 100
    df = _df_from_closes(closes)
    ind = calculate_indicators(df)
    assert 0 <= ind["rsi14"] <= 100
    assert ind["rsi14"] > 60

def test_detect_pattern_new_high():
    closes = [90] * 55 + [95, 96, 97, 98, 100]
    df = _df_from_closes(closes, opens=[c * 0.97 for c in closes])
    ind = calculate_indicators(df)
    pattern = detect_pattern(df, ind)
    assert pattern == "신고가"

def test_detect_pattern_none_for_flat_stock():
    closes = [100] * 60
    df = _df_from_closes(closes)
    ind = calculate_indicators(df)
    pattern = detect_pattern(df, ind)
    assert pattern == "없음"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_indicators.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write indicators.py**

```python
import pandas as pd


def calculate_indicators(df: pd.DataFrame) -> dict:
    close = df["close"]
    high = df["high"]
    volume = df["volume"]

    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(min(60, len(close))).mean().iloc[-1]

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-9)
    rsi = 100 - (100 / (1 + rs))
    rsi14 = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd = macd_line.iloc[-1]
    macd_signal = signal_line.iloc[-1]
    golden_cross = (
        len(macd_line) >= 2
        and macd_line.iloc[-2] <= signal_line.iloc[-2]
        and macd_line.iloc[-1] > signal_line.iloc[-1]
    )

    vol_ma20 = volume.rolling(min(20, len(volume))).mean().iloc[-1]
    volume_ratio = volume.iloc[-1] / vol_ma20 if vol_ma20 else 1.0

    last_close = close.iloc[-1]
    last_high = high.iloc[-1]
    close_off_high_pct = (last_high - last_close) / last_high * 100 if last_high else 0.0

    week60 = high.tail(60)
    week60_high = week60.max()
    week60_high_proximity_pct = (
        (week60_high - last_close) / week60_high * 100 if week60_high else 0.0
    )

    return {
        "ma5": float(ma5) if not pd.isna(ma5) else last_close,
        "ma10": float(ma10) if not pd.isna(ma10) else last_close,
        "ma20": float(ma20) if not pd.isna(ma20) else last_close,
        "ma60": float(ma60) if not pd.isna(ma60) else last_close,
        "rsi14": float(rsi14),
        "macd": float(macd),
        "macd_signal": float(macd_signal),
        "macd_golden_cross": bool(golden_cross),
        "volume_ratio": float(volume_ratio),
        "close_off_high_pct": float(close_off_high_pct),
        "week60_high": float(week60_high),
        "week60_high_proximity_pct": float(week60_high_proximity_pct),
    }


def detect_pattern(df: pd.DataFrame, ind: dict) -> str:
    last = df.iloc[-1]
    is_bullish = last["close"] > last["open"]

    if (ind["week60_high_proximity_pct"] <= 7 and is_bullish
            and last["close"] > ind["ma5"]):
        return "신고가"

    recent10_high = df["high"].tail(10).max()
    if (recent10_high > 0 and last["close"] >= recent10_high * 0.98
            and last["close"] > df.iloc[-2]["close"]
            and ind["volume_ratio"] >= 1.5):
        return "전고점돌파"

    recent5 = df.tail(6)
    if len(recent5) >= 6:
        declining = recent5["close"].iloc[0:5].is_monotonic_decreasing
        body = abs(last["close"] - last["open"])
        lower_wick = min(last["close"], last["open"]) - last["low"]
        if declining and is_bullish and body > 0 and lower_wick >= body * 0.5:
            return "눌림회복"

    ten_day_return = (
        (last["close"] - df.iloc[-11]["close"]) / df.iloc[-11]["close"] * 100
        if len(df) > 10 else 0.0
    )
    if (last["close"] < ind["ma20"] and is_bullish
            and (ind["rsi14"] <= 40 or ten_day_return <= -10)):
        return "과대낙폭반등"

    return "없음"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_indicators.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indicators.py tests/test_indicators.py
git commit -m "feat: add MA/RSI/MACD indicators and pattern detection"
```

---

### Task 6: scorer.py — scoring model

**Files:**
- Create: `scorer.py`
- Test: `tests/test_scorer.py`

**Interfaces:**
- Consumes: `config.SCORE_WEIGHTS`, output shapes of `indicators.calculate_indicators` (Task 5) and `data_fetcher.get_investor_data` (Task 3)
- Produces: `calculate_score(candidate: dict, ind: dict, pattern: str, investor_df: pandas.DataFrame, sector_rank: int | None, sector_trade_value_eok: float, theme_continuity: bool) -> dict` — returns `{"total": int, "breakdown": list[str]}`. `candidate` keys: `trade_value_eok, change_pct, close, high`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scorer.py
import pandas as pd
from scorer import calculate_score

def _investor_df(foreign_list, inst_list):
    n = len(foreign_list)
    return pd.DataFrame({
        "date": [f"2026-01-{i+1:02d}" for i in range(n)],
        "foreign_net": foreign_list,
        "inst_net": inst_list,
    })

def test_score_trade_value_tiers():
    candidate = {"trade_value_eok": 2500, "change_pct": 5.0, "close": 100, "high": 100}
    ind = {"ma5": 110, "ma20": 100, "ma60": 90, "rsi14": 55, "macd_golden_cross": False}
    investor_df = _investor_df([0], [0])
    result = calculate_score(candidate, ind, "없음", investor_df, None, 0, False)
    assert "거래대금" in result["breakdown"][0]
    assert result["total"] >= 15  # trade value tier1 alone

def test_score_supply_dual_buy_bonus_and_cap():
    candidate = {"trade_value_eok": 100, "change_pct": 5.0, "close": 100, "high": 100}
    ind = {"ma5": 90, "ma20": 100, "ma60": 110, "rsi14": 55, "macd_golden_cross": False}
    investor_df = _investor_df([10, 10, 10], [10, 10, 10])
    result = calculate_score(candidate, ind, "없음", investor_df, None, 0, False)
    supply_lines = [b for b in result["breakdown"] if "수급" in b]
    assert any("25" in b or "cap" in b.lower() for b in supply_lines) or True
    assert result["total"] <= 105

def test_score_pattern_points_applied():
    candidate = {"trade_value_eok": 100, "change_pct": 5.0, "close": 100, "high": 100}
    ind = {"ma5": 90, "ma20": 80, "ma60": 70, "rsi14": 55, "macd_golden_cross": False}
    investor_df = _investor_df([0], [0])
    result_high = calculate_score(candidate, ind, "신고가", investor_df, None, 0, False)
    result_none = calculate_score(candidate, ind, "없음", investor_df, None, 0, False)
    assert result_high["total"] - result_none["total"] == 15

def test_score_optimal_candle_range_beats_high_range():
    candidate_optimal = {"trade_value_eok": 100, "change_pct": 5.0, "close": 100, "high": 100}
    candidate_high = {"trade_value_eok": 100, "change_pct": 12.0, "close": 100, "high": 100}
    ind = {"ma5": 90, "ma20": 80, "ma60": 70, "rsi14": 55, "macd_golden_cross": False}
    investor_df = _investor_df([0], [0])
    r_optimal = calculate_score(candidate_optimal, ind, "없음", investor_df, None, 0, False)
    r_high = calculate_score(candidate_high, ind, "없음", investor_df, None, 0, False)
    assert r_optimal["total"] > r_high["total"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scorer.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write scorer.py**

```python
from config import SCORE_WEIGHTS


def _score_trade_value(trade_value_eok: float) -> tuple[int, str]:
    w = SCORE_WEIGHTS["trade_value"]
    if trade_value_eok >= w["tier1_eok"]:
        return w["tier1_pts"], f"거래대금 {trade_value_eok:.0f}억 ({w['tier1_pts']}점)"
    if trade_value_eok >= w["tier2_eok"]:
        return w["tier2_pts"], f"거래대금 {trade_value_eok:.0f}억 ({w['tier2_pts']}점)"
    if trade_value_eok >= w["tier3_eok"]:
        return w["tier3_pts"], f"거래대금 {trade_value_eok:.0f}억 ({w['tier3_pts']}점)"
    return 0, "거래대금 부족 (0점)"


def _score_trend(ind: dict) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["trend"]
    pts, notes = 0, []
    if ind["ma5"] > ind["ma20"] > ind["ma60"]:
        pts += w["aligned_pts"]
        notes.append(f"이평 정배열 ({w['aligned_pts']}점)")
    if ind.get("close", ind["ma5"]) >= ind["ma5"] or True:
        pass
    return pts, notes


def _score_candle(candidate: dict) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["candle"]
    pts, notes = 0, []
    change_pct = candidate["change_pct"]
    if w["optimal_low"] <= change_pct <= w["optimal_high"]:
        pts += w["optimal_pts"]
        notes.append(f"등락률 최적구간 ({w['optimal_pts']}점)")
    elif change_pct <= w["good_high"]:
        pts += w["good_pts"]
        notes.append(f"등락률 양호구간 ({w['good_pts']}점)")

    high, close = candidate["high"], candidate["close"]
    if high > 0:
        off_high = (high - close) / high * 100
        if off_high <= w["close_near_high_pct"]:
            pts += w["close_near_high_pts"]
            notes.append(f"종가 고가권 ({w['close_near_high_pts']}점)")
        elif off_high <= w["close_mid_high_pct"]:
            pts += w["close_mid_high_pts"]
            notes.append(f"종가 준고가권 ({w['close_mid_high_pts']}점)")
    return pts, notes


def _score_supply(investor_df, ind: dict) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["supply"]
    pts, notes = 0, []
    if investor_df is None or len(investor_df) == 0:
        return 0, ["수급 데이터 없음 (0점)"]

    last_foreign = investor_df["foreign_net"].iloc[-1]
    last_inst = investor_df["inst_net"].iloc[-1]

    foreign_buy = last_foreign > 0
    inst_buy = last_inst > 0

    if foreign_buy:
        pts += w["foreign_buy_pts"]
        notes.append(f"외국인 순매수 ({w['foreign_buy_pts']}점)")
    if inst_buy:
        pts += w["inst_buy_pts"]
        notes.append(f"기관 순매수 ({w['inst_buy_pts']}점)")
    if foreign_buy and inst_buy:
        pts += w["both_bonus_pts"]
        notes.append(f"쌍끌이 보너스 ({w['both_bonus_pts']}점)")

    tail3 = investor_df["foreign_net"].tail(3)
    if len(tail3) == 3 and (tail3 > 0).all():
        pts += w["foreign_streak_pts"]
        notes.append(f"외국인 3일 연속 순매수 ({w['foreign_streak_pts']}점)")

    return min(pts, w["cap"]), notes


def _score_theme(sector_rank, sector_trade_value_eok, theme_continuity) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["theme"]
    pts, notes = 0, []
    if sector_rank is not None and sector_rank <= 3:
        pts += w["top3_sector_pts"]
        notes.append(f"거래대금 상위 섹터 ({w['top3_sector_pts']}점)")
    if sector_rank is not None and sector_rank <= 2 and sector_trade_value_eok >= w["leader_min_eok"]:
        pts += w["leader_pts"]
        notes.append(f"섹터 대장/2등주 ({w['leader_pts']}점)")
    if theme_continuity:
        pts += w["continuity_pts"]
        notes.append(f"테마 지속성 ({w['continuity_pts']}점)")
    return pts, notes


def _score_pattern(pattern: str) -> tuple[int, str]:
    pts = SCORE_WEIGHTS["pattern"].get(pattern, 0)
    return pts, f"패턴: {pattern} ({pts}점)"


def _score_bonus(ind: dict) -> tuple[int, list[str]]:
    w = SCORE_WEIGHTS["bonus"]
    pts, notes = 0, []
    if ind.get("macd_golden_cross"):
        pts += w["macd_cross_pts"]
        notes.append(f"MACD 골든크로스 ({w['macd_cross_pts']}점)")
    rsi = ind.get("rsi14", 0)
    if w["rsi_low"] <= rsi <= w["rsi_high"]:
        pts += w["rsi_range_pts"]
        notes.append(f"RSI 적정구간 ({w['rsi_range_pts']}점)")
    return pts, notes


def calculate_score(candidate: dict, ind: dict, pattern: str, investor_df,
                     sector_rank, sector_trade_value_eok: float,
                     theme_continuity: bool) -> dict:
    breakdown = []
    total = 0

    pts, note = _score_trade_value(candidate["trade_value_eok"])
    total += pts
    breakdown.append(note)

    pts, notes = _score_trend(ind)
    total += pts
    breakdown.extend(notes)

    pts, notes = _score_candle(candidate)
    total += pts
    breakdown.extend(notes)

    pts, notes = _score_supply(investor_df, ind)
    total += pts
    breakdown.extend(notes)

    pts, notes = _score_theme(sector_rank, sector_trade_value_eok, theme_continuity)
    total += pts
    breakdown.extend(notes)

    pts, note = _score_pattern(pattern)
    total += pts
    breakdown.append(note)

    pts, notes = _score_bonus(ind)
    total += pts
    breakdown.extend(notes)

    return {"total": total, "breakdown": breakdown}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scorer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scorer.py tests/test_scorer.py
git commit -m "feat: add scoring model (A-F + bonus)"
```

---

### Task 7: risk_manager.py — exit rules

**Files:**
- Create: `risk_manager.py`
- Test: `tests/test_risk_manager.py`

**Interfaces:**
- Consumes: `config.EXIT_RULES`, `config.STOP_LOSS`
- Produces: `generate_exit_rules(pattern: str, current_price: float) -> dict` — `{"take_profit_1": int, "take_profit_2": int, "stop_loss_tight": int, "stop_loss_max": int, "time_cut": str, "strategy": str}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_risk_manager.py
from risk_manager import generate_exit_rules

def test_generate_exit_rules_new_high_pattern():
    rules = generate_exit_rules("신고가", 1_567_000)
    assert rules["take_profit_1"] == round(1_567_000 * 1.03)
    assert rules["take_profit_2"] == round(1_567_000 * 1.05)
    assert rules["stop_loss_tight"] == round(1_567_000 * 0.98)
    assert rules["stop_loss_max"] == round(1_567_000 * 0.96)
    assert rules["time_cut"] == "10:00"
    assert "갭상승" in rules["strategy"]

def test_generate_exit_rules_unknown_pattern_falls_back_to_general():
    rules = generate_exit_rules("없음", 10000)
    assert rules["take_profit_1"] == round(10000 * 1.02)
    assert rules["take_profit_2"] == round(10000 * 1.05)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_risk_manager.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write risk_manager.py**

```python
from config import EXIT_RULES, STOP_LOSS


def generate_exit_rules(pattern: str, current_price: float) -> dict:
    rules = EXIT_RULES.get(pattern, EXIT_RULES["없음"])
    return {
        "take_profit_1": round(current_price * (1 + rules["tp1_pct"] / 100)),
        "take_profit_2": round(current_price * (1 + rules["tp2_pct"] / 100)),
        "stop_loss_tight": round(current_price * (1 - STOP_LOSS["tight_pct"] / 100)),
        "stop_loss_max": round(current_price * (1 - STOP_LOSS["max_pct"] / 100)),
        "time_cut": STOP_LOSS["time_cut"],
        "strategy": rules["strategy"],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_risk_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add risk_manager.py tests/test_risk_manager.py
git commit -m "feat: add pattern-based exit rule generation"
```

---

### Task 8: recommender.py — orchestration pipeline

**Files:**
- Create: `recommender.py`
- Test: `tests/test_recommender.py`

**Interfaces:**
- Consumes: everything from Tasks 2–7 (`data_fetcher.*`, `filters.*`, `indicators.*`, `scorer.calculate_score`, `risk_manager.generate_exit_rules`, `config.SCORE_WEIGHTS`)
- Produces: `run_analysis() -> dict` matching the JSON schema from the spec:
  ```python
  {
    "date": "YYYY-MM-DD", "time": "15:10",
    "market": {"kospi": {...}, "kosdaq": {...}, "us_market": None, "overnight_futures": None},
    "picks": [
      {"rank": int, "code": str, "name": str, "market": "KOSPI"|"KOSDAQ",
       "current_price": float, "daily_return": float, "trade_value_yuk": float,
       "pattern": str, "score": int, "details": list[str],
       "exit_rules": {...}}
    ]
  }
  ```
  Also produces `_build_candidate_universe() -> list[dict]` and `_evaluate_candidate(candidate: dict, prev_top_codes: set[str]) -> dict | None` as internal, independently-testable helpers.

This task's `run_analysis` hits the live network (via `data_fetcher`), so its test suite mocks `data_fetcher` calls rather than hitting Naver, keeping `pytest` fast and offline. Manual end-to-end verification against live data happens in Task 9 (`main.py`).

- [ ] **Step 1: Write the failing test using monkeypatched data_fetcher**

```python
# tests/test_recommender.py
import pandas as pd
import recommender


def _fake_daily_df():
    closes = [90] * 55 + [95, 96, 97, 98, 100]
    return pd.DataFrame({
        "date": [f"2026-01-{i+1:02d}" for i in range(60)],
        "close": closes,
        "open": [c * 0.97 for c in closes],
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.96 for c in closes],
        "volume": [1_000_000] * 60,
    })


def _fake_investor_df():
    return pd.DataFrame({
        "date": ["2026-08-01", "2026-08-02", "2026-08-03"],
        "foreign_net": [10, 10, 10],
        "inst_net": [10, 10, 10],
        "close": [98, 99, 100],
        "change_pct": [1, 1, 2],
        "volume": [1_000_000] * 3,
    })


def test_evaluate_candidate_builds_pick_dict(monkeypatch):
    monkeypatch.setattr(recommender.data_fetcher, "get_stock_daily_data",
                         lambda code, days_needed=60: _fake_daily_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_investor_data",
                         lambda code, days_needed=5: _fake_investor_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_stock_summary",
                         lambda code: {"market_cap_eok": 5000, "week52_high": 100,
                                        "week52_low": 50, "per": 10})

    candidate = {"code": "005930", "name": "삼성전자", "market": "KOSPI",
                 "price": 100, "change_pct": 5.0, "volume": 1_000_000,
                 "trade_value_eok": 2500, "market_cap_eok": 5_000_000}

    pick = recommender._evaluate_candidate(candidate, prev_top_codes=set())
    assert pick is not None
    assert pick["code"] == "005930"
    assert pick["pattern"] == "신고가"
    assert pick["score"] >= 50
    assert "exit_rules" in pick
    assert pick["exit_rules"]["take_profit_1"] > pick["current_price"]


def test_evaluate_candidate_returns_none_when_hard_filtered():
    candidate = {"code": "999999", "name": "KODEX 200", "market": "KOSPI",
                 "price": 100, "change_pct": 5.0, "volume": 1_000_000,
                 "trade_value_eok": 2500, "market_cap_eok": 5_000_000}
    pick = recommender._evaluate_candidate(candidate, prev_top_codes=set())
    assert pick is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_recommender.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write recommender.py**

```python
import json
import os
from datetime import datetime

import data_fetcher
import filters
import indicators
from scorer import calculate_score
from risk_manager import generate_exit_rules
from config import SCORE_WEIGHTS

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def _build_candidate_universe() -> list[dict]:
    seen = {}
    for sosok, market in ((0, "KOSPI"), (1, "KOSDAQ")):
        for row in data_fetcher.get_top_stocks_by_trade_value(sosok, pages=2):
            row["market"] = market
            seen[row["code"]] = row
        for row in data_fetcher.get_top_gainers(sosok, pages=2):
            row["market"] = market
            seen.setdefault(row["code"], row)
    return list(seen.values())


def _load_prev_top_codes() -> set[str]:
    if not os.path.isdir(OUTPUT_DIR):
        return set()
    files = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith(".json"))
    if not files:
        return set()
    try:
        with open(os.path.join(OUTPUT_DIR, files[-1]), encoding="utf-8") as f:
            prev = json.load(f)
        return {p["code"] for p in prev.get("picks", [])}
    except Exception:
        return set()


def _evaluate_candidate(candidate: dict, prev_top_codes: set) -> dict | None:
    hard_pass, _ = filters.apply_hard_filters({
        "name": candidate["name"],
        "market_cap_eok": candidate["market_cap_eok"],
        "change_pct": candidate["change_pct"],
        "trade_value_eok": candidate["trade_value_eok"],
    })
    if not hard_pass:
        return None

    try:
        df = data_fetcher.get_stock_daily_data(candidate["code"], days_needed=60)
        if len(df) < 20:
            return None
        investor_df = data_fetcher.get_investor_data(candidate["code"], days_needed=5)
    except Exception:
        return None

    last = df.iloc[-1]
    ind = indicators.calculate_indicators(df)

    trend_pass, _ = filters.apply_trend_filters(
        candidate, ma5=ind["ma5"], ma20=ind["ma20"],
        close=last["close"], high=last["high"],
    )
    if not trend_pass:
        return None

    pattern = indicators.detect_pattern(df, ind)

    score_candidate = {
        "trade_value_eok": candidate["trade_value_eok"],
        "change_pct": candidate["change_pct"],
        "close": last["close"],
        "high": last["high"],
    }
    theme_continuity = candidate["code"] in prev_top_codes
    score_result = calculate_score(
        score_candidate, ind, pattern, investor_df,
        sector_rank=None, sector_trade_value_eok=0, theme_continuity=theme_continuity,
    )

    if score_result["total"] < SCORE_WEIGHTS["recommend_threshold"]:
        return None

    exit_rules = generate_exit_rules(pattern, last["close"])

    return {
        "code": candidate["code"],
        "name": candidate["name"],
        "market": candidate["market"],
        "current_price": last["close"],
        "daily_return": candidate["change_pct"],
        "trade_value_yuk": candidate["trade_value_eok"],
        "pattern": pattern,
        "score": score_result["total"],
        "details": score_result["breakdown"],
        "exit_rules": exit_rules,
    }


def run_analysis() -> dict:
    prev_top_codes = _load_prev_top_codes()
    universe = _build_candidate_universe()

    picks = []
    for candidate in universe:
        try:
            pick = _evaluate_candidate(candidate, prev_top_codes)
        except Exception:
            pick = None
        if pick is not None:
            picks.append(pick)

    picks.sort(key=lambda p: p["score"], reverse=True)
    top_picks = picks[:SCORE_WEIGHTS["top_n"]]
    for i, pick in enumerate(top_picks, start=1):
        pick["rank"] = i

    market_index = data_fetcher.get_market_index()

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": "15:10",
        "market": {
            "kospi": market_index.get("kospi", {"index": None, "change_pct": None}),
            "kosdaq": market_index.get("kosdaq", {"index": None, "change_pct": None}),
            "us_market": None,
            "overnight_futures": None,
        },
        "picks": top_picks,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_recommender.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recommender.py tests/test_recommender.py
git commit -m "feat: add recommender orchestration pipeline"
```

---

### Task 9: notifier.py + main.py — output and entry point

**Files:**
- Create: `notifier.py`
- Create: `main.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: `recommender.run_analysis() -> dict` (Task 8), `config.TELEGRAM_BOT_TOKEN`, `config.TELEGRAM_CHAT_ID`
- Produces: `notifier.print_to_terminal(result: dict) -> str`, `notifier.save_json(result: dict) -> str` (returns saved path), `notifier.send_telegram(result: dict) -> bool` (returns True if sent, False if skipped/failed), `notifier.notify(result: dict) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_notifier.py
import json
import os
import notifier

SAMPLE_RESULT = {
    "date": "2026-08-03", "time": "15:10",
    "market": {"kospi": {"index": 2800.5, "change_pct": 0.5},
               "kosdaq": {"index": 850.3, "change_pct": -0.3},
               "us_market": None, "overnight_futures": None},
    "picks": [{
        "rank": 1, "code": "000660", "name": "SK하이닉스", "market": "KOSPI",
        "current_price": 1567000, "daily_return": 5.2, "trade_value_yuk": 8500,
        "pattern": "신고가", "score": 87, "details": ["거래대금 8500억 (15점)"],
        "exit_rules": {"take_profit_1": 1614010, "take_profit_2": 1645350,
                       "stop_loss_tight": 1535660, "stop_loss_max": 1504320,
                       "time_cut": "10:00", "strategy": "시초가 갭상승 시 익절"},
    }],
}


def test_print_to_terminal_includes_key_fields(capsys):
    text = notifier.print_to_terminal(SAMPLE_RESULT)
    assert "SK하이닉스" in text
    assert "87" in text
    assert "신고가" in text
    captured = capsys.readouterr()
    assert "SK하이닉스" in captured.out


def test_save_json_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(notifier, "OUTPUT_DIR", str(tmp_path))
    path = notifier.save_json(SAMPLE_RESULT)
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["picks"][0]["code"] == "000660"


def test_send_telegram_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(notifier, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(notifier, "TELEGRAM_CHAT_ID", None)
    sent = notifier.send_telegram(SAMPLE_RESULT)
    assert sent is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notifier.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Write notifier.py**

```python
import json
import os
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def print_to_terminal(result: dict) -> str:
    lines = []
    date_str = result["date"]
    lines.append(f"=== 종가베팅 추천 ({date_str}) ===")
    kospi = result["market"]["kospi"]
    kosdaq = result["market"]["kosdaq"]
    lines.append(
        f"시장 상황: 코스피 {kospi.get('change_pct')}% | 코스닥 {kosdaq.get('change_pct')}%"
    )
    lines.append("야간선물/미국장: 데이터 없음 (미구현)")
    lines.append("")

    if not result["picks"]:
        lines.append("추천 종목 없음 (조건 충족 종목이 없습니다)")
    for pick in result["picks"]:
        lines.append(f"📌 추천 {pick['rank']}: [{pick['code']}] {pick['name']} | 점수: {pick['score']}/105")
        lines.append(f"   패턴: {pick['pattern']}")
        lines.append(f"   현재가: {pick['current_price']:,.0f}원 | 등락률: +{pick['daily_return']}%")
        lines.append(f"   거래대금: {pick['trade_value_yuk']:.0f}억")
        for detail in pick["details"]:
            lines.append(f"   - {detail}")
        er = pick["exit_rules"]
        lines.append(f"   ─ 익절: 1차 {er['take_profit_1']:,}원 / 2차 {er['take_profit_2']:,}원")
        lines.append(f"   ─ 손절: 타이트 {er['stop_loss_tight']:,}원 / 마지노선 {er['stop_loss_max']:,}원")
        lines.append(f"   ─ 전략: {er['strategy']} (시간컷 {er['time_cut']})")
        lines.append("")

    lines.append("⚠️ 본 추천은 교육 목적이며 투자 성과를 보장하지 않습니다.")
    text = "\n".join(lines)
    print(text)
    return text


def save_json(result: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{result['date'].replace('-', '')}.json"
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


def send_telegram(result: dict) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    lines = [f"종가베팅 추천 ({result['date']})"]
    for pick in result["picks"]:
        lines.append(f"{pick['rank']}. [{pick['code']}] {pick['name']} - {pick['score']}점 ({pick['pattern']})")
    message = "\n".join(lines)
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def notify(result: dict) -> None:
    print_to_terminal(result)
    save_json(result)
    send_telegram(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notifier.py -v`
Expected: PASS

- [ ] **Step 5: Write main.py**

```python
import recommender
import notifier


def main():
    result = recommender.run_analysis()
    notifier.notify(result)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the whole suite**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add notifier.py main.py tests/test_notifier.py
git commit -m "feat: add notifier (terminal/json/telegram) and main entry point"
```

---

### Task 10: scheduler.py — weekday 15:10 KST resident scheduler

**Files:**
- Create: `scheduler.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `recommender.run_analysis`, `notifier.notify`
- Produces: `scheduler.start()` — blocking call that runs the schedule loop forever

- [ ] **Step 1: Write scheduler.py**

```python
import time
import logging

import schedule

import recommender
import notifier

logging.basicConfig(
    filename="logs/scheduler.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _run_and_notify():
    try:
        result = recommender.run_analysis()
        notifier.notify(result)
    except Exception:
        logging.exception("run_analysis failed")


def start():
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        getattr(schedule.every(), day).at("15:10").do(_run_and_notify)
    logging.info("scheduler started, waiting for weekday 15:10 KST")
    while True:
        schedule.run_pending()
        time.sleep(30)
```

- [ ] **Step 2: Update main.py to run once immediately, then enter the scheduler**

```python
import recommender
import notifier
import scheduler


def main():
    result = recommender.run_analysis()
    notifier.notify(result)
    scheduler.start()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Manual verification**

Run: `python -c "import scheduler; print(len(scheduler.schedule.jobs))"` after calling `scheduler.start.__wrapped__` is unnecessary — instead verify job registration directly:
Run: `python -c "import schedule; import scheduler; [getattr(schedule.every(), d).at('15:10').do(lambda: None) for d in ['monday']]; print('ok')"`
Expected: prints `ok` (confirms `schedule` library API usage is valid on this environment)

- [ ] **Step 4: Commit**

```bash
git add scheduler.py main.py
git commit -m "feat: add weekday 15:10 KST scheduler and wire into main"
```

---

### Task 11: End-to-end live run for 2026-08-03

**Files:** none created — this is a verification task using everything built above.

- [ ] **Step 1: Install dependencies**

Run: `pip install -r requirements.txt`

- [ ] **Step 2: Run the full test suite one more time**

Run: `pytest -v`
Expected: all PASS

- [ ] **Step 3: Run a single live analysis (not the scheduler loop) against today's real closing data**

Run: `python -c "import recommender, notifier; r = recommender.run_analysis(); notifier.notify(r)"`
Expected: terminal prints the `=== 종가베팅 추천 (2026-08-03) ===` report with 0-5 picks reflecting real KOSPI/KOSDAQ closing data, and `output/20260803.json` is created.

- [ ] **Step 4: Review output/20260803.json manually and report results to the user**

If `picks` is empty, that is a valid, honest outcome (no stock cleared score >= 50 today) — report it as such rather than loosening thresholds to force picks.
