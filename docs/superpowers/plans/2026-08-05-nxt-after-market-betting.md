# NXT 애프터마켓 종가베팅 분석 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `session="nxt"`(19:50 KST) 실행 경로를 외부 입력 파일(NXT 시세 + 해외 선행지표) 기반의 무추천 판정 → NXT 전용 점수화 → NXT 전용 마크다운 리포트 파이프라인으로 교체한다. `session="close"`(15:10) 경로는 전혀 건드리지 않는다.

**Architecture:** 새 모듈 `input_loader.py`(수동 입력 파일 로드), `overseas.py`(네이버 해외지수/환율/유가 자동 스크래핑), `veto.py`(무추천 판정)를 추가하고, 기존 `filters.py`/`scorer.py`/`risk_manager.py`에 NXT 전용 함수를 병렬로 추가한다. `recommender.py`는 `session`으로 완전히 분기되는 `run_nxt_analysis()`를 새로 만들고, `notifier.py`는 NXT 세션일 때만 마크다운 리포트를 추가 저장한다.

**Tech Stack:** Python 3, requests, BeautifulSoup4, pandas, pytest (기존 스택 재사용, 신규 의존성 없음)

## Global Constraints

- 결측 데이터는 어디서든 "데이터 부족"으로 표시하고 추정하지 않는다.
- `close` 세션의 기존 파일/함수/출력 스키마는 수정하지 않는다.
- 개별 종목/데이터 소스 처리 중 예외는 해당 항목만 스킵하고 전체 실행을 막지 않는다.
- 신규 외부 HTTP 호출은 기존 `config.HEADERS`/`config.ENCODING`과 `data_fetcher._fetch_html`을 재사용한다.
- 인코딩은 기존 코드와 동일하게 `euc-kr` 응답을 처리한다.

---

### Task 1: 외부 입력 파일 로더 (`input_loader.py`)

**Files:**
- Create: `input_loader.py`
- Create: `input/nxt_signals.example.json`
- Modify: `.gitignore` (add `input/nxt_signals.json`)
- Test: `tests/test_input_loader.py`

**Interfaces:**
- Produces: `input_loader.load_nxt_signals(path: str = DEFAULT_PATH, today: str | None = None) -> dict` returning:
  ```python
  {
    "date": str | None,
    "overseas": {
      "sp500_futures_change_pct": float | None,
      "nasdaq_futures_change_pct": float | None,
      "sox_change_pct": float | None,
      "kospi200_night_futures_change_pct": float | None,
      "us_10y_yield_change_bp": float | None,
      "hynix_adr_change_pct": float | None,
      "samsung_adr_change_pct": float | None,
    },
    "events": {"major_event_tomorrow": bool, "event_desc": str, "geopolitical_shock": bool},
    "nxt_stocks": list[dict],  # each: code, name, nxt_price, nxt_change_pct, nxt_trade_value_eok, nxt_volume, buy_sell_ratio
  }
  ```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_input_loader.py
import json
import input_loader


def test_load_returns_empty_defaults_when_file_missing(tmp_path):
    path = str(tmp_path / "nxt_signals.json")
    data = input_loader.load_nxt_signals(path=path, today="2026-08-05")
    assert data["nxt_stocks"] == []
    assert data["overseas"]["sox_change_pct"] is None
    assert data["events"]["major_event_tomorrow"] is False


def test_load_returns_empty_defaults_when_date_stale(tmp_path):
    path = tmp_path / "nxt_signals.json"
    path.write_text(json.dumps({"date": "2026-08-04", "nxt_stocks": [{"code": "000660"}]}),
                     encoding="utf-8")
    data = input_loader.load_nxt_signals(path=str(path), today="2026-08-05")
    assert data["nxt_stocks"] == []


