# KiwoomProvider — 키움증권 OpenAPI+ (모의투자) 브릿지 연동 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `python main.py --provider kiwoom` path that fetches live KOSPI/KOSDAQ market data from a local `kiwoom_bridge` process (which wraps 키움증권 OpenAPI+ via win32com in a 32-bit Python environment), without touching the existing `--provider real` (KIS) or `--provider mock` paths.

**Architecture:** Two processes. `kiwoom_bridge/` (new, 32-bit Python + pywin32 only) owns the OpenAPI+ COM object, pumps the Windows message loop, and exposes a tiny localhost-only HTTP API (stdlib `http.server`, no new pip dependency) that returns a clean, already-normalized JSON schema. `leader_watch/providers/kiwoom/` (new subpackage, runs in the existing 64-bit venv) is a thin `requests`-based HTTP client + pure mapping functions, structurally identical to `leader_watch/providers/kis/`. `leader_watch/providers/kiwoom_provider.py` is the orchestrator, reusing the exact caching/staleness/bounded-minute-bar-window policy already implemented (and hardened via final review) in `leader_watch/providers/real.py`.

**Tech Stack:** Python 3.14 (main app, 64-bit), Python 3.x 32-bit + pywin32 (bridge only, not exercised by this repo's test suite), pytest, `requests`, stdlib `http.server`/`urllib.parse`/`threading`.

## Global Constraints

- Never write order/buy/sell/account-balance code. Only read-only Kiwoom market-data TRs (ranking, sector ranking, quote, minute bars) are used, exposed through the bridge.
- Do not modify: `leader_watch/providers/base.py`, `leader_watch/engine.py` (reuse `call_with_retry` via import only — no edits), `leader_watch/state_machine.py`, `leader_watch/scoring.py`, `leader_watch/filters.py`, `leader_watch/models.py`, `leader_watch/providers/mock.py`, `leader_watch/providers/mock_scenarios.py`, `leader_watch/providers/real.py`, or anything under `leader_watch/providers/kis/`. The existing KIS integration must keep working unchanged.
- Do not modify repo-root `recommender.py`, `scorer.py`, `filters.py`, `notifier.py`, `scheduler.py`, `data_fetcher.py`.
- All raw Kiwoom TR codes/field-name assumptions live ONLY in `kiwoom_bridge/tr_client.py`, each as a named constant with an `ASSUMPTION` comment — the bridge normalizes them into the clean JSON schema in this plan before `leader_watch/providers/kiwoom/mapping.py` ever sees them, so that file carries no broker-specific guesses.
- Every `StockSnapshot` returned by `KiwoomProvider` must carry a real `timestamp` reflecting when the data was actually received/observed (or, if no better field exists, be explicitly documented as an accepted structural limitation — same honest standard applied to `RealProvider`) — never a silently-wrong placeholder.
- Every automated test in this plan must pass with zero real network access, zero real bridge process, and zero win32com/COM dependency — all HTTP calls to the bridge are mocked at the `requests` boundary; `kiwoom_bridge/http_server.py`'s routing logic is tested via direct function calls with a fake TR client, never a real socket. The two files that transitively import `win32com` (`kiwoom_bridge/tr_client.py`, `kiwoom_bridge/bridge.py`) are NOT unit tested in this repo — they are verified by hand per `kiwoom_bridge/README.md`'s manual protocol, and this plan only requires a syntax compile-check (`python -m py_compile`) for them, which does not require win32com to be installed.
- `KiwoomProvider()` must remain callable with zero constructor arguments in the common case (reading all configuration from environment variables via `load_kiwoom_config()`), matching how `main.py` will instantiate it.
- New environment variables, exact names (main app / 64-bit side): `KIWOOM_BRIDGE_URL`, `KIWOOM_BRIDGE_TOKEN`, `KIWOOM_UNIVERSE_SIZE`, `KIWOOM_RANKING_REFRESH_SECONDS`. New environment variables, exact names (bridge / 32-bit side, read only by `kiwoom_bridge/bridge.py`): `KIWOOM_BRIDGE_PORT`, `KIWOOM_BRIDGE_TOKEN` (must match the main-app value).
- 20-day same-time-of-day averages (`avg_trading_value_same_time_20d`/`avg_volume_same_time_20d`) and news detection (`news_today`/`news_continuing`) are explicitly OUT OF SCOPE for this plan (per the design doc). Leave the averages as `None` (their existing `Optional` default) and always set `news_today=False`/`news_continuing=False`.
- The bridge's JSON response schema (documented per-endpoint in Task 4 below) is this plan's own contract, not a Kiwoom-native shape — it is designed to be as simple as possible for `mapping.py` to consume.

## Design doc

`docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md` — read for full background and rationale. This plan implements it in full, plus two refinements decided during planning (both consistent with the design doc, adding detail it left open):
1. The bridge's quote JSON includes a `market` field (`"KOSPI"`/`"KOSDAQ"`/`null`) sourced from Kiwoom's own market-classification field, instead of hardcoding a single guessed market label for every stock (a mislabeling risk flagged during the KIS integration's final review — this avoids repeating it here from day one).
2. `KiwoomProvider`'s minute-bar handling bakes in the bounded-copy-window fix from the start (see Task 8) rather than discovering the aliasing/O(n²) problem in a later review pass, since `leader_watch/providers/real.py` already demonstrates the exact fix to replicate.

---

## File Structure

```
leader_watch/providers/
├── kiwoom_provider.py         # NEW: KiwoomProvider(MarketDataProvider) — orchestrator
└── kiwoom/
    ├── __init__.py             # NEW: empty
    ├── config.py                 # NEW: KiwoomConfig, load_kiwoom_config(), KiwoomConfigError
    ├── client.py                  # NEW: KiwoomClient, KiwoomApiError
    └── mapping.py                   # NEW: pure functions, bridge JSON -> StockSnapshot/MinuteBar

kiwoom_bridge/                    # NEW top-level package — 32-bit only, not part of the 64-bit venv's runtime
├── __init__.py                    # NEW: empty
├── http_server.py                   # NEW: pure route-dispatch function (testable, no win32com)
├── tr_client.py                       # NEW: win32com-based KiwoomTrClient (NOT unit tested)
├── bridge.py                            # NEW: entrypoint wiring http_server + tr_client (NOT unit tested)
└── README.md                              # NEW: how to run the bridge + manual test protocol

tests/leader_watch/
├── test_kiwoom_config.py           # NEW
├── test_kiwoom_client.py             # NEW
├── test_kiwoom_mapping.py              # NEW
└── test_kiwoom_provider.py               # NEW

tests/kiwoom_bridge/
└── test_http_server.py                     # NEW

main.py            # MODIFY: add --provider kiwoom, catch KiwoomConfigError
.env.example        # MODIFY: append KIWOOM_* variables
README.md            # MODIFY: config table + TODO section
```

---

### Task 1: `kiwoom/config.py` — bridge connection settings

**Files:**
- Create: `leader_watch/providers/kiwoom/__init__.py` (empty)
- Create: `leader_watch/providers/kiwoom/config.py`
- Test: `tests/leader_watch/test_kiwoom_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `KiwoomConfigError(Exception)`, `KiwoomConfig` (frozen dataclass with fields `bridge_url: str`, `bridge_token: str`, `universe_size: int`, `ranking_refresh_seconds: int`), `load_kiwoom_config(env: dict | None = None) -> KiwoomConfig`. All later tasks import these from `leader_watch.providers.kiwoom.config`.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kiwoom_config.py
import pytest
from leader_watch.providers.kiwoom.config import KiwoomConfig, KiwoomConfigError, load_kiwoom_config


def test_missing_bridge_token_raises():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={})


def test_defaults_when_only_token_given():
    cfg = load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok"})
    assert cfg.bridge_token == "tok"
    assert cfg.bridge_url == "http://127.0.0.1:8000"
    assert cfg.universe_size == 100
    assert cfg.ranking_refresh_seconds == 20


def test_env_overrides_are_applied():
    cfg = load_kiwoom_config(env={
        "KIWOOM_BRIDGE_TOKEN": "tok",
        "KIWOOM_BRIDGE_URL": "http://127.0.0.1:9000",
        "KIWOOM_UNIVERSE_SIZE": "50",
        "KIWOOM_RANKING_REFRESH_SECONDS": "10",
    })
    assert cfg.bridge_url == "http://127.0.0.1:9000"
    assert cfg.universe_size == 50
    assert cfg.ranking_refresh_seconds == 10


def test_non_numeric_universe_size_raises_kiwoom_config_error_not_value_error():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok", "KIWOOM_UNIVERSE_SIZE": "abc"})


def test_non_numeric_ranking_refresh_seconds_raises_kiwoom_config_error():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok", "KIWOOM_RANKING_REFRESH_SECONDS": "abc"})


def test_zero_universe_size_raises():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok", "KIWOOM_UNIVERSE_SIZE": "0"})


def test_negative_ranking_refresh_seconds_raises():
    with pytest.raises(KiwoomConfigError):
        load_kiwoom_config(env={"KIWOOM_BRIDGE_TOKEN": "tok", "KIWOOM_RANKING_REFRESH_SECONDS": "-5"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kiwoom_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leader_watch.providers.kiwoom'`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/kiwoom/config.py
"""Environment-driven configuration for the kiwoom_bridge HTTP client.

Numeric env vars are parsed through `_parse_positive_int` so malformed input
(e.g. "abc", "0", "-5") raises `KiwoomConfigError` instead of a bare
`ValueError`/allowing a zero/negative value through — main.py only knows how
to catch `KiwoomConfigError` cleanly (see Task 9), so anything else here
would leak a traceback. This mirrors a fix applied to the KIS integration's
`load_kis_config` after its final review found the same gap.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class KiwoomConfigError(Exception):
    """Raised when required kiwoom bridge configuration is missing or invalid,
    or (per KiwoomProvider's constructor, Task 8) when the bridge itself is
    unreachable."""


@dataclass(frozen=True)
class KiwoomConfig:
    bridge_url: str
    bridge_token: str
    universe_size: int
    ranking_refresh_seconds: int


_DEFAULTS = {
    "KIWOOM_BRIDGE_URL": "http://127.0.0.1:8000",
    "KIWOOM_UNIVERSE_SIZE": "100",
    "KIWOOM_RANKING_REFRESH_SECONDS": "20",
}


def _parse_positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise KiwoomConfigError(f"{name} must be an integer, got {value!r}") from None
    if parsed <= 0:
        raise KiwoomConfigError(f"{name} must be a positive integer, got {parsed}")
    return parsed


def load_kiwoom_config(env: dict | None = None) -> KiwoomConfig:
    source = os.environ if env is None else env
    get = lambda key: source.get(key, _DEFAULTS.get(key, ""))  # noqa: E731

    bridge_token = get("KIWOOM_BRIDGE_TOKEN")
    if not bridge_token:
        raise KiwoomConfigError(
            "KIWOOM_BRIDGE_TOKEN must be set to use --provider kiwoom. See .env.example."
        )

    return KiwoomConfig(
        bridge_url=get("KIWOOM_BRIDGE_URL"),
        bridge_token=bridge_token,
        universe_size=_parse_positive_int(get("KIWOOM_UNIVERSE_SIZE"), "KIWOOM_UNIVERSE_SIZE"),
        ranking_refresh_seconds=_parse_positive_int(
            get("KIWOOM_RANKING_REFRESH_SECONDS"), "KIWOOM_RANKING_REFRESH_SECONDS"
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kiwoom_config.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kiwoom/__init__.py leader_watch/providers/kiwoom/config.py tests/leader_watch/test_kiwoom_config.py
git commit -m "feat(leader_watch): add kiwoom bridge config loader"
```

---

### Task 2: `kiwoom/client.py` — HTTP client for the local bridge

**Files:**
- Create: `leader_watch/providers/kiwoom/client.py`
- Test: `tests/leader_watch/test_kiwoom_client.py`

**Interfaces:**
- Consumes: `KiwoomConfig` (Task 1).
- Produces: `KiwoomApiError(Exception)`, `KiwoomClient` class with `__init__(self, config: KiwoomConfig)`, `check_health(self) -> None`, `get_trading_value_ranking(self, count: int) -> list[dict]`, `get_sector_ranking(self) -> list[dict]`, `get_quote(self, code: str) -> dict`, `get_minute_bars(self, code: str, reference_time: str) -> list[dict]`. Used by `providers/kiwoom_provider.py` (Task 8) via `kiwoom/mapping.py` (Task 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kiwoom_client.py
from unittest.mock import MagicMock, patch

import pytest
import requests
from leader_watch.providers.kiwoom.client import KiwoomApiError, KiwoomClient
from leader_watch.providers.kiwoom.config import KiwoomConfig

CFG = KiwoomConfig(bridge_url="http://127.0.0.1:8000", bridge_token="tok", universe_size=100, ranking_refresh_seconds=20)


def _ok_response(body):
    resp = MagicMock(status_code=200)
    resp.json.return_value = body
    return resp


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_check_health_calls_health_endpoint_with_token_header(mock_get):
    mock_get.return_value = _ok_response({"status": "ok"})
    KiwoomClient(CFG).check_health()
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/health"
    assert kwargs["headers"]["X-Bridge-Token"] == "tok"


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_trading_value_ranking_passes_count_and_returns_list(mock_get):
    mock_get.return_value = _ok_response([{"code": "005930", "name": "삼성전자", "rank": 1}])
    rows = KiwoomClient(CFG).get_trading_value_ranking(50)
    assert rows == [{"code": "005930", "name": "삼성전자", "rank": 1}]
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/ranking/trading-value"
    assert kwargs["params"] == {"count": 50}


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_sector_ranking_returns_list(mock_get):
    mock_get.return_value = _ok_response([{"name": "반도체", "rank": 1}])
    rows = KiwoomClient(CFG).get_sector_ranking()
    assert rows == [{"name": "반도체", "rank": 1}]
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/ranking/sector"


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_quote_returns_dict(mock_get):
    mock_get.return_value = _ok_response({"current_price": 70500})
    quote = KiwoomClient(CFG).get_quote("005930")
    assert quote == {"current_price": 70500}
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/quote/005930"


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_minute_bars_passes_reference_time_and_returns_list(mock_get):
    mock_get.return_value = _ok_response([{"time": "093000"}])
    bars = KiwoomClient(CFG).get_minute_bars("005930", "093000")
    assert bars == [{"time": "093000"}]
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/minute-bars/005930"
    assert kwargs["params"] == {"reference_time": "093000"}


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_non_200_raises_kiwoom_api_error(mock_get):
    mock_get.return_value = MagicMock(status_code=401, text="invalid token")
    with pytest.raises(KiwoomApiError):
        KiwoomClient(CFG).check_health()


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_request_exception_is_normalized_to_kiwoom_api_error(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("refused")
    with pytest.raises(KiwoomApiError):
        KiwoomClient(CFG).check_health()


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_quote_missing_dict_body_returns_empty_dict(mock_get):
    mock_get.return_value = _ok_response(["not", "a", "dict"])
    quote = KiwoomClient(CFG).get_quote("005930")
    assert quote == {}


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_trading_value_ranking_missing_list_body_returns_empty_list(mock_get):
    mock_get.return_value = _ok_response({"not": "a list"})
    rows = KiwoomClient(CFG).get_trading_value_ranking(50)
    assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kiwoom_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leader_watch.providers.kiwoom.client'`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/kiwoom/client.py
"""HTTP client for the local kiwoom_bridge process (see kiwoom_bridge/).

The bridge is a plain, unauthenticated-by-default local HTTP server other
than the shared-secret `X-Bridge-Token` header, so every request carries it.
`requests.RequestException` (timeouts, connection refused, etc.) is
normalized to `KiwoomApiError` here so a down/unreachable bridge never
surfaces as a raw, uncaught requests exception to callers — the same fix
applied to `leader_watch/providers/kis/client.py` after the KIS
integration's final review found the gap.
"""
from __future__ import annotations

import requests

from leader_watch.providers.kiwoom.config import KiwoomConfig


class KiwoomApiError(Exception):
    """Raised when a kiwoom_bridge HTTP call fails or the bridge is unreachable."""


class KiwoomClient:
    def __init__(self, config: KiwoomConfig) -> None:
        self._config = config

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        try:
            response = requests.get(
                f"{self._config.bridge_url}{path}",
                headers={"X-Bridge-Token": self._config.bridge_token},
                params=params or {},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise KiwoomApiError(f"kiwoom_bridge call to {path} failed: {exc}") from exc
        if response.status_code != 200:
            raise KiwoomApiError(
                f"kiwoom_bridge call to {path} failed with status {response.status_code}: {response.text}"
            )
        return response.json()

    def check_health(self) -> None:
        self._get("/health")

    def get_trading_value_ranking(self, count: int) -> list[dict]:
        body = self._get("/ranking/trading-value", params={"count": count})
        return body if isinstance(body, list) else []

    def get_sector_ranking(self) -> list[dict]:
        body = self._get("/ranking/sector")
        return body if isinstance(body, list) else []

    def get_quote(self, code: str) -> dict:
        body = self._get(f"/quote/{code}")
        return body if isinstance(body, dict) else {}

    def get_minute_bars(self, code: str, reference_time: str) -> list[dict]:
        body = self._get(f"/minute-bars/{code}", params={"reference_time": reference_time})
        return body if isinstance(body, list) else []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kiwoom_client.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kiwoom/client.py tests/leader_watch/test_kiwoom_client.py
git commit -m "feat(leader_watch): add kiwoom_bridge HTTP client"
```

---

### Task 3: `kiwoom/mapping.py` — bridge JSON to StockSnapshot/MinuteBar

**Files:**
- Create: `leader_watch/providers/kiwoom/mapping.py`
- Test: `tests/leader_watch/test_kiwoom_mapping.py`

**Interfaces:**
- Consumes: `StockSnapshot`, `MinuteBar` from `leader_watch.models` (existing, unmodified).
- Produces: `parse_ranking_row(row: dict) -> tuple[str, str, int]`, `parse_sector_ranking(rows: list[dict]) -> dict[str, int]`, `quote_to_snapshot(quote: dict, code: str, name: str, market: str, received_at: datetime.datetime, market_rank: int, theme_rank_by_sector: dict[str, int]) -> StockSnapshot`, `parse_minute_bar(row: dict, reference_date: datetime.date) -> MinuteBar`. Used by `providers/kiwoom_provider.py` (Task 8).

**Bridge JSON schema this file consumes** (produced by `kiwoom_bridge/http_server.py`, Task 4, ultimately sourced from `kiwoom_bridge/tr_client.py`, Task 5):
- Ranking row: `{"code": str, "name": str, "rank": int|str}`
- Sector ranking row: `{"name": str, "rank": int|str}` (rank optional — falls back to list position, same as KIS)
- Quote: `{"current_price": num, "open": num, "high": num, "low": num, "prev_close": num, "volume": int, "trading_value": num, "sector": str|null, "market": "KOSPI"|"KOSDAQ"|null, "status": "normal"|"administrative"|"investment_alert"|"trading_halted", "execution_strength": num|null}`
- Minute bar row: `{"time": "HHMMSS", "open": num, "high": num, "low": num, "close": num, "volume": int}`

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kiwoom_mapping.py
import datetime

from leader_watch.providers.kiwoom.mapping import (
    parse_minute_bar,
    parse_ranking_row,
    parse_sector_ranking,
    quote_to_snapshot,
)


def test_parse_ranking_row():
    code, name, rank = parse_ranking_row({"code": "005930", "name": "삼성전자", "rank": "3"})
    assert code == "005930"
    assert name == "삼성전자"
    assert rank == 3


def test_parse_sector_ranking_uses_rank_when_present():
    ranks = parse_sector_ranking([{"name": "반도체", "rank": 1}, {"name": "2차전지", "rank": 2}])
    assert ranks == {"반도체": 1, "2차전지": 2}


def test_parse_sector_ranking_falls_back_to_position_when_rank_missing():
    ranks = parse_sector_ranking([{"name": "반도체"}, {"name": "2차전지"}])
    assert ranks == {"반도체": 1, "2차전지": 2}


def _quote(**overrides):
    base = {
        "current_price": 70500, "open": 70000, "high": 71000, "low": 69800,
        "prev_close": 70000, "volume": 12345678, "trading_value": 870123456789,
        "sector": "반도체", "market": "KOSPI", "status": "normal",
    }
    base.update(overrides)
    return base


def test_quote_to_snapshot_maps_core_fields():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={"반도체": 1},
    )
    assert snap.code == "005930"
    assert snap.market == "KOSPI"
    assert snap.current_price == 70500.0
    assert snap.prev_close == 70000.0
    assert snap.open_price == 70000.0
    assert snap.high_price == 71000.0
    assert snap.low_price == 69800.0
    assert snap.cum_volume == 12345678
    assert snap.cum_trading_value == 870123456789.0
    assert snap.market_trading_value_rank == 5
    assert snap.theme == "반도체"
    assert snap.theme_trading_value_rank == 1
    assert snap.news_today is False
    assert snap.news_continuing is False
    assert snap.avg_trading_value_same_time_20d is None
    assert snap.avg_volume_same_time_20d is None


def test_quote_to_snapshot_uses_market_field_when_present():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(market="KOSDAQ"), code="123456", name="어떤종목", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.market == "KOSDAQ"  # bridge-supplied market wins over the caller's fallback


def test_quote_to_snapshot_falls_back_to_caller_market_when_missing():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(market=None), code="123456", name="어떤종목", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.market == "KOSPI"


def test_quote_to_snapshot_execution_strength_defaults_to_neutral_when_absent():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.execution_strength == 100.0


def test_quote_to_snapshot_uses_execution_strength_when_present():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(execution_strength=145.3), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.execution_strength == 145.3


def test_quote_to_snapshot_theme_none_when_sector_missing():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(sector=None), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={"반도체": 1},
    )
    assert snap.theme is None
    assert snap.theme_trading_value_rank is None


def test_quote_to_snapshot_maps_administrative_status():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(status="administrative"), code="000001", name="관리종목", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_administrative is True
    assert snap.is_investment_alert is False
    assert snap.is_trading_halted is False


def test_quote_to_snapshot_maps_investment_alert_status():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(status="investment_alert"), code="000002", name="투자위험", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_investment_alert is True


def test_quote_to_snapshot_maps_trading_halted_status():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(status="trading_halted"), code="000003", name="거래정지", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_trading_halted is True


def test_quote_to_snapshot_normal_status_excludes_nothing():
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snap = quote_to_snapshot(
        _quote(status="normal"), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.is_administrative is False
    assert snap.is_investment_alert is False
    assert snap.is_trading_halted is False


def test_parse_minute_bar():
    row = {"time": "093000", "open": 70000, "high": 70200, "low": 69900, "close": 70100, "volume": 12345}
    bar = parse_minute_bar(row, reference_date=datetime.date(2026, 8, 13))
    assert bar.timestamp == datetime.datetime(2026, 8, 13, 9, 30)
    assert bar.open == 70000.0
    assert bar.high == 70200.0
    assert bar.low == 69900.0
    assert bar.close == 70100.0
    assert bar.volume == 12345
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kiwoom_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leader_watch.providers.kiwoom.mapping'`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/kiwoom/mapping.py
"""Pure functions mapping the kiwoom_bridge JSON schema to StockSnapshot/MinuteBar.

Unlike leader_watch/providers/kis/mapping.py, this file carries no
ASSUMPTION-tagged raw broker field names — kiwoom_bridge/ already normalizes
real Kiwoom TR responses into the clean JSON schema documented in Task 3 of
docs/superpowers/plans/2026-08-13-kiwoom-provider.md (mirroring
docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md, "브릿지 HTTP
프로토콜"). All broker-specific field-name guessing lives in
kiwoom_bridge/tr_client.py instead, tagged ASSUMPTION there.
"""
from __future__ import annotations

import datetime

from leader_watch.models import MinuteBar, StockSnapshot

_STATUS_ADMINISTRATIVE = "administrative"
_STATUS_INVESTMENT_ALERT = "investment_alert"
_STATUS_TRADING_HALTED = "trading_halted"


def parse_ranking_row(row: dict) -> tuple[str, str, int]:
    return row["code"], row["name"], int(row["rank"])


def parse_sector_ranking(rows: list[dict]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for position, row in enumerate(rows, start=1):
        raw_rank = row.get("rank")
        ranks[row["name"]] = int(raw_rank) if raw_rank else position
    return ranks


def quote_to_snapshot(
    quote: dict,
    code: str,
    name: str,
    market: str,
    received_at: datetime.datetime,
    market_rank: int,
    theme_rank_by_sector: dict[str, int],
) -> StockSnapshot:
    status = quote.get("status", "normal")
    sector_name = quote.get("sector") or None
    theme_rank = theme_rank_by_sector.get(sector_name) if sector_name else None
    # The bridge-supplied market (from Kiwoom's own field) wins when present;
    # `market` is only a fallback for when the bridge couldn't determine it.
    resolved_market = quote.get("market") or market

    execution_strength_raw = quote.get("execution_strength")
    execution_strength = (
        float(execution_strength_raw) if execution_strength_raw not in (None, "") else 100.0
    )

    return StockSnapshot(
        code=code,
        name=name,
        market=resolved_market,
        timestamp=received_at,
        current_price=float(quote["current_price"]),
        prev_close=float(quote["prev_close"]),
        open_price=float(quote["open"]),
        high_price=float(quote["high"]),
        low_price=float(quote["low"]),
        cum_volume=int(quote["volume"]),
        cum_trading_value=float(quote["trading_value"]),
        market_trading_value_rank=market_rank,
        execution_strength=execution_strength,
        theme=sector_name,
        theme_trading_value_rank=theme_rank,
        news_today=False,
        news_continuing=False,
        is_administrative=status == _STATUS_ADMINISTRATIVE,
        is_investment_alert=status == _STATUS_INVESTMENT_ALERT,
        is_trading_halted=status == _STATUS_TRADING_HALTED,
    )


def parse_minute_bar(row: dict, reference_date: datetime.date) -> MinuteBar:
    time_str = str(row["time"]).zfill(6)
    hour, minute = int(time_str[0:2]), int(time_str[2:4])
    timestamp = datetime.datetime(reference_date.year, reference_date.month, reference_date.day, hour, minute)
    return MinuteBar(
        timestamp=timestamp,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=int(row["volume"]),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kiwoom_mapping.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kiwoom/mapping.py tests/leader_watch/test_kiwoom_mapping.py
git commit -m "feat(leader_watch): add kiwoom_bridge response mapping to StockSnapshot/MinuteBar"
```

---

### Task 4: `kiwoom_bridge/http_server.py` — pure HTTP route dispatch

**Files:**
- Create: `kiwoom_bridge/__init__.py` (empty)
- Create: `kiwoom_bridge/http_server.py`
- Test: `tests/kiwoom_bridge/test_http_server.py`

**Interfaces:**
- Consumes: nothing (defines a `TrClient` `Protocol` that Task 5's real `KiwoomTrClient` and this task's tests' fake both satisfy structurally).
- Produces: `handle_request(method: str, path: str, headers: dict, tr_client: TrClient, expected_token: str) -> tuple[int, dict | list]`. Used by `kiwoom_bridge/bridge.py` (Task 6).

This is the routing/response-shaping logic separated from any actual socket or win32com machinery, so it is fully unit-testable here even though `kiwoom_bridge/tr_client.py` (Task 5) is not.

- [ ] **Step 1: Write the failing test**

```python
# tests/kiwoom_bridge/test_http_server.py
from kiwoom_bridge.http_server import handle_request

TOKEN = "tok"


class _FakeTrClient:
    def __init__(self):
        self.ranking_calls = []
        self.sector_calls = 0
        self.quote_calls = []
        self.minute_bar_calls = []
        self.raise_on_quote_for: set[str] = set()

    def get_trading_value_ranking(self, count):
        self.ranking_calls.append(count)
        return [{"code": "005930", "name": "삼성전자", "rank": 1}][:count]

    def get_sector_ranking(self):
        self.sector_calls += 1
        return [{"name": "반도체", "rank": 1}]

    def get_quote(self, code):
        self.quote_calls.append(code)
        if code in self.raise_on_quote_for:
            raise RuntimeError(f"TR failure for {code}")
        return {"current_price": 70500}

    def get_minute_bars(self, code, reference_time):
        self.minute_bar_calls.append((code, reference_time))
        return [{"time": reference_time}]


def test_missing_token_returns_401():
    status, body = handle_request("GET", "/health", {}, _FakeTrClient(), TOKEN)
    assert status == 401


def test_wrong_token_returns_401():
    status, body = handle_request("GET", "/health", {"X-Bridge-Token": "wrong"}, _FakeTrClient(), TOKEN)
    assert status == 401


def test_health_returns_200_ok():
    status, body = handle_request("GET", "/health", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN)
    assert status == 200
    assert body == {"status": "ok"}


def test_non_get_method_returns_404():
    status, body = handle_request("POST", "/health", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN)
    assert status == 404


def test_ranking_trading_value_passes_count_query_param():
    client = _FakeTrClient()
    status, body = handle_request(
        "GET", "/ranking/trading-value?count=1", {"X-Bridge-Token": TOKEN}, client, TOKEN
    )
    assert status == 200
    assert body == [{"code": "005930", "name": "삼성전자", "rank": 1}]
    assert client.ranking_calls == [1]


def test_ranking_trading_value_defaults_count_to_100_when_missing():
    client = _FakeTrClient()
    handle_request("GET", "/ranking/trading-value", {"X-Bridge-Token": TOKEN}, client, TOKEN)
    assert client.ranking_calls == [100]


def test_ranking_sector_returns_rows():
    status, body = handle_request(
        "GET", "/ranking/sector", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN
    )
    assert status == 200
    assert body == [{"name": "반도체", "rank": 1}]


def test_quote_route_extracts_code_from_path():
    client = _FakeTrClient()
    status, body = handle_request("GET", "/quote/005930", {"X-Bridge-Token": TOKEN}, client, TOKEN)
    assert status == 200
    assert body == {"current_price": 70500}
    assert client.quote_calls == ["005930"]


def test_quote_route_missing_code_returns_404():
    status, body = handle_request("GET", "/quote/", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN)
    assert status == 404


def test_minute_bars_route_requires_reference_time_query_param():
    status, body = handle_request(
        "GET", "/minute-bars/005930", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN
    )
    assert status == 400


def test_minute_bars_route_returns_rows():
    client = _FakeTrClient()
    status, body = handle_request(
        "GET", "/minute-bars/005930?reference_time=093000", {"X-Bridge-Token": TOKEN}, client, TOKEN
    )
    assert status == 200
    assert body == [{"time": "093000"}]
    assert client.minute_bar_calls == [("005930", "093000")]


def test_unknown_route_returns_404():
    status, body = handle_request("GET", "/nonsense", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN)
    assert status == 404


def test_tr_client_exception_becomes_503_not_a_raised_exception():
    client = _FakeTrClient()
    client.raise_on_quote_for.add("005930")
    status, body = handle_request("GET", "/quote/005930", {"X-Bridge-Token": TOKEN}, client, TOKEN)
    assert status == 503
    assert "error" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kiwoom_bridge/test_http_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kiwoom_bridge'`

- [ ] **Step 3: Write minimal implementation**

```python
# kiwoom_bridge/http_server.py
"""Pure HTTP-routing logic for kiwoom_bridge (see kiwoom_bridge/README.md).

Deliberately separated from any actual socket/HTTP-server machinery, and
from kiwoom_bridge/tr_client.py's win32com dependency, so this file's
routing/response-shaping logic — the part most likely to have copy-paste
bugs — is fully unit testable without a live Kiwoom login or even a real
HTTP server. kiwoom_bridge/bridge.py (Task 6) wires this dispatch function
into an actual http.server.HTTPServer; that wiring is NOT unit tested (see
docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md, "테스트 계획").
"""
from __future__ import annotations

from typing import Protocol
from urllib.parse import parse_qs, urlparse


class TrClient(Protocol):
    def get_trading_value_ranking(self, count: int) -> list[dict]: ...
    def get_sector_ranking(self) -> list[dict]: ...
    def get_quote(self, code: str) -> dict: ...
    def get_minute_bars(self, code: str, reference_time: str) -> list[dict]: ...


def handle_request(
    method: str,
    path: str,
    headers: dict,
    tr_client: TrClient,
    expected_token: str,
) -> tuple[int, dict | list]:
    """Route one HTTP request to a TrClient call. Returns (status_code, json_body)."""
    if method != "GET":
        return 404, {"error": f"unsupported method {method}"}

    if headers.get("X-Bridge-Token") != expected_token:
        return 401, {"error": "invalid or missing X-Bridge-Token"}

    parsed = urlparse(path)
    route = parsed.path
    query = {key: values[0] for key, values in parse_qs(parsed.query).items()}

    try:
        if route == "/health":
            return 200, {"status": "ok"}
        if route == "/ranking/trading-value":
            count = int(query.get("count", "100"))
            return 200, tr_client.get_trading_value_ranking(count)
        if route == "/ranking/sector":
            return 200, tr_client.get_sector_ranking()
        if route.startswith("/quote/"):
            code = route[len("/quote/"):]
            if not code:
                return 404, {"error": "missing stock code"}
            return 200, tr_client.get_quote(code)
        if route.startswith("/minute-bars/"):
            code = route[len("/minute-bars/"):]
            if not code:
                return 404, {"error": "missing stock code"}
            reference_time = query.get("reference_time", "")
            if not reference_time:
                return 400, {"error": "reference_time query param is required"}
            return 200, tr_client.get_minute_bars(code, reference_time)
    except Exception as exc:  # noqa: BLE001 - any TR failure becomes a clean 503, never a raised exception
        return 503, {"error": str(exc)}

    return 404, {"error": f"unknown route {route}"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/kiwoom_bridge/test_http_server.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add kiwoom_bridge/__init__.py kiwoom_bridge/http_server.py tests/kiwoom_bridge/test_http_server.py
git commit -m "feat(kiwoom_bridge): add pure HTTP route-dispatch logic"
```

---

### Task 5: `kiwoom_bridge/tr_client.py` — win32com TR wrapper (NOT unit tested)

**Files:**
- Create: `kiwoom_bridge/tr_client.py`

**Interfaces:**
- Consumes: `win32com.client`, `pythoncom` (pywin32 — not installed in this repo's test environment; import only happens inside this file).
- Produces: `KiwoomTrError(Exception)`, `KiwoomTrClient` class with `__init__(self)`, `get_trading_value_ranking(self, count: int) -> list[dict]`, `get_sector_ranking(self) -> list[dict]`, `get_quote(self, code: str) -> dict`, `get_minute_bars(self, code: str, reference_time: str) -> list[dict]` — each returning data already shaped to match the bridge JSON schema documented in Task 3, so `kiwoom_bridge/http_server.py` (Task 4) can hand its return value straight back as the HTTP response body. Used by `kiwoom_bridge/bridge.py` (Task 6).

**This file cannot be imported or unit tested in this repository's environment** (no `win32com`/`pythoncom`, no 32-bit Windows COM runtime, no logged-in Kiwoom OpenAPI+ session) — see the plan's Global Constraints and `docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md`, "테스트 계획". This task has no RED/GREEN test cycle; instead it has a syntax-only compile check (Step 2) and a manual-verification note (Step 3) pointing at `kiwoom_bridge/README.md` (Task 6), which the user runs by hand in their 32-bit environment after this plan is fully implemented.

Every TR code and raw field name below is an `ASSUMPTION` — a best-effort guess at commonly documented 키움 OpenAPI+ TR shapes — and MUST be checked against a real login before trusting this file's output. If a real response differs, change ONLY the named constants; the surrounding request/parse logic should not need to change.

- [ ] **Step 1: Write the implementation**

```python
# kiwoom_bridge/tr_client.py
"""kiwoom_bridge/tr_client.py — win32com wrapper around the Kiwoom OpenAPI+ OCX control.

32-bit Python + pywin32 ONLY. This module is not imported by any test in
this repository and cannot be exercised by the automated test suite — see
this plan's Task 5 and docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md,
"테스트 계획" / "브릿지 수동 테스트 프로토콜". Verify it by hand, following
kiwoom_bridge/README.md, after implementing it.

All TR codes and raw Kiwoom field names below are ASSUMPTIONs and MUST be
verified against a real login before trusting this file's output — see the
design doc's "구현 중 반드시 검증해야 할 가정" section. If a real response
uses different TR codes/field names, change ONLY the constants below; the
request/parse logic in the methods should not need to change.

Login is assumed to already be established externally (per this project's
design doc — the user's existing 32-bit win32com setup already handles
OpenAPI+ login) before `KiwoomTrClient()` is constructed; this class does
not itself call `CommConnect`.
"""
from __future__ import annotations

import threading
import time

import pythoncom
import win32com.client


class KiwoomTrError(Exception):
    """Raised when a Kiwoom TR request fails, times out, or returns malformed data."""


# ASSUMPTION: 거래대금상위 조회 TR. Commonly documented as opt10032
# (당일거래량상위/거래대금상위 계열) — verify the exact TR code and the
# 종목코드/종목명/순위 output field names against a real login.
_TR_TRADING_VALUE_RANKING = "opt10032"
_TR_TRADING_VALUE_RANKING_SCREEN = "9001"
_F_RANK_CODE = "종목코드"
_F_RANK_NAME = "종목명"
_F_RANK_RANK = "순위"

# ASSUMPTION: 업종별 순위 TR — verify TR code and output field names.
_TR_SECTOR_RANKING = "opt10053"
_TR_SECTOR_RANKING_SCREEN = "9002"
_F_SECTOR_NAME = "업종명"
_F_SECTOR_RANK = "순위"

# ASSUMPTION: 주식기본정보 TR — verify TR code and every output field name.
_TR_QUOTE = "opt10001"
_TR_QUOTE_SCREEN = "9003"
_F_CURRENT_PRICE = "현재가"
_F_OPEN = "시가"
_F_HIGH = "고가"
_F_LOW = "저가"
_F_PREV_CLOSE = "전일종가"
_F_VOLUME = "거래량"
_F_TRADING_VALUE = "거래대금"
_F_SECTOR = "업종명"
_F_MARKET = "시장구분"
_F_STATUS = "종목상태"

# ASSUMPTION: 분봉차트 TR — verify TR code, and whether output rows are
# most-recent-first (assumed here, matching the KIS integration's convention).
_TR_MINUTE_BARS = "opt10080"
_TR_MINUTE_BARS_SCREEN = "9004"
_F_BAR_TIME = "체결시간"
_F_BAR_OPEN = "시가"
_F_BAR_HIGH = "고가"
_F_BAR_LOW = "저가"
_F_BAR_CLOSE = "현재가"
_F_BAR_VOLUME = "거래량"

# ASSUMPTION: raw 종목상태 value -> normalized bridge status string. Assumes
# Korean text values; some TRs instead return numeric codes (like the KIS
# integration's iscd_stat_cls_code) — verify against a real login.
_STATUS_MAP = {
    "관리종목": "administrative",
    "투자위험": "investment_alert",
    "투자경고": "investment_alert",
    "거래정지": "trading_halted",
}

_TR_TIMEOUT_SECONDS = 10.0


def _map_status(raw: str) -> str:
    return _STATUS_MAP.get(raw.strip(), "normal")


class KiwoomTrClient:
    """Blocking wrapper: each public method sends one TR request and waits
    (via a threading.Event set inside OnReceiveTrData) for its response,
    raising KiwoomTrError on timeout or a Kiwoom-reported failure."""

    def __init__(self) -> None:
        self._ocx = win32com.client.Dispatch("KHOPENAPI.KHOpenAPICtrl.1")
        self._event = threading.Event()
        self._ocx.OnReceiveTrData = self._on_receive_tr_data

    def _on_receive_tr_data(self, scrno, rqname, trcode, recordname, prevnext, *_args) -> None:
        self._event.set()

    def _request_tr(self, rqname: str, trcode: str, screen_no: str, inputs: dict[str, str]) -> None:
        for key, value in inputs.items():
            self._ocx.SetInputValue(key, value)
        self._event.clear()
        ret = self._ocx.CommRqData(rqname, trcode, 0, screen_no)
        if ret != 0:
            raise KiwoomTrError(f"CommRqData({trcode}) failed with return code {ret}")
        deadline = time.time() + _TR_TIMEOUT_SECONDS
        while not self._event.is_set():
            if time.time() > deadline:
                raise KiwoomTrError(f"TR {trcode} timed out after {_TR_TIMEOUT_SECONDS}s")
            pythoncom.PumpWaitingMessages()
            time.sleep(0.05)

    def get_trading_value_ranking(self, count: int) -> list[dict]:
        rqname = "trading_value_ranking"
        self._request_tr(rqname, _TR_TRADING_VALUE_RANKING, _TR_TRADING_VALUE_RANKING_SCREEN, {})
        row_count = self._ocx.GetRepeatCnt(_TR_TRADING_VALUE_RANKING, rqname)
        rows = []
        for i in range(min(row_count, count)):
            rows.append({
                "code": self._ocx.GetCommData(_TR_TRADING_VALUE_RANKING, rqname, i, _F_RANK_CODE).strip(),
                "name": self._ocx.GetCommData(_TR_TRADING_VALUE_RANKING, rqname, i, _F_RANK_NAME).strip(),
                "rank": self._ocx.GetCommData(_TR_TRADING_VALUE_RANKING, rqname, i, _F_RANK_RANK).strip(),
            })
        return rows

    def get_sector_ranking(self) -> list[dict]:
        rqname = "sector_ranking"
        self._request_tr(rqname, _TR_SECTOR_RANKING, _TR_SECTOR_RANKING_SCREEN, {})
        row_count = self._ocx.GetRepeatCnt(_TR_SECTOR_RANKING, rqname)
        rows = []
        for i in range(row_count):
            rows.append({
                "name": self._ocx.GetCommData(_TR_SECTOR_RANKING, rqname, i, _F_SECTOR_NAME).strip(),
                "rank": self._ocx.GetCommData(_TR_SECTOR_RANKING, rqname, i, _F_SECTOR_RANK).strip(),
            })
        return rows

    def get_quote(self, code: str) -> dict:
        rqname = "quote"
        self._request_tr(rqname, _TR_QUOTE, _TR_QUOTE_SCREEN, {"종목코드": code})

        def field(name: str) -> str:
            return self._ocx.GetCommData(_TR_QUOTE, rqname, 0, name).strip()

        # "execution_strength" (체결강도) is intentionally omitted here: unlike
        # the other fields, no ASSUMPTION could be made about which basic-quote
        # TR field (if any) carries it without a real login to check against —
        # it may require a separate TR entirely. kiwoom/mapping.py's
        # quote_to_snapshot already treats it as optional and defaults to a
        # neutral 100.0 when absent, so omitting it here is a safe, honest
        # scope choice, not an oversight. Add it here (and to the ASSUMPTION
        # constants above) once a real field is confirmed.
        return {
            "current_price": field(_F_CURRENT_PRICE),
            "open": field(_F_OPEN),
            "high": field(_F_HIGH),
            "low": field(_F_LOW),
            "prev_close": field(_F_PREV_CLOSE),
            "volume": field(_F_VOLUME),
            "trading_value": field(_F_TRADING_VALUE),
            "sector": field(_F_SECTOR) or None,
            "market": field(_F_MARKET) or None,
            "status": _map_status(field(_F_STATUS)),
        }

    def get_minute_bars(self, code: str, reference_time: str) -> list[dict]:
        rqname = "minute_bars"
        self._request_tr(rqname, _TR_MINUTE_BARS, _TR_MINUTE_BARS_SCREEN, {"종목코드": code, "기준시간": reference_time})
        row_count = self._ocx.GetRepeatCnt(_TR_MINUTE_BARS, rqname)
        rows = []
        for i in range(row_count):
            rows.append({
                "time": self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_TIME).strip(),
                "open": self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_OPEN).strip(),
                "high": self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_HIGH).strip(),
                "low": self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_LOW).strip(),
                "close": self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_CLOSE).strip(),
                "volume": self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_VOLUME).strip(),
            })
        return rows
```

- [ ] **Step 2: Syntax-only compile check (does not require win32com/pywin32)**

Run: `python -m py_compile kiwoom_bridge/tr_client.py`
Expected: exits with no output/no error (confirms valid Python syntax only — does NOT confirm the win32com calls actually work; that requires the manual protocol in Task 6).

- [ ] **Step 3: Commit**

```bash
git add kiwoom_bridge/tr_client.py
git commit -m "feat(kiwoom_bridge): add win32com TR client (untestable outside 32-bit Kiwoom login)"
```

---

### Task 6: `kiwoom_bridge/bridge.py` + `kiwoom_bridge/README.md` — entrypoint and manual test protocol

**Files:**
- Create: `kiwoom_bridge/bridge.py`
- Create: `kiwoom_bridge/README.md`

**Interfaces:**
- Consumes: `handle_request` (Task 4), `KiwoomTrClient` (Task 5).
- Produces: a `main()` entrypoint, run via `python bridge.py` from the 32-bit environment. No Python interface consumed by later tasks — this is the final piece of the bridge process.

Same testing posture as Task 5: this file transitively imports `win32com`/`pythoncom` via `tr_client.py`, so it gets a compile-check, not a pytest run.

- [ ] **Step 1: Write the implementation**

```python
# kiwoom_bridge/bridge.py
"""kiwoom_bridge/bridge.py — entrypoint. 32-bit Python + pywin32 ONLY.

Run this from your existing 32-bit Kiwoom OpenAPI+ environment, after
logging in through the OpenAPI+ login program, per kiwoom_bridge/README.md's
manual test protocol. Not part of the automated test suite — see
docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md, "테스트 계획".
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from kiwoom_bridge.http_server import handle_request
from kiwoom_bridge.tr_client import KiwoomTrClient


def _make_handler(tr_client: KiwoomTrClient, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required name by BaseHTTPRequestHandler
            status, body = handle_request("GET", self.path, dict(self.headers), tr_client, token)
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args) -> None:
            print(f"[kiwoom_bridge] {self.address_string()} - {format % args}")

    return Handler


def main() -> None:
    port = int(os.environ.get("KIWOOM_BRIDGE_PORT", "8000"))
    token = os.environ.get("KIWOOM_BRIDGE_TOKEN", "")
    if not token:
        raise SystemExit("KIWOOM_BRIDGE_TOKEN environment variable must be set before starting the bridge.")

    tr_client = KiwoomTrClient()
    server = HTTPServer(("127.0.0.1", port), _make_handler(tr_client, token))
    print(f"[kiwoom_bridge] listening on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
```

```markdown
# kiwoom_bridge — 실행 및 수동 테스트 절차

**32비트 Python + pywin32 전용.** 메인 `leader_watch` 앱(64비트)과는 별도의
프로세스/환경에서 실행합니다.

## 실행

1. 키움 OpenAPI+ 로그인 프로그램으로 로그인합니다 (기존에 사용하던 방식 그대로).
2. 같은 32비트 Python 환경에서:
   ```
   set KIWOOM_BRIDGE_PORT=8000
   set KIWOOM_BRIDGE_TOKEN=<메인 앱 .env 의 KIWOOM_BRIDGE_TOKEN 과 동일한 값>
   python bridge.py
   ```
3. `[kiwoom_bridge] listening on http://127.0.0.1:8000` 로그가 뜨면 준비 완료입니다.

## 수동 테스트 절차

아래를 순서대로 실행하며 응답을 확인합니다 (`<token>`은 위에서 설정한 값으로 교체):

1. `curl -H "X-Bridge-Token: <token>" http://127.0.0.1:8000/health`
   → `{"status": "ok"}` 확인.
2. `curl -H "X-Bridge-Token: <token>" "http://127.0.0.1:8000/ranking/trading-value?count=5"`
   → 5개 종목의 JSON 배열, 각 항목에 `code`/`name`/`rank` 확인.
3. `curl -H "X-Bridge-Token: <token>" http://127.0.0.1:8000/ranking/sector`
   → 업종 배열, 각 항목에 `name`/`rank` 확인.
4. `curl -H "X-Bridge-Token: <token>" http://127.0.0.1:8000/quote/005930`
   (실제 보유/조회 가능한 종목코드로 교체) → `current_price`/`open`/`high`/`low`/
   `prev_close`/`volume`/`trading_value`/`sector`/`market`/`status` 필드 확인.
5. `curl -H "X-Bridge-Token: <token>" "http://127.0.0.1:8000/minute-bars/005930?reference_time=093000"`
   → 분봉 배열, 각 항목에 `time`/`open`/`high`/`low`/`close`/`volume` 확인.
6. 존재하지 않는 종목코드로 4번을 반복 → HTTP `503` + `{"error": "..."}` 확인
   (트레이스백으로 브릿지 프로세스가 죽지 않아야 함).
7. 잘못된 토큰으로 아무 요청이나 실행 → HTTP `401` 확인.

## 응답 필드가 다를 경우

3-5번에서 확인한 실제 응답 필드명이 `kiwoom_bridge/tr_client.py` 상단의
`ASSUMPTION` 주석이 달린 상수(`_F_*`, `_TR_*`, `_STATUS_MAP`)와 다르면, 그
상수들만 실제 값으로 수정하세요. `_request_tr`/`get_*` 메서드의 로직 자체는
바꿀 필요가 없습니다.
```

- [ ] **Step 2: Syntax-only compile check**

Run: `python -m py_compile kiwoom_bridge/bridge.py`
Expected: exits with no output/no error.

- [ ] **Step 3: Commit**

```bash
git add kiwoom_bridge/bridge.py kiwoom_bridge/README.md
git commit -m "feat(kiwoom_bridge): add HTTP server entrypoint and manual test protocol"
```

---

### Task 7: `providers/kiwoom_provider.py` — KiwoomProvider orchestrator

**Files:**
- Create: `leader_watch/providers/kiwoom_provider.py`
- Test: `tests/leader_watch/test_kiwoom_provider.py`

**Interfaces:**
- Consumes: `KiwoomConfig`/`load_kiwoom_config`/`KiwoomConfigError` (Task 1), `KiwoomClient`/`KiwoomApiError` (Task 2), `parse_ranking_row`/`parse_sector_ranking`/`quote_to_snapshot`/`parse_minute_bar` (Task 3), `call_with_retry` from `leader_watch.engine` (existing, unmodified — import only), `MarketDataProvider` (existing).
- Produces: `KiwoomProvider(MarketDataProvider)` with `__init__(self, config: KiwoomConfig | None = None)` and `get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]`. Consumed by `main.py` (Task 8, call site `KiwoomProvider()`).

This directly ports `leader_watch/providers/real.py`'s caching/staleness/bounded-minute-bar-window design (see that file for the reasoning comments this task's implementation mirrors), swapping in the Kiwoom client/mapping/config/error types, and adds one eager connectivity check at construction time (`client.check_health()`) that `RealProvider` does not have, per the design doc's "브릿지가 아예 떠 있지 않음" requirement.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kiwoom_provider.py
import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.kiwoom.client import KiwoomApiError
from leader_watch.providers.kiwoom.config import KiwoomConfig, KiwoomConfigError
from leader_watch.providers.kiwoom_provider import KiwoomProvider

CFG = KiwoomConfig(bridge_url="http://127.0.0.1:8000", bridge_token="tok", universe_size=100, ranking_refresh_seconds=20)


@pytest.fixture
def _no_real_sleep(monkeypatch):
    """KiwoomProvider wraps each bridge call in leader_watch.engine.call_with_retry,
    whose default backoff sleeps for real. Tests that deliberately exhaust all
    retry attempts patch that sleep to keep the test fast, matching the
    convention already used for RealProvider's equivalent test."""
    monkeypatch.setattr("leader_watch.engine.time.sleep", lambda seconds: None)


class _FakeClient:
    """Stands in for KiwoomClient — KiwoomProvider only calls these four methods
    (health is checked separately at construction, see the _healthy_provider helper)."""

    def __init__(self):
        self.ranking_calls = 0
        self.sector_calls = 0
        self.quote_calls = []
        self.minute_bar_calls = []
        self.ranking_rows = [{"code": "005930", "name": "삼성전자", "rank": 1}]
        self.sector_rows = [{"name": "반도체", "rank": 1}]
        self.quote_by_code = {
            "005930": {
                "current_price": 70500, "open": 70000, "high": 71000, "low": 69800,
                "prev_close": 70000, "volume": 1000000, "trading_value": 70000000000,
                "sector": "반도체", "market": "KOSPI", "status": "normal",
            },
        }
        self.minute_bar_by_code = {
            "005930": [{"time": "093000", "open": 70000, "high": 70200, "low": 69900, "close": 70100, "volume": 12345}],
        }
        self.quote_should_fail_for: set[str] = set()

    def get_trading_value_ranking(self, count):
        self.ranking_calls += 1
        return self.ranking_rows[:count]

    def get_sector_ranking(self):
        self.sector_calls += 1
        return self.sector_rows

    def get_quote(self, code):
        self.quote_calls.append(code)
        if code in self.quote_should_fail_for:
            raise KiwoomApiError(f"simulated failure for {code}")
        return self.quote_by_code.get(code, {})

    def get_minute_bars(self, code, reference_time):
        self.minute_bar_calls.append((code, reference_time))
        return self.minute_bar_by_code.get(code, [])


def _provider_with_fake_client():
    with patch("leader_watch.providers.kiwoom.client.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok"})
        provider = KiwoomProvider(config=CFG)
    fake_client = _FakeClient()
    provider._client = fake_client
    return provider, fake_client


def test_kiwoom_provider_is_a_market_data_provider():
    provider, _ = _provider_with_fake_client()
    assert isinstance(provider, MarketDataProvider)


def test_constructor_raises_kiwoom_config_error_when_bridge_unreachable():
    with patch("leader_watch.providers.kiwoom.client.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        with pytest.raises(KiwoomConfigError):
            KiwoomProvider(config=CFG)


def test_constructor_uses_load_kiwoom_config_when_no_config_given(monkeypatch):
    monkeypatch.setenv("KIWOOM_BRIDGE_TOKEN", "envtoken")
    with patch("leader_watch.providers.kiwoom.client.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status": "ok"})
        provider = KiwoomProvider()
    assert provider._config.bridge_token == "envtoken"


def test_get_snapshot_returns_snapshot_per_ranked_code():
    provider, client = _provider_with_fake_client()
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert isinstance(snap, StockSnapshot)
    assert snap.code == "005930"
    assert snap.market == "KOSPI"
    assert snap.market_trading_value_rank == 1
    assert snap.theme == "반도체"
    assert snap.theme_trading_value_rank == 1
    assert snap.timestamp == now


def test_get_snapshot_includes_minute_bars():
    provider, client = _provider_with_fake_client()
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots[0].minute_bars_1m) == 1
    assert isinstance(snapshots[0].minute_bars_1m[0], MinuteBar)


def test_get_snapshot_does_not_refetch_minute_bar_within_same_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 30))
    assert len(client.minute_bar_calls) == 1


def test_get_snapshot_refetches_minute_bar_on_new_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 31, 0))
    assert len(client.minute_bar_calls) == 2


def test_update_minute_bar_requests_previous_completed_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 31, 0))
    assert client.minute_bar_calls == [("005930", "093000")]


def test_get_snapshot_accumulates_minute_bars_across_ticks():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 31, 0))
    assert len(snapshots[0].minute_bars_1m) == 2


def test_get_snapshot_does_not_alias_minute_bars_across_ticks():
    provider, client = _provider_with_fake_client()
    tick1_snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    tick1_bars = tick1_snapshots[0].minute_bars_1m
    assert len(tick1_bars) == 1
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 31, 0))
    assert len(tick1_bars) == 1  # the tick-1 snapshot's own list must not have grown


def test_get_snapshot_minute_bars_1m_is_bounded_to_window():
    provider, client = _provider_with_fake_client()
    for minute in range(30, 38):  # 8 ticks, 8 minutes
        snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, minute, 0))
    assert len(snapshots[0].minute_bars_1m) == 5


def test_get_snapshot_does_not_refetch_ranking_within_refresh_window():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 5))
    assert client.ranking_calls == 1
    assert client.sector_calls == 1


def test_get_snapshot_refetches_ranking_after_refresh_window_elapses():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 13, 9, 30, 25))  # > 20s KIWOOM_RANKING_REFRESH_SECONDS
    assert client.ranking_calls == 2
    assert client.sector_calls == 2


@pytest.mark.usefixtures("_no_real_sleep")
def test_get_snapshot_skips_codes_whose_quote_fails():
    provider, client = _provider_with_fake_client()
    client.quote_should_fail_for.add("005930")
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert snapshots == []


@pytest.mark.usefixtures("_no_real_sleep")
def test_get_snapshot_skips_codes_with_malformed_quote_but_keeps_others():
    provider, client = _provider_with_fake_client()
    client.ranking_rows = [
        {"code": "005930", "name": "삼성전자", "rank": 1},
        {"code": "000660", "name": "SK하이닉스", "rank": 2},
    ]
    client.quote_by_code["000660"] = {}  # missing required fields -> KeyError inside mapping
    now = datetime.datetime(2026, 8, 13, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots) == 1
    assert snapshots[0].code == "005930"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kiwoom_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leader_watch.providers.kiwoom_provider'`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/kiwoom_provider.py
"""KiwoomProvider — orchestrates the kiwoom_bridge HTTP client into a MarketDataProvider.

Directly ports leader_watch/providers/real.py's caching/staleness/bounded-
minute-bar-window design (see that file's comments for the full reasoning):
ranking/sector data is refreshed on a slow cadence, quotes are fetched fresh
every tick, minute bars are fetched only once per new minute per code (the
PREVIOUS completed minute, never the in-progress one), and each snapshot
gets a bounded COPY of the most recent minute bars rather than a live
reference to the growing cache.

Unlike RealProvider, this provider also eagerly checks bridge connectivity
at construction (`client.check_health()`) and raises KiwoomConfigError if
the bridge is unreachable, per the design doc's "브릿지가 아예 떠 있지
않음(connection refused)" requirement — the bridge being an entirely
separate local process makes "bridge simply isn't running yet" a much more
common failure mode than anything in the KIS integration.
"""
from __future__ import annotations

import datetime

from leader_watch.engine import call_with_retry
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.kiwoom.client import KiwoomApiError, KiwoomClient
from leader_watch.providers.kiwoom.config import KiwoomConfig, KiwoomConfigError, load_kiwoom_config
from leader_watch.providers.kiwoom.mapping import (
    parse_minute_bar,
    parse_ranking_row,
    parse_sector_ranking,
    quote_to_snapshot,
)

# Fallback market label when the bridge quote doesn't supply one (see
# kiwoom/mapping.py's quote_to_snapshot — the bridge's own "market" field
# wins when present; this is only used if that field is missing/null).
_DEFAULT_MARKET_FALLBACK = "KOSPI"

# See leader_watch/providers/real.py's `_MINUTE_BAR_WINDOW` for the full
# reasoning (scoring.py concatenates minute_bars_1m across engine.history
# assuming ~1 bar/snapshot; state_machine.py needs >=2 bars within a single
# snapshot). Same fixed window, same rationale, applied here from the start.
_MINUTE_BAR_WINDOW = 5


def _aggregate_5m(bars_1m: list[MinuteBar]) -> list[MinuteBar]:
    """Group a chronological list of 1-minute bars into completed 5-minute candles."""
    aggregated: list[MinuteBar] = []
    complete_len = len(bars_1m) - (len(bars_1m) % 5)
    for start in range(0, complete_len, 5):
        chunk = bars_1m[start:start + 5]
        aggregated.append(
            MinuteBar(
                timestamp=chunk[0].timestamp,
                open=chunk[0].open,
                high=max(b.high for b in chunk),
                low=min(b.low for b in chunk),
                close=chunk[-1].close,
                volume=sum(b.volume for b in chunk),
            )
        )
    return aggregated


class KiwoomProvider(MarketDataProvider):
    """KiwoomProvider — thin orchestrator over the kiwoom_bridge HTTP client.

    Note on snapshot timestamp / staleness: every StockSnapshot produced by
    get_snapshot(now) is stamped with timestamp=now (the tick's own poll
    time), not a bridge-supplied trade timestamp, for the same reason
    documented on RealProvider: this provider polls synchronously, so `now`
    IS an honest observation time for this architecture. One consequence:
    engine.py's is_stale(snapshot, now, config) staleness check is a
    structural no-op for this provider too — an accepted, documented
    limitation, not a bug.
    """

    def __init__(self, config: KiwoomConfig | None = None) -> None:
        self._config = config or load_kiwoom_config()
        self._client = KiwoomClient(self._config)
        try:
            self._client.check_health()
        except KiwoomApiError as exc:
            raise KiwoomConfigError(
                f"kiwoom_bridge에 연결할 수 없습니다 ({self._config.bridge_url}): {exc}\n"
                "  kiwoom_bridge/bridge.py 가 32비트 환경에서 실행 중인지, "
                "KIWOOM_BRIDGE_TOKEN이 양쪽에 동일하게 설정되어 있는지 확인하세요."
            ) from exc

        self._ranking_cache: list[tuple[str, str, int]] = []
        self._ranking_cache_at: datetime.datetime | None = None
        self._sector_rank_cache: dict[str, int] = {}
        self._sector_rank_cache_at: datetime.datetime | None = None

        self._bars_1m: dict[str, list[MinuteBar]] = {}
        self._last_bar_minute: dict[str, tuple[int, int]] = {}

    def _refresh_ranking_if_stale(self, now: datetime.datetime) -> None:
        if (
            self._ranking_cache_at is not None
            and (now - self._ranking_cache_at).total_seconds() < self._config.ranking_refresh_seconds
        ):
            return
        rows = call_with_retry(lambda: self._client.get_trading_value_ranking(self._config.universe_size))
        self._ranking_cache = [parse_ranking_row(row) for row in rows]
        self._ranking_cache_at = now

    def _refresh_sector_ranking_if_stale(self, now: datetime.datetime) -> None:
        if (
            self._sector_rank_cache_at is not None
            and (now - self._sector_rank_cache_at).total_seconds() < self._config.ranking_refresh_seconds
        ):
            return
        rows = call_with_retry(lambda: self._client.get_sector_ranking())
        self._sector_rank_cache = parse_sector_ranking(rows)
        self._sector_rank_cache_at = now

    def _update_minute_bar(self, code: str, now: datetime.datetime) -> None:
        current_minute = (now.hour, now.minute)
        if self._last_bar_minute.get(code) == current_minute:
            return
        # Request the PREVIOUS completed minute, not `now`'s own minute —
        # see leader_watch/providers/real.py's `_update_minute_bar` for why.
        reference_time = (now - datetime.timedelta(minutes=1)).strftime("%H%M%S")
        try:
            rows = call_with_retry(lambda: self._client.get_minute_bars(code, reference_time))
        except KiwoomApiError:
            return
        if not rows:
            return
        bar = parse_minute_bar(rows[0], now.date())
        self._bars_1m.setdefault(code, []).append(bar)
        self._last_bar_minute[code] = current_minute

    def get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]:
        self._refresh_ranking_if_stale(now)
        self._refresh_sector_ranking_if_stale(now)

        snapshots: list[StockSnapshot] = []
        for code, name, rank in self._ranking_cache:
            try:
                quote = call_with_retry(lambda code=code: self._client.get_quote(code))
                snapshot = quote_to_snapshot(
                    quote,
                    code=code,
                    name=name,
                    market=_DEFAULT_MARKET_FALLBACK,
                    received_at=now,
                    market_rank=rank,
                    theme_rank_by_sector=self._sector_rank_cache,
                )
            except (KiwoomApiError, KeyError, ValueError, TypeError):
                # Partial-failure tolerance: a bad/partial quote for one code
                # must not abort the whole tick — skip just this code.
                continue

            self._update_minute_bar(code, now)
            bars_1m_full = self._bars_1m.get(code, [])
            # Bounded COPY, never the live cached list — see _MINUTE_BAR_WINDOW above.
            snapshot.minute_bars_1m = list(bars_1m_full[-_MINUTE_BAR_WINDOW:])
            snapshot.minute_bars_5m = _aggregate_5m(bars_1m_full)
            snapshots.append(snapshot)

        return snapshots
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kiwoom_provider.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kiwoom_provider.py tests/leader_watch/test_kiwoom_provider.py
git commit -m "feat(leader_watch): implement KiwoomProvider against the kiwoom_bridge HTTP API"
```

---

### Task 8: `main.py` — add `--provider kiwoom`

**Files:**
- Modify: `main.py`
- Modify: `tests/leader_watch/test_main_cli.py`

**Interfaces:**
- Consumes: `KiwoomProvider` (Task 7), `KiwoomConfigError` (Task 1).
- Produces: no new public interface — `main.py` gains a third `--provider` choice and catches `KiwoomConfigError` alongside the existing `KisConfigError`.

- [ ] **Step 1: Read the current `main.py`**

Read the file first — it currently has (per the existing KIS integration):
```python
from leader_watch.providers.kis.config import KisConfigError
from leader_watch.providers.real import RealProvider
...
parser.add_argument("--provider", choices=["mock", "real"], default="mock")
...
    try:
        provider = MockProvider() if args.provider == "mock" else RealProvider()
    except KisConfigError as exc:
        print(f"[leader_watch] {exc}", file=sys.stderr)
        return 1
```

- [ ] **Step 2: Write the failing test**

Append to `tests/leader_watch/test_main_cli.py`:

```python
from leader_watch.providers.kiwoom.config import KiwoomConfigError


def test_arg_parser_accepts_kiwoom_provider():
    parser = build_arg_parser()
    args = parser.parse_args(["--provider", "kiwoom"])
    assert args.provider == "kiwoom"


def test_leader_watch_main_reports_missing_kiwoom_bridge_token_without_traceback(monkeypatch, capsys):
    monkeypatch.delenv("KIWOOM_BRIDGE_TOKEN", raising=False)
    exit_code = leader_watch_main(["--provider", "kiwoom", "--notifier", "console", "--single-tick"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "KIWOOM_BRIDGE_TOKEN" in captured.err or "KIWOOM" in captured.err
    assert "Traceback" not in captured.err
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_main_cli.py -v`
Expected: FAIL — `test_arg_parser_accepts_kiwoom_provider` fails with `SystemExit` (invalid choice 'kiwoom'); `test_leader_watch_main_reports_missing_kiwoom_bridge_token_without_traceback` fails with `AttributeError`/`NameError` (no `"kiwoom"` branch exists yet)

- [ ] **Step 4: Modify `main.py`**

Add the import alongside the existing `leader_watch.*` imports:

```python
from leader_watch.providers.kiwoom.config import KiwoomConfigError
from leader_watch.providers.kiwoom_provider import KiwoomProvider
```

Change the `--provider` choices:

```python
parser.add_argument("--provider", choices=["mock", "real", "kiwoom"], default="mock")
```

Change the provider-construction block from:

```python
    try:
        provider = MockProvider() if args.provider == "mock" else RealProvider()
    except KisConfigError as exc:
        print(f"[leader_watch] {exc}", file=sys.stderr)
        return 1
```

to:

```python
    try:
        if args.provider == "mock":
            provider = MockProvider()
        elif args.provider == "real":
            provider = RealProvider()
        else:
            provider = KiwoomProvider()
    except (KisConfigError, KiwoomConfigError) as exc:
        print(f"[leader_watch] {exc}", file=sys.stderr)
        return 1
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_main_cli.py -v`
Expected: PASS (all tests in the file, including the two new ones)

- [ ] **Step 6: Run the full leader_watch suite to confirm nothing else broke**

Run: `pytest tests/leader_watch/ -v`
Expected: PASS, no regressions in `test_engine.py`/KIS tests/`test_providers_real.py` (none of them touch `KiwoomProvider`).

- [ ] **Step 7: Commit**

```bash
git add main.py tests/leader_watch/test_main_cli.py
git commit -m "feat(leader_watch): add --provider kiwoom"
```

---

### Task 9: `.env.example` and `README.md` updates

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Append to `.env.example`**

Append after the existing `KIS_MAX_REQUESTS_PER_SECOND=15` line:

```env

# --- Kiwoom OpenAPI+ bridge (KiwoomProvider, --provider kiwoom) ---
# The bridge itself (kiwoom_bridge/) runs separately in a 32-bit Python
# environment — see kiwoom_bridge/README.md. These vars configure the main
# app's HTTP client to reach it; KIWOOM_BRIDGE_TOKEN must match the value
# the bridge process was started with.
KIWOOM_BRIDGE_URL=http://127.0.0.1:8000
KIWOOM_BRIDGE_TOKEN=
KIWOOM_UNIVERSE_SIZE=100
KIWOOM_RANKING_REFRESH_SECONDS=20
```

- [ ] **Step 2: Update `README.md`'s config table**

Read the current `README.md` first (its config table is in the "설정값" section). Add these four rows immediately after the `KIS_MAX_REQUESTS_PER_SECOND` row:

```markdown
| KIWOOM_BRIDGE_URL | http://127.0.0.1:8000 | kiwoom_bridge 프로세스 주소 (--provider kiwoom 사용 시) |
| KIWOOM_BRIDGE_TOKEN | (없음, 필수) | kiwoom_bridge와 공유하는 인증 토큰 (--provider kiwoom 사용 시 필수) |
| KIWOOM_UNIVERSE_SIZE | 100 | 거래대금 상위 몇 종목까지 추적할지 (kiwoom_bridge 경유) |
| KIWOOM_RANKING_REFRESH_SECONDS | 20 | 거래대금/업종 순위 갱신 주기(초) (kiwoom_bridge 경유) |
```

- [ ] **Step 3: Add a TODO section bullet about the bridge process**

Add this bullet to the `### TODO / 실 데이터 연동 필요 사항` section:

```markdown
- `leader_watch/providers/kiwoom_provider.py`의 `KiwoomProvider`는 별도의
  32비트 `kiwoom_bridge` 프로세스(키움증권 OpenAPI+)를 통해 동작합니다.
  `kiwoom_bridge/README.md`에 따라 32비트 환경에서 `kiwoom_bridge/bridge.py`를
  먼저 실행한 뒤 `--provider kiwoom`을 사용하세요. `kiwoom_bridge/tr_client.py`의
  TR코드/필드명은 검증되지 않은 가정입니다 — 자세한 내용은
  `docs/superpowers/specs/2026-08-13-kiwoom-provider-design.md`를 참고하세요.
  20일 동시간대 평균 거래대금/거래량과 당일 뉴스/공시 감지는 이번 범위에
  포함되지 않았습니다 (KIS 연동과 동일).
```

- [ ] **Step 4: Commit**

```bash
git add .env.example README.md
git commit -m "docs: document KiwoomProvider bridge setup and config"
```

---

### Task 10: Full test suite run and manual verification

**Files:** None — verification only.

**Interfaces:** None.

- [ ] **Step 1: Run the entire automated test suite**

Run: `pytest -v`
Expected: All tests pass, zero failures, zero errors. This includes every existing test (including the KIS integration, unaffected) plus all new `tests/leader_watch/test_kiwoom_*.py` and `tests/kiwoom_bridge/test_http_server.py`.

- [ ] **Step 2: Confirm no real network/bridge/COM access is made by the automated test suite**

Run: `pytest tests/leader_watch/ tests/kiwoom_bridge/ -v -k kiwoom` and manually confirm (by reading the test output/names) that every test exercising `KiwoomClient`/`KiwoomProvider` uses `unittest.mock.patch` on `requests.get`, and every test exercising `kiwoom_bridge/http_server.py` uses the in-memory `_FakeTrClient` with direct function calls (no socket, no `win32com`). If any test is found making a real call or importing `win32com`/`pythoncom`, STOP and fix it before proceeding.

- [ ] **Step 3: Syntax-compile-check the two win32com-dependent files**

Run: `python -m py_compile kiwoom_bridge/tr_client.py kiwoom_bridge/bridge.py`
Expected: no output, no error.

- [ ] **Step 4: Manually verify the CLI still handles missing bridge config gracefully**

Run (ensuring `KIWOOM_BRIDGE_TOKEN` is NOT set in your shell environment for this check):

```bash
python main.py --provider kiwoom --notifier console --single-tick
```

Expected: prints a clear message to stderr naming the missing environment variable, exits with code 1, no Python traceback.

- [ ] **Step 5: Manually verify `--provider mock` and `--provider real` still work unaffected**

Run: `python main.py --provider mock --notifier console --single-tick` — expect exit code 0.
Run: `python main.py --provider real --notifier console --single-tick` (with no `KIS_APP_KEY`/`KIS_APP_SECRET` set) — expect the existing KIS clean-error behavior, unchanged by this plan.

- [ ] **Step 6: Hand off the bridge's manual test protocol**

This plan's automated work ends here. The user runs `kiwoom_bridge/README.md`'s manual test protocol by hand, in their 32-bit Kiwoom OpenAPI+ environment, to verify `kiwoom_bridge/tr_client.py`'s TR codes/field names against a real login — and updates the `ASSUMPTION`-tagged constants in that file if any differ. Only after that should `python main.py --provider kiwoom` be run against the live bridge for an end-to-end check.

- [ ] **Step 7: Commit (only if Steps 1-5 required any fixes)**

If all steps passed without needing changes, there is nothing to commit for this task — it is a pure verification checkpoint.