def test_load_passes_through_valid_same_day_data(tmp_path):
    path = tmp_path / "nxt_signals.json"
    payload = {
        "date": "2026-08-05",
        "overseas": {"sox_change_pct": -0.8, "sp500_futures_change_pct": 0.3},
        "events": {"major_event_tomorrow": True, "event_desc": "FOMC", "geopolitical_shock": False},
        "nxt_stocks": [{"code": "000660", "name": "SK하이닉스", "nxt_price": 250000,
                         "nxt_change_pct": 4.5, "nxt_trade_value_eok": 120,
                         "nxt_volume": 50000, "buy_sell_ratio": 1.4}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    data = input_loader.load_nxt_signals(path=str(path), today="2026-08-05")
    assert data["overseas"]["sox_change_pct"] == -0.8
    assert data["overseas"]["nasdaq_futures_change_pct"] is None
    assert data["events"]["major_event_tomorrow"] is True
    assert data["nxt_stocks"][0]["code"] == "000660"


def test_load_handles_malformed_json(tmp_path):
    path = tmp_path / "nxt_signals.json"
    path.write_text("{not valid json", encoding="utf-8")
    data = input_loader.load_nxt_signals(path=str(path), today="2026-08-05")
    assert data["nxt_stocks"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_input_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'input_loader'`

- [ ] **Step 3: Implement `input_loader.py`**

```python
import json
import os
from datetime import datetime

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "input", "nxt_signals.json")

_EMPTY_OVERSEAS = {
    "sp500_futures_change_pct": None,
    "nasdaq_futures_change_pct": None,
    "sox_change_pct": None,
    "kospi200_night_futures_change_pct": None,
    "us_10y_yield_change_bp": None,
    "hynix_adr_change_pct": None,
    "samsung_adr_change_pct": None,
}
_EMPTY_EVENTS = {"major_event_tomorrow": False, "event_desc": "", "geopolitical_shock": False}


def _empty_signals() -> dict:
    return {
        "date": None,
        "overseas": dict(_EMPTY_OVERSEAS),
        "events": dict(_EMPTY_EVENTS),
        "nxt_stocks": [],
    }


def load_nxt_signals(path: str = DEFAULT_PATH, today: str | None = None) -> dict:
    today = today or datetime.now().strftime("%Y-%m-%d")
    if not os.path.exists(path):
        return _empty_signals()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _empty_signals()
    if data.get("date") != today:
        return _empty_signals()

    merged = _empty_signals()
    merged["date"] = data.get("date")
    merged["overseas"].update(data.get("overseas") or {})
    merged["events"].update(data.get("events") or {})
    merged["nxt_stocks"] = data.get("nxt_stocks") or []
    return merged
```

- [ ] **Step 4: Create the example input file**

```json
{
  "date": "2026-08-05",
  "updated_at": "19:45",
  "overseas": {
    "sp500_futures_change_pct": 0.3,
    "nasdaq_futures_change_pct": 0.5,
    "sox_change_pct": -0.2,
    "kospi200_night_futures_change_pct": 0.1,
    "us_10y_yield_change_bp": -2.0,
    "hynix_adr_change_pct": 1.2,
    "samsung_adr_change_pct": 0.4
  },
  "events": {
    "major_event_tomorrow": false,
    "event_desc": "",
    "geopolitical_shock": false
  },
  "nxt_stocks": [
    {
      "code": "000660",
      "name": "SK하이닉스",
      "nxt_price": 250000,
      "nxt_change_pct": 4.5,
      "nxt_trade_value_eok": 120,
      "nxt_volume": 50000,
      "buy_sell_ratio": 1.4
    }
  ]
}
```

Save to `input/nxt_signals.example.json`.

- [ ] **Step 5: Update `.gitignore`**

Add a new line to `.gitignore`:
```
input/nxt_signals.json
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_input_loader.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add input_loader.py input/nxt_signals.example.json tests/test_input_loader.py .gitignore
git commit -m "feat: add NXT signals input file loader"
```

---

### Task 2: 해외 지표 자동 스크래핑 (`overseas.py`)

**Files:**
- Create: `overseas.py`
- Modify: `config.py` — add to `NAVER_URLS`:
  ```python
  "world_index": "https://finance.naver.com/world/",
  "market_index": "https://finance.naver.com/marketindex/",
  ```
- Test: `tests/test_overseas.py`

**Interfaces:**
- Consumes: `data_fetcher._fetch_html(url: str) -> str` (existing)
- Produces: `overseas.get_overseas_indices() -> dict` with keys
  `dow_change_pct`, `nasdaq_change_pct`, `sp500_change_pct`,
  `usd_krw_change_pct`, `wti_change_pct` (all `float | None`)

- [ ] **Step 1: Add URLs to config.py**

In `config.py`, inside the `NAVER_URLS` dict (after `"kosdaq_index"` entry), add:

```python
    "world_index": "https://finance.naver.com/world/",
    "market_index": "https://finance.naver.com/marketindex/",
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_overseas.py
import overseas

WORLD_HTML = """
<ul class="data_lst" id="worldIndexColumn1">
<li class="on"><dl>
<dt class="dt3"><a href="/world/sise.naver?symbol=DJI@DJI"><span class="blind">다우 산업</span></a></dt>
<dd class="point_status"><strong>14,578.54</strong><em>52.38</em><span><span>+</span>0.36%</span><span class="blind">상승</span></dd>
</dl></li>
</ul>
<ul class="data_lst" id="worldIndexColumn2">
<li class="on"><dl>
<dt class="dt3"><a href="/world/sise.naver?symbol=NAS@IXIC"><span class="blind">나스닥</span></a></dt>
<dd class="point_status"><strong>3,267.52</strong><em>11.00</em><span><span>-</span>0.34%</span><span class="blind">하락</span></dd>
</dl></li>
</ul>
<ul class="data_lst" id="worldIndexColumn3">
<li class="on"><dl>
<dt class="dt3"><a href="/world/sise.naver?symbol=SPI@SPX"><span class="blind">S&amp;P500</span></a></dt>
<dd class="point_status"><strong>1,569.19</strong><em>6.34</em><span><span>+</span>0.41%</span><span class="blind">상승</span></dd>
</dl></li>
</ul>
"""

MARKET_INDEX_HTML = """
<ul id="exchangeList">
<li class="on">
<a class="head usd" href="/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW">
<h3 class="h_lst"><span class="blind">미국 USD</span></h3>
<div class="head_info point_dn">
<span class="value">1,425.20</span><span class="change"> 5.80</span>
</div></a>
</li>
</ul>
<ul id="oilGoldList">
<li class="on">
<a class="head wti" href="/marketindex/worldOilDetail.naver?marketindexCd=OIL_CL&amp;fdtc=2">
<h3 class="h_lst"><span class="blind">WTI</span></h3>
<div class="head_info point_up">
<span class="value">75.77</span><span class="change">4.57</span>
</div></a>
</li>
</ul>
"""


def test_parse_world_indices_extracts_signed_pct():
    result = overseas._parse_world_indices(WORLD_HTML)
    assert result["DJI"] == 0.36
    assert result["NAS"] == -0.34
    assert result["SPI"] == 0.41


def test_parse_market_index_list_computes_signed_pct_from_class():
    fx = overseas._parse_market_index_list(MARKET_INDEX_HTML, "exchangeList")
    assert fx["FX_USDKRW"] < 0  # point_dn means the value fell

    oil = overseas._parse_market_index_list(MARKET_INDEX_HTML, "oilGoldList")
    assert oil["OIL_CL"] > 0  # point_up means the value rose


def test_get_overseas_indices_merges_all_sources(monkeypatch):
    def fake_fetch(url):
        if "world" in url:
            return WORLD_HTML
        return MARKET_INDEX_HTML

    monkeypatch.setattr(overseas, "_fetch_html", fake_fetch)
    result = overseas.get_overseas_indices()
    assert result["dow_change_pct"] == 0.36
    assert result["nasdaq_change_pct"] == -0.34
    assert result["sp500_change_pct"] == 0.41
    assert result["usd_krw_change_pct"] is not None
    assert result["wti_change_pct"] is not None


def test_get_overseas_indices_returns_none_fields_on_fetch_failure(monkeypatch):
    def raise_error(url):
        raise ConnectionError("boom")

    monkeypatch.setattr(overseas, "_fetch_html", raise_error)
    result = overseas.get_overseas_indices()
    assert result == {
        "dow_change_pct": None, "nasdaq_change_pct": None, "sp500_change_pct": None,
        "usd_krw_change_pct": None, "wti_change_pct": None,
    }
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_overseas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'overseas'`

- [ ] **Step 4: Implement `overseas.py`**

```python
import re

from bs4 import BeautifulSoup

from config import NAVER_URLS
from data_fetcher import _fetch_html


def _to_number(text: str) -> float:
    cleaned = text.replace(",", "").strip()
    if cleaned in ("", "-"):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_world_indices(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    out = {}
    for dl in soup.select("ul.data_lst dl"):
        a = dl.select_one("dt a")
        dd = dl.select_one("dd.point_status")
        if a is None or dd is None:
            continue
        href = a.get("href", "")
        m_symbol = re.search(r"symbol=(\w+)@", href)
        if not m_symbol:
            continue
        m_pct = re.search(r"([+-])\s*([\d,.]+)%", dd.get_text(" ", strip=True))
        if not m_pct:
            continue
        sign = -1 if m_pct.group(1) == "-" else 1
        out[m_symbol.group(1)] = sign * float(m_pct.group(2).replace(",", ""))
    return out


def _parse_market_index_list(html: str, list_id: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    out = {}
    for li in soup.select(f"#{list_id} li"):
        a = li.select_one("a.head")
        head_info = li.select_one("div.head_info")
        value_tag = li.select_one("span.value")
        change_tag = li.select_one("span.change")
        if a is None or head_info is None or value_tag is None or change_tag is None:
            continue
        m_code = re.search(r"marketindexCd=([A-Za-z0-9_]+)", a.get("href", ""))
        if not m_code:
            continue
        value = _to_number(value_tag.get_text())
        change = abs(_to_number(change_tag.get_text()))
        classes = head_info.get("class", [])
        sign = -1 if "point_dn" in classes else 1
        signed_change = change * sign
        prev = value - signed_change
        out[m_code.group(1)] = (signed_change / prev * 100) if prev else 0.0
    return out


def get_overseas_indices() -> dict:
    out = {"dow_change_pct": None, "nasdaq_change_pct": None, "sp500_change_pct": None,
           "usd_krw_change_pct": None, "wti_change_pct": None}
    try:
        idx = _parse_world_indices(_fetch_html(NAVER_URLS["world_index"]))
        out["dow_change_pct"] = idx.get("DJI")
        out["nasdaq_change_pct"] = idx.get("NAS")
        out["sp500_change_pct"] = idx.get("SPI")
    except Exception:
        pass
    try:
        html = _fetch_html(NAVER_URLS["market_index"])
        out["usd_krw_change_pct"] = _parse_market_index_list(html, "exchangeList").get("FX_USDKRW")
        out["wti_change_pct"] = _parse_market_index_list(html, "oilGoldList").get("OIL_CL")
    except Exception:
        pass
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_overseas.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add overseas.py config.py tests/test_overseas.py
git commit -m "feat: add automatic scraping of overseas indices, FX, and oil"
```

---

### Task 3: 무추천(veto) 판정 (`veto.py`)

**Files:**
- Create: `veto.py`
- Modify: `config.py` — add:
  ```python
  VETO_THRESHOLDS = {
      "night_futures_pct": -0.5,
      "sp500_futures_pct": -0.5,
      "fx_change_pct": 0.5,
      "sox_pct": -1.0,
      "kospi_close_pct": -1.5,
      "nxt_trade_value_ratio_pct": 50.0,
      "min_conditions": 2,
  }
  ```
- Test: `tests/test_veto.py`

**Interfaces:**
- Consumes: none (pure function)
- Produces: `veto.check_veto_conditions(overseas: dict, kospi_change_pct: float | None, events: dict, nxt_trade_value_ratio_pct: float | None) -> tuple[bool, list[str]]`

- [ ] **Step 1: Add `VETO_THRESHOLDS` to config.py**

Append to `config.py` (after `SCORE_WEIGHTS`):

```python
VETO_THRESHOLDS = {
    "night_futures_pct": -0.5,
    "sp500_futures_pct": -0.5,
    "fx_change_pct": 0.5,
    "sox_pct": -1.0,
    "kospi_close_pct": -1.5,
    "nxt_trade_value_ratio_pct": 50.0,
    "min_conditions": 2,
}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_veto.py
from veto import check_veto_conditions


def _overseas(**kwargs):
    base = {
        "kospi200_night_futures_change_pct": None,
        "sp500_futures_change_pct": None,
        "usd_krw_change_pct": None,
        "sox_change_pct": None,
    }
    base.update(kwargs)
    return base


def test_no_conditions_met_does_not_block():
    blocked, reasons = check_veto_conditions(
        _overseas(kospi200_night_futures_change_pct=0.1, sp500_futures_change_pct=0.2,
                   usd_krw_change_pct=0.1, sox_change_pct=0.3),
        kospi_change_pct=0.5, events={}, nxt_trade_value_ratio_pct=120.0,
    )
    assert blocked is False
    assert reasons == []


def test_single_condition_does_not_block():
    blocked, reasons = check_veto_conditions(
        _overseas(kospi200_night_futures_change_pct=-0.8),
        kospi_change_pct=0.5, events={}, nxt_trade_value_ratio_pct=120.0,
    )
    assert blocked is False
    assert len(reasons) == 1


def test_two_conditions_blocks():
    blocked, reasons = check_veto_conditions(
        _overseas(kospi200_night_futures_change_pct=-0.8, sp500_futures_change_pct=-0.6),
        kospi_change_pct=0.5, events={}, nxt_trade_value_ratio_pct=120.0,
    )
    assert blocked is True
    assert len(reasons) == 2


def test_missing_data_is_not_counted():
    blocked, reasons = check_veto_conditions(
        _overseas(),  # all None
        kospi_change_pct=None, events={}, nxt_trade_value_ratio_pct=None,
    )
    assert blocked is False
    assert reasons == []


def test_event_flags_trigger_conditions():
    blocked, reasons = check_veto_conditions(
        _overseas(), kospi_change_pct=None,
        events={"major_event_tomorrow": True, "geopolitical_shock": True},
        nxt_trade_value_ratio_pct=None,
    )
    assert blocked is True
    assert len(reasons) == 2


def test_nxt_trade_value_ratio_below_threshold_triggers():
    blocked, reasons = check_veto_conditions(
        _overseas(kospi200_night_futures_change_pct=-0.8), kospi_change_pct=None,
        events={}, nxt_trade_value_ratio_pct=30.0,
    )
    assert blocked is True
    assert len(reasons) == 2
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_veto.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'veto'`

- [ ] **Step 4: Implement `veto.py`**

```python
from config import VETO_THRESHOLDS


def check_veto_conditions(overseas: dict, kospi_change_pct: float | None,
                           events: dict, nxt_trade_value_ratio_pct: float | None
                           ) -> tuple[bool, list[str]]:
    t = VETO_THRESHOLDS
    conditions = []

    v = overseas.get("kospi200_night_futures_change_pct")
    conditions.append((None if v is None else v <= t["night_futures_pct"],
                        "코스피200 야간선물 -0.5% 이상 하락"))

    v = overseas.get("sp500_futures_change_pct")
    conditions.append((None if v is None else v <= t["sp500_futures_pct"],
                        "S&P500 선물 -0.5% 이상 하락"))

    v = overseas.get("usd_krw_change_pct")
    conditions.append((None if v is None else v >= t["fx_change_pct"],
                        "원/달러 환율 +0.5% 이상 급등"))

    v = overseas.get("sox_change_pct")
    conditions.append((None if v is None else v <= t["sox_pct"],
                        "필라델피아 반도체지수 선물 -1% 이상 하락"))

    conditions.append((None if kospi_change_pct is None else kospi_change_pct <= t["kospi_close_pct"],
                        "코스피 -1.5% 이상 하락 마감"))

    conditions.append((bool(events.get("major_event_tomorrow", False)),
                        "익일 주요 경제지표/FOMC 등 고변동성 이벤트 예정"))

    v = nxt_trade_value_ratio_pct
    conditions.append((None if v is None else v < t["nxt_trade_value_ratio_pct"],
                        "NXT 애프터마켓 거래대금 직전 5일 평균 대비 50% 미만"))

    conditions.append((bool(events.get("geopolitical_shock", False)),
                        "돌발 지정학적 악재"))

    reasons = [label for matched, label in conditions if matched]
    return len(reasons) >= t["min_conditions"], reasons
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_veto.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add veto.py config.py tests/test_veto.py
git commit -m "feat: add no-recommendation (veto) condition check"
```

---

### Task 4: NXT 하드 필터 (`filters.py`)

**Files:**
- Modify: `filters.py`
- Modify: `config.py` — add:
  ```python
  NXT_HARD_FILTERS = {"min_nxt_trade_ratio_pct": 3.0}
  ```
- Test: `tests/test_filters.py` (append)

**Interfaces:**
- Consumes: `config.HARD_FILTERS` (existing), `config.NXT_HARD_FILTERS` (new), `filters.is_etf_etn_spac` (existing)
- Produces: `filters.apply_nxt_trade_ratio_filter(nxt_trade_value_eok: float, daily_trade_value_eok: float) -> tuple[bool, str]`,
  `filters.apply_nxt_hard_filters(candidate: dict) -> tuple[bool, str]` where `candidate` has keys
  `name`, `daily_trade_value_eok`, `daily_change_pct`, `nxt_trade_value_eok`

- [ ] **Step 1: Add `NXT_HARD_FILTERS` to config.py**

Append after `HARD_FILTERS` in `config.py`:

```python
NXT_HARD_FILTERS = {"min_nxt_trade_ratio_pct": 3.0}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_filters.py`:

```python
from filters import apply_nxt_trade_ratio_filter, apply_nxt_hard_filters


def test_apply_nxt_trade_ratio_filter_passes_above_threshold():
    passed, reason = apply_nxt_trade_ratio_filter(nxt_trade_value_eok=30, daily_trade_value_eok=500)
    assert passed is True
    assert reason == ""


def test_apply_nxt_trade_ratio_filter_rejects_below_threshold():
    passed, reason = apply_nxt_trade_ratio_filter(nxt_trade_value_eok=5, daily_trade_value_eok=500)
    assert passed is False
    assert reason == "nxt_trade_ratio"


def test_apply_nxt_hard_filters_passes_valid_candidate():
    candidate = {"name": "SK하이닉스", "daily_trade_value_eok": 8500,
                 "daily_change_pct": 5.0, "nxt_trade_value_eok": 300}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is True
    assert reason == ""


def test_apply_nxt_hard_filters_rejects_etf_name():
    candidate = {"name": "KODEX 반도체", "daily_trade_value_eok": 8500,
                 "daily_change_pct": 5.0, "nxt_trade_value_eok": 300}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is False
    assert reason == "etf_etn_spac"


def test_apply_nxt_hard_filters_rejects_low_daily_trade_value():
    candidate = {"name": "종목", "daily_trade_value_eok": 100,
                 "daily_change_pct": 5.0, "nxt_trade_value_eok": 300}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is False
    assert reason == "trade_value"


def test_apply_nxt_hard_filters_rejects_limit_up():
    candidate = {"name": "종목", "daily_trade_value_eok": 8500,
                 "daily_change_pct": 29.5, "nxt_trade_value_eok": 300}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is False
    assert reason == "limit_up"


def test_apply_nxt_hard_filters_rejects_thin_nxt_trade_value():
    candidate = {"name": "종목", "daily_trade_value_eok": 8500,
                 "daily_change_pct": 5.0, "nxt_trade_value_eok": 5}
    passed, reason = apply_nxt_hard_filters(candidate)
    assert passed is False
    assert reason == "nxt_trade_ratio"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_filters.py -v`
Expected: FAIL with `ImportError: cannot import name 'apply_nxt_trade_ratio_filter'`

- [ ] **Step 4: Implement in `filters.py`**

Modify the import line at the top of `filters.py`:

```python
from config import EXCLUDED_NAME_KEYWORDS, HARD_FILTERS, NXT_HARD_FILTERS
```

Append at the end of `filters.py`:

```python
def apply_nxt_trade_ratio_filter(nxt_trade_value_eok: float, daily_trade_value_eok: float) -> tuple[bool, str]:
    if daily_trade_value_eok <= 0:
        return False, "daily_trade_value_zero"
    ratio_pct = nxt_trade_value_eok / daily_trade_value_eok * 100
    if ratio_pct < NXT_HARD_FILTERS["min_nxt_trade_ratio_pct"]:
        return False, "nxt_trade_ratio"
    return True, ""


def apply_nxt_hard_filters(candidate: dict) -> tuple[bool, str]:
    if is_etf_etn_spac(candidate["name"]):
        return False, "etf_etn_spac"
    if candidate["daily_trade_value_eok"] < HARD_FILTERS["min_trade_value_eok"]:
        return False, "trade_value"
    if candidate["daily_change_pct"] >= HARD_FILTERS["limit_up_pct"]:
        return False, "limit_up"
    return apply_nxt_trade_ratio_filter(
        candidate["nxt_trade_value_eok"], candidate["daily_trade_value_eok"]
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_filters.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 6: Commit**

```bash
git add filters.py config.py tests/test_filters.py
git commit -m "feat: add NXT-specific hard filters (trade value ratio, limit-up)"
```

---

### Task 5: NXT 매매 시나리오 (`risk_manager.py`)

**Files:**
- Modify: `risk_manager.py`
- Modify: `config.py` — add:
  ```python
  NXT_EXIT_RULES = {"tp1_pct": 4.0, "tp2_pct": 6.0, "no_chase_pct": 2.0}
  ```
- Test: `tests/test_risk_manager.py` (append)

**Interfaces:**
- Consumes: `config.STOP_LOSS` (existing, reused as-is: `tight_pct=2, max_pct=4, time_cut="10:00"`)
- Produces: `risk_manager.generate_nxt_exit_rules(nxt_price: float) -> dict` with keys
  `entry_target, no_chase_price, take_profit_1, take_profit_2, stop_loss_tight, stop_loss_max, time_cut, strategy, scenario_0900, scenario_0910, scenario_1000`
  (the first seven keys match the existing `generate_exit_rules()` output shape so `notifier.print_to_terminal`/`send_telegram` work unmodified)

- [ ] **Step 1: Add `NXT_EXIT_RULES` to config.py**

Append after `STOP_LOSS` in `config.py`:

```python
NXT_EXIT_RULES = {"tp1_pct": 4.0, "tp2_pct": 6.0, "no_chase_pct": 2.0}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_risk_manager.py`:

```python
from risk_manager import generate_nxt_exit_rules


def test_generate_nxt_exit_rules_computes_prices():
    rules = generate_nxt_exit_rules(250_000)
    assert rules["entry_target"] == 250_000
    assert rules["no_chase_price"] == round(250_000 * 1.02)
    assert rules["take_profit_1"] == round(250_000 * 1.04)
    assert rules["take_profit_2"] == round(250_000 * 1.06)
    assert rules["stop_loss_tight"] == round(250_000 * 0.98)
    assert rules["stop_loss_max"] == round(250_000 * 0.96)
    assert rules["time_cut"] == "10:00"


def test_generate_nxt_exit_rules_includes_scenarios():
    rules = generate_nxt_exit_rules(10_000)
    assert "scenario_0900" in rules
    assert "scenario_0910" in rules
    assert "scenario_1000" in rules
    assert "strategy" in rules
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_risk_manager.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_nxt_exit_rules'`

- [ ] **Step 4: Implement in `risk_manager.py`**

Modify the import line at the top of `risk_manager.py`:

```python
from config import EXIT_RULES, STOP_LOSS, NXT_EXIT_RULES
```

Append at the end of `risk_manager.py`:

```python
def generate_nxt_exit_rules(nxt_price: float) -> dict:
    w = NXT_EXIT_RULES
    return {
        "entry_target": round(nxt_price),
        "no_chase_price": round(nxt_price * (1 + w["no_chase_pct"] / 100)),
        "take_profit_1": round(nxt_price * (1 + w["tp1_pct"] / 100)),
        "take_profit_2": round(nxt_price * (1 + w["tp2_pct"] / 100)),
        "stop_loss_tight": round(nxt_price * (1 - STOP_LOSS["tight_pct"] / 100)),
        "stop_loss_max": round(nxt_price * (1 - STOP_LOSS["max_pct"] / 100)),
        "time_cut": STOP_LOSS["time_cut"],
        "strategy": "시초가 갭상승 +3%↑: 1차 익절 / 갭하락 시 5분 관망 후 -2% 진입 시 손절",
        "scenario_0900": "갭상승 +3%↑: 1차 익절 / 갭하락: 5분 관망 후 -2% 진입 시 손절",
        "scenario_0910": "고점 돌파 실패 시 절반 축소",
        "scenario_1000": "슈팅 없으면 전량 정리 (본절 또는 손절)",
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_risk_manager.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 6: Commit**

```bash
git add risk_manager.py config.py tests/test_risk_manager.py
git commit -m "feat: add NXT exit-rule scenario generator"
```

---

### Task 6: NXT 전용 점수화 (`scorer.py`)

**Files:**
- Modify: `scorer.py`
- Modify: `config.py` — add:
  ```python
  NXT_SCORE_WEIGHTS = {
      "nxt_flow": {"t1_pct": 5.0, "t1_pts": 25, "t2_pct": 3.0, "t2_pts": 20,
                   "t3_pct": 1.0, "t3_pts": 12, "t4_pts": 5,
                   "min_trade_value_eok": 1.0, "thin_pts": 2},
      "supply": {"both_pts": 20, "single_pts": 12, "flat_pts": 6, "sell_pts": 0},
      "theme": {"streak_pts": 20, "single_day_pts": 10, "none_pts": 0},
      "overseas": {"up_pts": 15, "flat_pts": 8, "down_pts": 0, "flat_band_pct": 0.2},
      "technical": {"breakout_pts": 15, "above_ma_pts": 8, "below_ma_pts": 0, "proximity_pct": 7.0},
      "gap": {"freq_high_pct": 60.0, "freq_high_pts": 5,
              "freq_mid_pct": 40.0, "freq_mid_pts": 3, "freq_low_pts": 0},
      "risk": {"night_futures_pts": -5, "fx_surge_pts": -5, "us_futures_pts": -5,
               "overheat_pts": -5, "cap": -20},
      "recommend_threshold": 70,
      "top_n": 5,
  }
  SECTOR_KEYWORDS = [
      {"keywords": ["하이닉스", "삼성전자", "반도체", "한미반도체"],
       "signal": "sox_change_pct", "label": "반도체(SOX)"},
      {"keywords": ["에너지솔루션", "에코프로", "포스코", "2차전지"],
       "signal": "nasdaq_futures_change_pct", "label": "2차전지(나스닥)"},
      {"keywords": ["에어로스페이스", "로템", "넥스원", "방산"],
       "signal": "sp500_futures_change_pct", "label": "방산(S&P500)"},
      {"keywords": ["이노베이션", "S-Oil", "GS"],
       "signal": "sp500_futures_change_pct", "label": "정유(S&P500)"},
  ]
  ```
- Test: `tests/test_scorer.py` (append)

**Interfaces:**
- Consumes: `pandas.DataFrame` with `open`/`close` columns (from `data_fetcher.get_stock_daily_data`), `ind` dict from `indicators.calculate_indicators` (existing keys: `ma5`, `ma20`, `week60_high_proximity_pct`), `investor_df` from `data_fetcher.get_investor_data`
- Produces: `scorer.calculate_nxt_score(candidate: dict, ind: dict, df, investor_df, overseas: dict, theme_streak_days: int) -> dict` returning `{"total": int, "breakdown": list[str]}`.
  `candidate` requires keys: `name`, `nxt_change_pct`, `nxt_trade_value_eok`, `close`, `daily_change_pct`.

- [ ] **Step 1: Add config additions**

Append the `NXT_SCORE_WEIGHTS` and `SECTOR_KEYWORDS` blocks shown above to `config.py` (after `SCORE_WEIGHTS`).

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_scorer.py`:

```python
from scorer import calculate_nxt_score, _gap_up_frequency_pct, _match_sector_signal


def _gap_df():
    # 6 rows -> 5 gap comparisons; opens all above previous close = 100% gap-up frequency
    return pd.DataFrame({
        "date": [f"2026-01-{i+1:02d}" for i in range(6)],
        "close": [100, 101, 102, 103, 104, 105],
        "open": [99, 101.5, 102.5, 103.5, 104.5, 105.5],
        "high": [101, 102, 103, 104, 105, 106],
        "low": [98, 100, 101, 102, 103, 104],
        "volume": [1_000_000] * 6,
    })


def test_gap_up_frequency_all_gap_ups():
    freq = _gap_up_frequency_pct(_gap_df())
    assert freq == 100.0


def test_gap_up_frequency_returns_none_with_insufficient_history():
    df = _gap_df().head(3)
    assert _gap_up_frequency_pct(df) is None


def test_match_sector_signal_finds_semiconductor_keyword():
    signal, label = _match_sector_signal("SK하이닉스", {"sox_change_pct": -1.2})
    assert signal == -1.2
    assert "SOX" in label


def test_match_sector_signal_falls_back_to_average():
    signal, label = _match_sector_signal(
        "알수없는종목", {"sp500_futures_change_pct": 0.4, "nasdaq_futures_change_pct": 0.2}
    )
    assert signal == 0.3
    assert "평균" in label


def test_match_sector_signal_returns_none_when_no_data():
    signal, label = _match_sector_signal("알수없는종목", {})
    assert signal is None


def test_calculate_nxt_score_full_breakdown():
    candidate = {"name": "SK하이닉스", "nxt_change_pct": 6.0, "nxt_trade_value_eok": 300,
                 "close": 250_000, "daily_change_pct": 5.0}
    ind = {"ma5": 240_000, "ma20": 230_000, "week60_high_proximity_pct": 3.0}
    investor_df = _investor_df([10, 10, 10], [10, 10, 10])
    overseas = {"sox_change_pct": 1.0, "kospi200_night_futures_change_pct": 0.2,
                "sp500_futures_change_pct": 0.3, "usd_krw_change_pct": 0.1}
    result = calculate_nxt_score(candidate, ind, _gap_df(), investor_df, overseas, theme_streak_days=2)
    assert result["total"] > 0
    assert any("NXT 상승률" in b for b in result["breakdown"])
    assert any("동반 순매수" in b for b in result["breakdown"])
    assert any("테마 지속" in b for b in result["breakdown"])


def test_calculate_nxt_score_applies_risk_penalty_and_caps():
    candidate = {"name": "알수없는종목", "nxt_change_pct": -2.0, "nxt_trade_value_eok": 0.1,
                 "close": 10_000, "daily_change_pct": 12.0}
    ind = {"ma5": 10_500, "ma20": 11_000, "week60_high_proximity_pct": 20.0}
    investor_df = _investor_df([-10], [-10])
    overseas = {"kospi200_night_futures_change_pct": -1.0, "usd_krw_change_pct": 1.0,
                "sp500_futures_change_pct": -1.0}
    result = calculate_nxt_score(candidate, ind, _gap_df().head(3), investor_df, overseas,
                                  theme_streak_days=0)
    risk_lines = [b for b in result["breakdown"] if "하락" in b or "급등" in b or "과다" in b]
    assert len(risk_lines) >= 3
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_scorer.py -v`
Expected: FAIL with `ImportError: cannot import name 'calculate_nxt_score'`

- [ ] **Step 4: Implement in `scorer.py`**

Modify the import line at the top of `scorer.py`:

```python
from config import SCORE_WEIGHTS, NXT_SCORE_WEIGHTS, SECTOR_KEYWORDS
```

Append at the end of `scorer.py`:

```python
def _score_nxt_flow(nxt_change_pct: float, nxt_trade_value_eok: float) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["nxt_flow"]
    if nxt_trade_value_eok < w["min_trade_value_eok"]:
        return w["thin_pts"], f"NXT 거래대금 부족 ({w['thin_pts']}점)"
    if nxt_change_pct >= w["t1_pct"]:
        return w["t1_pts"], f"NXT 상승률 {nxt_change_pct:.1f}% ({w['t1_pts']}점)"
    if nxt_change_pct >= w["t2_pct"]:
        return w["t2_pts"], f"NXT 상승률 {nxt_change_pct:.1f}% ({w['t2_pts']}점)"
    if nxt_change_pct >= w["t3_pct"]:
        return w["t3_pts"], f"NXT 상승률 {nxt_change_pct:.1f}% ({w['t3_pts']}점)"
    if nxt_change_pct >= 0:
        return w["t4_pts"], f"NXT 상승률 {nxt_change_pct:.1f}% ({w['t4_pts']}점)"
    return 0, f"NXT 하락 {nxt_change_pct:.1f}% (0점)"


def _score_nxt_supply(investor_df) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["supply"]
    if investor_df is None or len(investor_df) == 0:
        return 0, "수급 데이터 없음 (0점)"
    last_foreign = investor_df["foreign_net"].iloc[-1]
    last_inst = investor_df["inst_net"].iloc[-1]
    foreign_buy = last_foreign > 0
    inst_buy = last_inst > 0
    if foreign_buy and inst_buy:
        return w["both_pts"], f"외국인+기관 동반 순매수 ({w['both_pts']}점)"
    if foreign_buy or inst_buy:
        return w["single_pts"], f"단일 순매수 ({w['single_pts']}점)"
    if last_foreign == 0 and last_inst == 0:
        return w["flat_pts"], f"수급 보합 ({w['flat_pts']}점)"
    return w["sell_pts"], "순매도 (0점)"


def _score_nxt_theme(streak_days: int) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["theme"]
    if streak_days >= 2:
        return w["streak_pts"], f"테마 지속 {streak_days}일차 ({w['streak_pts']}점)"
    if streak_days == 1:
        return w["single_day_pts"], f"당일 발생 테마 ({w['single_day_pts']}점)"
    return w["none_pts"], "테마 연속성 없음 (0점)"


def _match_sector_signal(name: str, overseas: dict) -> tuple[float | None, str]:
    for entry in SECTOR_KEYWORDS:
        if any(kw in name for kw in entry["keywords"]):
            return overseas.get(entry["signal"]), entry["label"]
    sp = overseas.get("sp500_futures_change_pct")
    nq = overseas.get("nasdaq_futures_change_pct")
    vals = [v for v in (sp, nq) if v is not None]
    if vals:
        return sum(vals) / len(vals), "S&P/나스닥 평균"
    return None, "매칭 실패"


def _score_nxt_overseas(name: str, overseas: dict) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["overseas"]
    signal, label = _match_sector_signal(name, overseas)
    if signal is None:
        return 0, f"해외 선행 신호 데이터 부족 ({label}) (0점)"
    if signal > w["flat_band_pct"]:
        return w["up_pts"], f"해외 선행 신호 상승 ({label} {signal:+.2f}%) ({w['up_pts']}점)"
    if signal >= -w["flat_band_pct"]:
        return w["flat_pts"], f"해외 선행 신호 보합 ({label} {signal:+.2f}%) ({w['flat_pts']}점)"
    return w["down_pts"], f"해외 선행 신호 하락 ({label} {signal:+.2f}%) (0점)"


def _score_nxt_technical(ind: dict, close: float) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["technical"]
    if ind["week60_high_proximity_pct"] <= w["proximity_pct"]:
        return w["breakout_pts"], f"전고점 근접/돌파 임박 ({w['breakout_pts']}점)"
    if close > ind["ma5"]:
        return w["above_ma_pts"], f"5일선 위 ({w['above_ma_pts']}점)"
    return w["below_ma_pts"], "이평선 하단 (0점)"


def _gap_up_frequency_pct(df) -> float | None:
    if len(df) < 6:
        return None
    tail = df.tail(6).reset_index(drop=True)
    ups = sum(
        1 for i in range(1, len(tail))
        if tail.loc[i, "open"] > tail.loc[i - 1, "close"]
    )
    return ups / (len(tail) - 1) * 100


def _score_nxt_gap(df) -> tuple[int, str]:
    w = NXT_SCORE_WEIGHTS["gap"]
    freq = _gap_up_frequency_pct(df)
    if freq is None:
        return 0, "갭상승 빈도 데이터 부족 (0점)"
    if freq >= w["freq_high_pct"]:
        return w["freq_high_pts"], f"갭상승 빈도 {freq:.0f}% ({w['freq_high_pts']}점)"
    if freq >= w["freq_mid_pct"]:
        return w["freq_mid_pts"], f"갭상승 빈도 {freq:.0f}% ({w['freq_mid_pts']}점)"
    return w["freq_low_pts"], f"갭상승 빈도 {freq:.0f}% (0점)"


def _score_nxt_risk(overseas: dict, daily_change_pct: float) -> tuple[int, list[str]]:
    w = NXT_SCORE_WEIGHTS["risk"]
    pts, notes = 0, []
    night = overseas.get("kospi200_night_futures_change_pct")
    if night is not None and night < 0:
        pts += w["night_futures_pts"]
        notes.append(f"야간선물 하락 ({w['night_futures_pts']}점)")
    fx = overseas.get("usd_krw_change_pct")
    if fx is not None and fx >= 1.0:
        pts += w["fx_surge_pts"]
        notes.append(f"환율 급등 ({w['fx_surge_pts']}점)")
    sp = overseas.get("sp500_futures_change_pct")
    if sp is not None and sp < 0:
        pts += w["us_futures_pts"]
        notes.append(f"미국 선물 하락 ({w['us_futures_pts']}점)")
    if daily_change_pct is not None and daily_change_pct >= 10.0:
        pts += w["overheat_pts"]
        notes.append(f"당일 상승률 과다 ({w['overheat_pts']}점)")
    return max(pts, w["cap"]), notes


def calculate_nxt_score(candidate: dict, ind: dict, df, investor_df,
                         overseas: dict, theme_streak_days: int) -> dict:
    breakdown = []
    total = 0

    pts, note = _score_nxt_flow(candidate["nxt_change_pct"], candidate["nxt_trade_value_eok"])
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_supply(investor_df)
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_theme(theme_streak_days)
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_overseas(candidate["name"], overseas)
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_technical(ind, candidate["close"])
    total += pts
    breakdown.append(note)

    pts, note = _score_nxt_gap(df)
    total += pts
    breakdown.append(note)

    pts, notes = _score_nxt_risk(overseas, candidate["daily_change_pct"])
    total += pts
    breakdown.extend(notes)

    return {"total": total, "breakdown": breakdown}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_scorer.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 6: Commit**

```bash
git add scorer.py config.py tests/test_scorer.py
git commit -m "feat: add NXT-specific scoring model (A-G weights)"
```

---

### Task 7: NXT 파이프라인 통합 (`recommender.py`)

**Files:**
- Modify: `recommender.py`
- Test: `tests/test_recommender.py` (append)

**Interfaces:**
- Consumes: `input_loader.load_nxt_signals()`, `overseas.get_overseas_indices()`,
  `veto.check_veto_conditions()`, `filters.apply_nxt_hard_filters()`,
  `scorer.calculate_nxt_score()`, `risk_manager.generate_nxt_exit_rules()`,
  `data_fetcher.get_stock_daily_data`, `data_fetcher.get_investor_data`,
  `data_fetcher.get_market_index`, `indicators.calculate_indicators`, `indicators.detect_pattern`
- Produces: `recommender.run_nxt_analysis() -> dict` (same top-level shape as the
  existing `run_analysis()` result: `date, time, session, session_label, market, picks`,
  plus `nxt_total_trade_value_eok`, `veto_blocked`, `veto_reasons`).
  `recommender.run_analysis(session="nxt")` now dispatches to `run_nxt_analysis()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_recommender.py`:

```python
import json
import os
from datetime import datetime

import input_loader
import overseas
import veto


def _fake_gap_daily_df():
    closes = [90] * 55 + [95, 96, 97, 98, 100, 101]
    opens = [c * 0.99 for c in closes]
    return pd.DataFrame({
        "date": [f"2026-01-{i+1:02d}" for i in range(61)],
        "close": closes,
        "open": opens,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.96 for c in closes],
        "volume": [1_000_000] * 61,
    })


def _stub_common(monkeypatch):
    monkeypatch.setattr(recommender.data_fetcher, "get_stock_daily_data",
                         lambda code, days_needed=60: _fake_gap_daily_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_investor_data",
                         lambda code, days_needed=5: _fake_investor_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_market_index",
                         lambda: {"kospi": {"index": 2800.0, "change_pct": 0.3},
                                   "kosdaq": {"index": 850.0, "change_pct": 0.1}})
    monkeypatch.setattr(recommender.overseas, "get_overseas_indices",
                         lambda: {"dow_change_pct": 0.2, "nasdaq_change_pct": 0.3,
                                   "sp500_change_pct": 0.1, "usd_krw_change_pct": 0.1,
                                   "wti_change_pct": 0.1})


def test_run_nxt_analysis_blocks_on_veto(monkeypatch, tmp_path):
    _stub_common(monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")
    input_path = tmp_path / "nxt_signals.json"
    input_path.write_text(json.dumps({
        "date": today,
        "overseas": {"kospi200_night_futures_change_pct": -1.0, "sp500_futures_change_pct": -1.0},
        "events": {}, "nxt_stocks": [{"code": "000660", "name": "SK하이닉스",
                                       "nxt_price": 100, "nxt_change_pct": 5.0,
                                       "nxt_trade_value_eok": 300}],
    }), encoding="utf-8")
    monkeypatch.setattr(recommender.input_loader, "DEFAULT_PATH", str(input_path))
    monkeypatch.setattr(recommender, "_load_recent_nxt_totals", lambda max_days=5: [])

    result = recommender.run_analysis(session="nxt")
    assert result["veto_blocked"] is True
    assert result["picks"] == []
    assert len(result["veto_reasons"]) >= 2


def test_run_nxt_analysis_returns_no_recommendation_when_no_stocks(monkeypatch, tmp_path):
    _stub_common(monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")
    input_path = tmp_path / "nxt_signals.json"
    input_path.write_text(json.dumps({"date": today, "overseas": {}, "events": {},
                                        "nxt_stocks": []}), encoding="utf-8")
    monkeypatch.setattr(recommender.input_loader, "DEFAULT_PATH", str(input_path))
    monkeypatch.setattr(recommender, "_load_recent_nxt_totals", lambda max_days=5: [])

    result = recommender.run_analysis(session="nxt")
    assert result["picks"] == []
    assert result["veto_blocked"] is False


def test_run_nxt_analysis_produces_ranked_picks(monkeypatch, tmp_path):
    _stub_common(monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")
    input_path = tmp_path / "nxt_signals.json"
    input_path.write_text(json.dumps({
        "date": today,
        "overseas": {"sox_change_pct": 1.0, "kospi200_night_futures_change_pct": 0.2,
                      "sp500_futures_change_pct": 0.3, "usd_krw_change_pct": 0.1},
        "events": {},
        "nxt_stocks": [{"code": "000660", "name": "SK하이닉스", "nxt_price": 250000,
                         "nxt_change_pct": 6.0, "nxt_trade_value_eok": 300,
                         "nxt_volume": 1000, "buy_sell_ratio": 1.4}],
    }), encoding="utf-8")
    monkeypatch.setattr(recommender.input_loader, "DEFAULT_PATH", str(input_path))
    monkeypatch.setattr(recommender, "_load_recent_nxt_totals", lambda max_days=5: [])
    monkeypatch.setattr(recommender, "_nxt_theme_streak", lambda code, max_days=5: 2)

    result = recommender.run_analysis(session="nxt")
    assert result["session"] == "nxt"
    if result["picks"]:
        pick = result["picks"][0]
        assert pick["code"] == "000660"
        assert pick["rank"] == 1
        assert "exit_rules" in pick
        assert "entry_target" in pick["exit_rules"]


def test_nxt_theme_streak_counts_consecutive_recent_days(tmp_path, monkeypatch):
    monkeypatch.setattr(recommender, "OUTPUT_DIR", str(tmp_path))
    for i, day in enumerate(["20260801", "20260802", "20260803"]):
        with open(os.path.join(str(tmp_path), f"{day}_nxt.json"), "w", encoding="utf-8") as f:
            json.dump({"picks": [{"code": "000660"}]}, f)
    streak = recommender._nxt_theme_streak("000660")
    assert streak == 3


def test_nxt_theme_streak_stops_at_first_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(recommender, "OUTPUT_DIR", str(tmp_path))
    with open(os.path.join(str(tmp_path), "20260801_nxt.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": [{"code": "000660"}]}, f)
    with open(os.path.join(str(tmp_path), "20260802_nxt.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": []}, f)
    with open(os.path.join(str(tmp_path), "20260803_nxt.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": [{"code": "000660"}]}, f)
    streak = recommender._nxt_theme_streak("000660")
    assert streak == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_recommender.py -v`
Expected: FAIL with `AttributeError: module 'recommender' has no attribute 'input_loader'` (or similar)

- [ ] **Step 3: Implement in `recommender.py`**

Modify the imports at the top of `recommender.py`:

```python
import json
import os
from datetime import datetime

import data_fetcher
import filters
import indicators
import input_loader
import overseas
import veto
from scorer import calculate_score, calculate_nxt_score
from risk_manager import generate_exit_rules, generate_nxt_exit_rules
from config import SCORE_WEIGHTS, NXT_SCORE_WEIGHTS
```

Add `"nxt": "넥스트레이드(NXT) 애프터마켓 마감"` is already covered by the existing
`SESSION_LABELS["nxt"]` entry — no change needed there.

Append these new functions to `recommender.py` (after the existing `_load_prev_top_codes`
function, before `_evaluate_candidate`):

```python
def _nxt_theme_streak(code: str, max_days: int = 5) -> int:
    if not os.path.isdir(OUTPUT_DIR):
        return 0
    files = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith("_nxt.json"))
    streak = 0
    for filename in reversed(files[-max_days:]):
        try:
            with open(os.path.join(OUTPUT_DIR, filename), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            break
        codes = {p["code"] for p in data.get("picks", [])}
        if code in codes:
            streak += 1
        else:
            break
    return streak


def _load_recent_nxt_totals(max_days: int = 5) -> list[float]:
    if not os.path.isdir(OUTPUT_DIR):
        return []
    files = sorted(f for f in os.listdir(OUTPUT_DIR) if f.endswith("_nxt.json"))
    totals = []
    for filename in files[-max_days:]:
        try:
            with open(os.path.join(OUTPUT_DIR, filename), encoding="utf-8") as f:
                data = json.load(f)
            total = data.get("nxt_total_trade_value_eok")
            if total is not None:
                totals.append(total)
        except Exception:
            continue
    return totals


def _evaluate_nxt_candidate(stock: dict, overseas_signals: dict):
    try:
        df = data_fetcher.get_stock_daily_data(stock["code"], days_needed=60)
        if len(df) < 20:
            return None
        investor_df = data_fetcher.get_investor_data(stock["code"], days_needed=5)
    except Exception:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    daily_change_pct = ((last["close"] - prev["close"]) / prev["close"] * 100
                         if prev["close"] else 0.0)
    daily_trade_value_eok = last["volume"] * last["close"] / 1e8

    candidate = {
        "name": stock["name"],
        "nxt_change_pct": stock.get("nxt_change_pct", 0),
        "nxt_trade_value_eok": stock.get("nxt_trade_value_eok", 0),
        "close": last["close"],
        "daily_change_pct": daily_change_pct,
        "daily_trade_value_eok": daily_trade_value_eok,
    }

    hard_pass, _ = filters.apply_nxt_hard_filters(candidate)
    if not hard_pass:
        return None

    ind = indicators.calculate_indicators(df)
    pattern = indicators.detect_pattern(df, ind)
    streak_days = _nxt_theme_streak(stock["code"])

    score_result = calculate_nxt_score(candidate, ind, df, investor_df, overseas_signals, streak_days)
    nxt_price = stock.get("nxt_price", last["close"])
    exit_rules = generate_nxt_exit_rules(nxt_price)

    return {
        "code": stock["code"],
        "name": stock["name"],
        "market": "NXT",
        "current_price": nxt_price,
        "daily_return": daily_change_pct,
        "trade_value_yuk": daily_trade_value_eok,
        "nxt_change_pct": candidate["nxt_change_pct"],
        "nxt_trade_value_yuk": candidate["nxt_trade_value_eok"],
        "pattern": pattern,
        "score": score_result["total"],
        "details": score_result["breakdown"],
        "exit_rules": exit_rules,
        "passed_threshold": score_result["total"] >= NXT_SCORE_WEIGHTS["recommend_threshold"],
    }


def run_nxt_analysis() -> dict:
    input_data = input_loader.load_nxt_signals(path=input_loader.DEFAULT_PATH)
    market_index = data_fetcher.get_market_index()
    kospi_change_pct = market_index.get("kospi", {}).get("change_pct")

    recent_totals = _load_recent_nxt_totals()
    today_total = sum(s.get("nxt_trade_value_eok", 0) for s in input_data["nxt_stocks"])
    nxt_trade_value_ratio_pct = None
    if len(recent_totals) >= 5:
        avg = sum(recent_totals) / len(recent_totals)
        nxt_trade_value_ratio_pct = (today_total / avg * 100) if avg else None

    overseas_signals = {**overseas.get_overseas_indices(), **input_data["overseas"]}

    blocked, veto_reasons = veto.check_veto_conditions(
        overseas_signals, kospi_change_pct, input_data["events"], nxt_trade_value_ratio_pct
    )

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "session": "nxt",
        "session_label": SESSION_LABELS.get("nxt", "nxt"),
        "market": {
            "kospi": market_index.get("kospi", {"index": None, "change_pct": None}),
            "kosdaq": market_index.get("kosdaq", {"index": None, "change_pct": None}),
            "overseas": overseas_signals,
        },
        "nxt_total_trade_value_eok": today_total,
        "veto_blocked": blocked,
        "veto_reasons": veto_reasons,
        "picks": [],
    }

    if blocked or not input_data["nxt_stocks"]:
        return result

    picks = []
    for stock in input_data["nxt_stocks"]:
        try:
            pick = _evaluate_nxt_candidate(stock, overseas_signals)
        except Exception:
            pick = None
        if pick is not None:
            picks.append(pick)

    picks.sort(key=lambda p: p["score"], reverse=True)
    top_picks = [p for p in picks if p["passed_threshold"]][:NXT_SCORE_WEIGHTS["top_n"]]
    for i, pick in enumerate(top_picks, start=1):
        pick["rank"] = i
        del pick["passed_threshold"]

    result["picks"] = top_picks
    return result
```

Modify `run_analysis()` to dispatch to the new function — replace its first line:

```python
def run_analysis(session: str = "close") -> dict:
    if session == "nxt":
        return run_nxt_analysis()
    prev_top_codes = _load_prev_top_codes()
    ...  # rest unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_recommender.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add recommender.py tests/test_recommender.py
git commit -m "feat: wire up NXT session pipeline (veto, scoring, ranking)"
```

---

### Task 8: NXT 리포트 출력 (`notifier.py`)

**Files:**
- Modify: `notifier.py`
- Test: `tests/test_notifier.py` (append)

**Interfaces:**
- Consumes: `result` dict shape produced by `recommender.run_nxt_analysis()`
- Produces: `notifier.format_nxt_report(result: dict) -> str`,
  `notifier.save_nxt_markdown(result: dict) -> str`.
  `notifier.notify(result)` now also calls `save_nxt_markdown` when `result["session"] == "nxt"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notifier.py`:

```python
NXT_SAMPLE_RESULT = {
    "date": "2026-08-05", "time": "19:50", "session": "nxt",
    "session_label": "넥스트레이드(NXT) 애프터마켓 마감",
    "market": {
        "kospi": {"index": 2800.0, "change_pct": 0.3},
        "kosdaq": {"index": 850.0, "change_pct": 0.1},
        "overseas": {"sp500_change_pct": 0.2, "nasdaq_change_pct": 0.3,
                     "sp500_futures_change_pct": None, "nasdaq_futures_change_pct": None,
                     "sox_change_pct": -0.5, "kospi200_night_futures_change_pct": 0.1,
                     "hynix_adr_change_pct": None, "samsung_adr_change_pct": None,
                     "us_10y_yield_change_bp": None, "usd_krw_change_pct": 0.1,
                     "wti_change_pct": 0.2},
    },
    "nxt_total_trade_value_eok": 4500,
    "veto_blocked": False,
    "veto_reasons": [],
    "picks": [{
        "rank": 1, "code": "000660", "name": "SK하이닉스", "market": "NXT",
        "current_price": 250000, "daily_return": 5.0, "trade_value_yuk": 8500,
        "nxt_change_pct": 6.0, "nxt_trade_value_yuk": 300,
        "pattern": "신고가", "score": 87, "details": ["NXT 상승률 6.0% (25점)"],
        "exit_rules": {"entry_target": 250000, "no_chase_price": 255000,
                        "take_profit_1": 260000, "take_profit_2": 265000,
                        "stop_loss_tight": 245000, "stop_loss_max": 240000,
                        "time_cut": "10:00", "strategy": "시초가 갭상승 시 익절",
                        "scenario_0900": "갭상승 시 1차 익절", "scenario_0910": "고점 돌파 실패 시 축소",
                        "scenario_1000": "슈팅 없으면 정리"},
    }],
}

NXT_BLOCKED_RESULT = {
    "date": "2026-08-05", "time": "19:50", "session": "nxt",
    "session_label": "넥스트레이드(NXT) 애프터마켓 마감",
    "market": {"kospi": {"index": 2700.0, "change_pct": -1.8},
               "kosdaq": {"index": 800.0, "change_pct": -1.5},
               "overseas": {}},
    "nxt_total_trade_value_eok": None,
    "veto_blocked": True,
    "veto_reasons": ["코스피 -1.5% 이상 하락 마감", "S&P500 선물 -0.5% 이상 하락"],
    "picks": [],
}


def test_format_nxt_report_includes_pick_and_scenario():
    text = notifier.format_nxt_report(NXT_SAMPLE_RESULT)
    assert "SK하이닉스" in text
    assert "87" in text
    assert "250,000" in text or "260,000" in text
    assert "고점 돌파 실패" in text


def test_format_nxt_report_shows_no_recommendation_reasons():
    text = notifier.format_nxt_report(NXT_BLOCKED_RESULT)
    assert "오늘은 추천 없음" in text
    assert "코스피 -1.5% 이상 하락 마감" in text


def test_save_nxt_markdown_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(notifier, "OUTPUT_DIR", str(tmp_path))
    path = notifier.save_nxt_markdown(NXT_SAMPLE_RESULT)
    assert os.path.exists(path)
    assert path.endswith("_nxt.md")


def test_notify_saves_markdown_for_nxt_session(tmp_path, monkeypatch):
    monkeypatch.setattr(notifier, "OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(notifier, "TELEGRAM_BOT_TOKEN", None)
    monkeypatch.setattr(notifier, "TELEGRAM_CHAT_ID", None)
    notifier.notify(NXT_SAMPLE_RESULT)
    files = os.listdir(str(tmp_path))
    assert any(f.endswith("_nxt.md") for f in files)
    assert any(f.endswith(".json") for f in files)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_notifier.py -v`
Expected: FAIL with `AttributeError: module 'notifier' has no attribute 'format_nxt_report'`

- [ ] **Step 3: Implement in `notifier.py`**

Append at the end of `notifier.py` (before the existing `notify` function), and modify
`notify` as shown:

```python
def format_nxt_report(result: dict) -> str:
    lines = [f"# {result['date']} NXT 종가베팅 추천 리포트", f"## 발행 시각: {result['time']} KST", ""]

    overseas_data = result["market"].get("overseas", {})
    lines.append("## 1. 시장 요약")
    lines.append("")
    lines.append("### 해외 선행 신호")
    lines.append("| 지표 | 등락률 |")
    lines.append("|---|---|")
    fields = [
        ("S&P500 지수", "sp500_change_pct"), ("나스닥 지수", "nasdaq_change_pct"),
        ("다우 지수", "dow_change_pct"),
        ("S&P500 선물", "sp500_futures_change_pct"), ("나스닥100 선물", "nasdaq_futures_change_pct"),
        ("SOX(반도체) 선물", "sox_change_pct"), ("코스피200 야간선물", "kospi200_night_futures_change_pct"),
        ("SK하이닉스 ADR", "hynix_adr_change_pct"), ("삼성전자 ADR", "samsung_adr_change_pct"),
        ("미국 10년물 금리(bp)", "us_10y_yield_change_bp"),
        ("원/달러 환율", "usd_krw_change_pct"), ("WTI 유가", "wti_change_pct"),
    ]
    for label, key in fields:
        value = overseas_data.get(key)
        display = "데이터 부족" if value is None else f"{value:+.2f}%"
        lines.append(f"| {label} | {display} |")
    lines.append("")

    kospi = result["market"]["kospi"]
    kosdaq = result["market"]["kosdaq"]
    lines.append("### 코스피/코스닥")
    lines.append(f"- 코스피: {kospi.get('change_pct')}% / 코스닥: {kosdaq.get('change_pct')}%")
    lines.append("")

    total = result.get("nxt_total_trade_value_eok")
    lines.append("### NXT 애프터마켓 요약")
    lines.append(f"- 총 거래대금: {total if total is not None else '데이터 부족'}억원")
    lines.append("")

    lines.append("## 2. 추천 종목")
    lines.append("")
    if result.get("veto_blocked") or not result["picks"]:
        lines.append("**오늘은 추천 없음**")
        lines.append("")
        if result.get("veto_reasons"):
            lines.append("무추천 사유:")
            for reason in result["veto_reasons"]:
                lines.append(f"- {reason}")
            lines.append("")
    else:
        for pick in result["picks"]:
            lines.append(f"### 종목 {pick['rank']}: {pick['name']} ({pick['code']}) - {pick['score']}점")
            lines.append("")
            lines.append(f"- NXT가: {pick['current_price']:,.0f}원 (NXT 등락률 {pick['nxt_change_pct']:+.2f}%)")
            lines.append(f"- NXT 거래대금: {pick['nxt_trade_value_yuk']:.0f}억")
            lines.append(f"- 당일 KRX 등락률: {pick['daily_return']:+.2f}%")
            lines.append("")
            lines.append("**매수 근거:**")
            for detail in pick["details"]:
                lines.append(f"- {detail}")
            lines.append("")
            er = pick["exit_rules"]
            lines.append("**매매 시나리오:**")
            lines.append(f"- 진입 타겟가: {er['entry_target']:,}원")
            lines.append(f"- 추격 금지가: {er['no_chase_price']:,}원")
            lines.append(f"- 1차 익절: {er['take_profit_1']:,}원 / 2차 익절: {er['take_profit_2']:,}원")
            lines.append(f"- 손절: 타이트 {er['stop_loss_tight']:,}원 / 마지노선 {er['stop_loss_max']:,}원")
            lines.append(f"- 09:00 시나리오: {er['scenario_0900']}")
            lines.append(f"- 09:10 시나리오: {er['scenario_0910']}")
            lines.append(f"- 10:00 시간컷: {er['scenario_1000']}")
            lines.append("")

    lines.append("## 3. 주의사항")
    lines.append("")
    lines.append("### 익일 대응 체크리스트")
    for item in [
        "미국 본장 개장 후 선물 방향 재확인",
        "한국 연동 섹터(반도체, AI, 방산 등) 흐름 확인",
        "익일 NXT 프리마켓 방향 확인",
        "시가 단일가 확인 후 최종 매도 여부 결정",
    ]:
        lines.append(f"- [ ] {item}")
    lines.append("")
    lines.append("### 손절 원칙")
    lines.append("1. -4% 손절: 매수가 대비 -4% 도달 시 즉시 시장가 매도")
    lines.append("2. 10:00 시간컷: 슈팅 미출현 시 전량 정리")
    lines.append("3. 신규 악재 시 칼손절: 시초가 시장가 즉시 매도")
    lines.append("")
    lines.append("### 면책")
    lines.append(
        "본 리포트는 데이터 기반 분석 결과이며, 투자를 권유하는 것이 아닙니다. "
        "모든 투자의 최종 판단과 책임은 투자자 본인에게 있습니다."
    )
    return "\n".join(lines)


def save_nxt_markdown(result: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = f"{result['date'].replace('-', '')}_nxt.md"
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(format_nxt_report(result))
    return path


def notify(result: dict) -> None:
    print_to_terminal(result)
    save_json(result)
    if result.get("session") == "nxt":
        save_nxt_markdown(result)
    send_telegram(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_notifier.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add notifier.py tests/test_notifier.py
git commit -m "feat: add NXT markdown report generation and saving"
```

---

## Final Verification

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: All tests PASS (existing `close`-session tests untouched and still green,
plus all new NXT tests)

- [ ] **Step 2: Manual smoke test with the example input file**

```bash
cp input/nxt_signals.example.json input/nxt_signals.json
python -c "
import json, input_loader
data = input_loader.load_nxt_signals(today=json.load(open('input/nxt_signals.json'))['date'])
print(data)
"
```

Confirm the printed dict reflects the example file's contents (this validates the
file path wiring end-to-end without hitting the network). Note: a full
`run_daily.py nxt` smoke test will hit live Naver endpoints and real stock codes —
run it manually only when ready to validate against production data, with today's
date in `input/nxt_signals.json`.
