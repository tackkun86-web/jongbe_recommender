# RealProvider — KIS Developers API Integration (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `leader_watch/providers/real.py`'s `RealProvider` so `python main.py --provider real` fetches live KOSPI/KOSDAQ market data from the 한국투자증권(KIS) Developers Open API instead of raising `NotImplementedError`.

**Architecture:** A new `leader_watch/providers/kis/` subpackage holds a rate-limited, retry-wrapped REST client (`client.py`), OAuth token management (`auth.py`), env-driven credentials/tuning (`config.py`), and pure response-mapping functions (`mapping.py`). `providers/real.py` becomes a thin orchestrator that caches slow-changing data (trading-value ranking, sector ranking — used as a theme substitute) and refreshes fast-changing data (price/체결강도, one new 1-minute bar per code per new minute) every `get_snapshot(now)` call, assembling `StockSnapshot` objects exactly like `MockProvider` does today.

**Tech Stack:** Python 3.14, pytest, `requests` (already a dependency), stdlib `datetime`/`time`.

## Global Constraints

- Never write order/buy/sell/account-balance code. Only read-only KIS market-data endpoints (OAuth token, ranking, sector ranking, quote, minute bars) are used.
- Do not modify `leader_watch/providers/base.py`, `leader_watch/engine.py` (reuse its `call_with_retry` via import only — no edits to that file), `leader_watch/state_machine.py`, `leader_watch/scoring.py`, `leader_watch/filters.py`, `leader_watch/models.py`, `leader_watch/providers/mock.py`, `leader_watch/providers/mock_scenarios.py`.
- Do not modify repo-root `recommender.py`, `scorer.py`, `filters.py`, `notifier.py`, `scheduler.py`, `data_fetcher.py`.
- All KIS field-name/TR_ID/endpoint-path assumptions must be recorded as named constants with a comment marking them `ASSUMPTION` (per `docs/superpowers/specs/2026-08-12-real-provider-kis-design.md`, "구현 중 반드시 검증해야 할 가정") — never silently hardcoded without a comment.
- Every `StockSnapshot` returned by `RealProvider` must carry a real `timestamp` reflecting when the data was actually received/observed — never a value computed as a placeholder unrelated to the actual poll.
- Every test in this plan must pass with zero real network access and zero real KIS credentials — all HTTP calls are mocked at the `requests` boundary.
- `RealProvider()` must remain callable with **zero constructor arguments** in the common case (reading all configuration from environment variables via `load_kis_config()`), because `main.py` already instantiates it as `RealProvider()`.
- New environment variables, exact names: `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ENV`, `KIS_UNIVERSE_SIZE`, `KIS_RANKING_REFRESH_SECONDS`, `KIS_MAX_REQUESTS_PER_SECOND`.
- 20-day same-time-of-day averages (`avg_trading_value_same_time_20d`/`avg_volume_same_time_20d`) and news detection (`news_today`/`news_continuing`) are explicitly OUT OF SCOPE for this plan (per the design doc). Leave the averages as `None` (their existing `Optional` default) and always set `news_today=False`/`news_continuing=False`.

## Deviation from the design doc, decided during planning

The design doc's "가정" section flagged "배치 시세 조회 1회당 최대 종목 수 (가정: 30개)" as something to verify. During planning, the multi-code batch-quote endpoint's exact parameter shape turned out to be the single least-certain assumption of the whole integration — too risky to commit to blindly. This plan instead uses the well-documented **single-code current-price endpoint** (`inquire-price`, TR_ID `FHKST01010100`) called once per code in the tracked universe, throttled naturally by the shared rate limiter. This is slower per full universe refresh than true batching would be, but it is correct-by-construction against a stable, well-known endpoint shape instead of a guessed multi-code parameter scheme. If real testing later shows a working multi-code endpoint, swapping it in only touches `kis/client.py`'s `get_quote`/a new batch method and `providers/real.py`'s per-code loop — nothing else.

---

## File Structure

```
leader_watch/providers/
├── real.py                    # MODIFY: RealProvider(MarketDataProvider) — real implementation
└── kis/
    ├── __init__.py             # NEW: empty
    ├── config.py                # NEW: KisConfig, load_kis_config(), KisConfigError
    ├── auth.py                  # NEW: KisAuth, KisAuthError
    ├── client.py                 # NEW: KisClient, KisApiError, _RateLimiter
    └── mapping.py                 # NEW: pure functions, raw KIS dict -> StockSnapshot/MinuteBar

tests/leader_watch/
├── test_kis_config.py            # NEW
├── test_kis_auth.py               # NEW
├── test_kis_client_get.py          # NEW
├── test_kis_client_ranking.py       # NEW
├── test_kis_client_sector.py         # NEW
├── test_kis_client_quote.py           # NEW
├── test_kis_client_minute_bars.py      # NEW
├── test_kis_mapping.py                  # NEW
├── test_providers_real.py                # MODIFY: replace the two placeholder-era tests
└── test_main_cli.py                       # MODIFY: add KIS-misconfiguration handling test

main.py            # MODIFY: catch KisConfigError alongside NotImplementedError
.env.example        # MODIFY: append KIS_* variables
README.md            # MODIFY: update TODO section + config table
```

---

### Task 1: `kis/config.py` — credentials and tuning parameters

**Files:**
- Create: `leader_watch/providers/kis/__init__.py` (empty)
- Create: `leader_watch/providers/kis/config.py`
- Test: `tests/leader_watch/test_kis_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `KisConfigError(Exception)`, `KisConfig` (frozen dataclass with fields `app_key: str`, `app_secret: str`, `env: str`, `universe_size: int`, `ranking_refresh_seconds: int`, `max_requests_per_second: int`, and a `base_url` property), `load_kis_config(env: dict | None = None) -> KisConfig`. All later tasks import `KisConfig`/`load_kis_config`/`KisConfigError` from `leader_watch.providers.kis.config`.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kis_config.py
import pytest
from leader_watch.providers.kis.config import KisConfig, KisConfigError, load_kis_config


def test_missing_app_key_raises():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_SECRET": "secret"})


def test_missing_app_secret_raises():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_KEY": "key"})


def test_defaults_when_only_credentials_given():
    cfg = load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret"})
    assert cfg.app_key == "key"
    assert cfg.app_secret == "secret"
    assert cfg.env == "real"
    assert cfg.universe_size == 100
    assert cfg.ranking_refresh_seconds == 20
    assert cfg.max_requests_per_second == 15


def test_env_overrides_are_applied():
    cfg = load_kis_config(env={
        "KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret",
        "KIS_ENV": "paper", "KIS_UNIVERSE_SIZE": "50",
        "KIS_RANKING_REFRESH_SECONDS": "10", "KIS_MAX_REQUESTS_PER_SECOND": "5",
    })
    assert cfg.env == "paper"
    assert cfg.universe_size == 50
    assert cfg.ranking_refresh_seconds == 10
    assert cfg.max_requests_per_second == 5


def test_invalid_env_value_raises():
    with pytest.raises(KisConfigError):
        load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_ENV": "bogus"})


def test_base_url_for_real_env():
    cfg = load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_ENV": "real"})
    assert cfg.base_url == "https://openapi.koreainvestment.com:9443"


def test_base_url_for_paper_env():
    cfg = load_kis_config(env={"KIS_APP_KEY": "key", "KIS_APP_SECRET": "secret", "KIS_ENV": "paper"})
    assert cfg.base_url == "https://openapivts.koreainvestment.com:29443"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kis_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leader_watch.providers.kis'`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/kis/config.py
"""Environment-driven credentials and tuning parameters for the KIS Developers API client."""
from __future__ import annotations

import os
from dataclasses import dataclass


class KisConfigError(Exception):
    """Raised when required KIS credentials are missing or a setting is invalid."""


@dataclass(frozen=True)
class KisConfig:
    app_key: str
    app_secret: str
    env: str  # "real" | "paper"
    universe_size: int
    ranking_refresh_seconds: int
    max_requests_per_second: int

    @property
    def base_url(self) -> str:
        if self.env == "paper":
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"


_DEFAULTS = {
    "KIS_ENV": "real",
    "KIS_UNIVERSE_SIZE": "100",
    "KIS_RANKING_REFRESH_SECONDS": "20",
    "KIS_MAX_REQUESTS_PER_SECOND": "15",
}


def load_kis_config(env: dict | None = None) -> KisConfig:
    source = os.environ if env is None else env
    get = lambda key: source.get(key, _DEFAULTS.get(key, ""))  # noqa: E731

    app_key = get("KIS_APP_KEY")
    app_secret = get("KIS_APP_SECRET")
    if not app_key or not app_secret:
        raise KisConfigError(
            "KIS_APP_KEY and KIS_APP_SECRET must be set to use --provider real. "
            "See .env.example."
        )

    kis_env = get("KIS_ENV")
    if kis_env not in ("real", "paper"):
        raise KisConfigError(f"KIS_ENV must be 'real' or 'paper', got {kis_env!r}")

    return KisConfig(
        app_key=app_key,
        app_secret=app_secret,
        env=kis_env,
        universe_size=int(get("KIS_UNIVERSE_SIZE")),
        ranking_refresh_seconds=int(get("KIS_RANKING_REFRESH_SECONDS")),
        max_requests_per_second=int(get("KIS_MAX_REQUESTS_PER_SECOND")),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kis_config.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kis/__init__.py leader_watch/providers/kis/config.py tests/leader_watch/test_kis_config.py
git commit -m "feat(leader_watch): add KIS API credentials/config loader"
```

---

### Task 2: `kis/auth.py` — OAuth token acquisition and caching

**Files:**
- Create: `leader_watch/providers/kis/auth.py`
- Test: `tests/leader_watch/test_kis_auth.py`

**Interfaces:**
- Consumes: `KisConfig` from Task 1.
- Produces: `KisAuthError(Exception)`, `KisAuth` class with `__init__(self, config: KisConfig, now_fn: Callable[[], float] = time.time)` and `get_token(self) -> str`. Used by `kis/client.py` (Task 3).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kis_auth.py
from unittest.mock import MagicMock, patch

import pytest
from leader_watch.providers.kis.auth import KisAuth, KisAuthError
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=15)


def _ok_response(token="TOKEN123", expires_in=86400):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"access_token": token, "expires_in": expires_in, "token_type": "Bearer"}
    return resp


@patch("leader_watch.providers.kis.auth.requests.post")
def test_get_token_fetches_on_first_call(mock_post):
    mock_post.return_value = _ok_response()
    auth = KisAuth(CFG, now_fn=lambda: 1000.0)
    token = auth.get_token()
    assert token == "TOKEN123"
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    assert kwargs["json"] == {"grant_type": "client_credentials", "appkey": "key", "appsecret": "secret"}


@patch("leader_watch.providers.kis.auth.requests.post")
def test_get_token_returns_cached_token_before_expiry(mock_post):
    mock_post.return_value = _ok_response(expires_in=3600)
    clock = {"now": 1000.0}
    auth = KisAuth(CFG, now_fn=lambda: clock["now"])
    auth.get_token()
    clock["now"] = 1000.0 + 60  # well before expiry - refresh margin
    auth.get_token()
    assert mock_post.call_count == 1


@patch("leader_watch.providers.kis.auth.requests.post")
def test_get_token_refreshes_near_expiry(mock_post):
    mock_post.return_value = _ok_response(expires_in=3600)
    clock = {"now": 1000.0}
    auth = KisAuth(CFG, now_fn=lambda: clock["now"])
    auth.get_token()
    clock["now"] = 1000.0 + 3600 - 200  # inside the 300s refresh margin
    auth.get_token()
    assert mock_post.call_count == 2


@patch("leader_watch.providers.kis.auth.requests.post")
def test_non_200_raises_kis_auth_error(mock_post):
    resp = MagicMock(status_code=401, text="unauthorized")
    mock_post.return_value = resp
    auth = KisAuth(CFG, now_fn=lambda: 1000.0)
    with pytest.raises(KisAuthError):
        auth.get_token()


@patch("leader_watch.providers.kis.auth.requests.post")
def test_missing_fields_in_response_raises_kis_auth_error(mock_post):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"token_type": "Bearer"}
    mock_post.return_value = resp
    auth = KisAuth(CFG, now_fn=lambda: 1000.0)
    with pytest.raises(KisAuthError):
        auth.get_token()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kis_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leader_watch.providers.kis.auth'`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/kis/auth.py
"""OAuth token acquisition and in-process caching for the KIS Developers API."""
from __future__ import annotations

import time
from typing import Callable

import requests

from leader_watch.providers.kis.config import KisConfig

_TOKEN_PATH = "/oauth2/tokenP"
_REFRESH_MARGIN_SECONDS = 300  # refresh this many seconds before actual expiry


class KisAuthError(Exception):
    """Raised when the KIS OAuth token endpoint fails or returns an unexpected shape."""


class KisAuth:
    def __init__(self, config: KisConfig, now_fn: Callable[[], float] = time.time) -> None:
        self._config = config
        self._now_fn = now_fn
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    def get_token(self) -> str:
        if self._access_token is not None and self._now_fn() < self._expires_at - _REFRESH_MARGIN_SECONDS:
            return self._access_token
        self._refresh()
        assert self._access_token is not None
        return self._access_token

    def _refresh(self) -> None:
        response = requests.post(
            f"{self._config.base_url}{_TOKEN_PATH}",
            json={
                "grant_type": "client_credentials",
                "appkey": self._config.app_key,
                "appsecret": self._config.app_secret,
            },
            timeout=10,
        )
        if response.status_code != 200:
            raise KisAuthError(f"KIS token request failed with status {response.status_code}: {response.text}")
        body = response.json()
        token = body.get("access_token")
        expires_in = body.get("expires_in")
        if not token or not isinstance(expires_in, (int, float)):
            raise KisAuthError(f"KIS token response missing access_token/expires_in: {body}")
        self._access_token = token
        self._expires_at = self._now_fn() + float(expires_in)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kis_auth.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kis/auth.py tests/leader_watch/test_kis_auth.py
git commit -m "feat(leader_watch): add KIS OAuth token acquisition and caching"
```

---

### Task 3: `kis/client.py` — rate limiter and authenticated GET wrapper

**Files:**
- Create: `leader_watch/providers/kis/client.py`
- Test: `tests/leader_watch/test_kis_client_get.py`

**Interfaces:**
- Consumes: `KisConfig` (Task 1), `KisAuth` (Task 2).
- Produces: `KisApiError(Exception)`, `KisClient` class with `__init__(self, config: KisConfig, auth: KisAuth)` and internal `_get(self, path: str, tr_id: str, params: dict) -> dict`. Tasks 4-7 append endpoint methods to this same class/file.

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kis_client_get.py
from unittest.mock import MagicMock, patch

import pytest
from leader_watch.providers.kis.client import KisApiError, KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


def _ok_response(output=None):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상", "output": output if output is not None else []}
    return resp


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_attaches_correct_headers_and_url(mock_get):
    mock_get.return_value = _ok_response(output={"foo": "bar"})
    client = KisClient(CFG, _FakeAuth())
    body = client._get("/uapi/domestic-stock/v1/quotations/inquire-price", tr_id="FHKST01010100", params={"a": "b"})
    assert body["output"] == {"foo": "bar"}
    args, kwargs = mock_get.call_args
    assert args[0] == "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
    assert kwargs["headers"]["authorization"] == "Bearer FAKE_TOKEN"
    assert kwargs["headers"]["appkey"] == "key"
    assert kwargs["headers"]["appsecret"] == "secret"
    assert kwargs["headers"]["tr_id"] == "FHKST01010100"
    assert kwargs["params"] == {"a": "b"}


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_raises_on_non_200(mock_get):
    resp = MagicMock(status_code=500, text="server error")
    mock_get.return_value = resp
    client = KisClient(CFG, _FakeAuth())
    with pytest.raises(KisApiError):
        client._get("/some/path", tr_id="X", params={})


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_raises_on_nonzero_rt_cd(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "1", "msg1": "실패"}
    mock_get.return_value = resp
    client = KisClient(CFG, _FakeAuth())
    with pytest.raises(KisApiError):
        client._get("/some/path", tr_id="X", params={})


@patch("leader_watch.providers.kis.client.time.sleep")
@patch("leader_watch.providers.kis.client.requests.get")
def test_rate_limiter_sleeps_between_rapid_calls(mock_get, mock_sleep):
    mock_get.return_value = _ok_response()
    slow_cfg = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=2)
    client = KisClient(slow_cfg, _FakeAuth())
    client._get("/p", tr_id="X", params={})
    client._get("/p", tr_id="X", params={})
    assert mock_sleep.call_count >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kis_client_get.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leader_watch.providers.kis.client'`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/kis/client.py
"""Rate-limited, authenticated HTTP client for the KIS Developers API.

Endpoint methods are appended to this file/class across several plan tasks;
each method's TR_ID and path are commented `ASSUMPTION` where the exact
value could not be verified without a live account — see
docs/superpowers/specs/2026-08-12-real-provider-kis-design.md.
"""
from __future__ import annotations

import time
from typing import Callable

import requests

from leader_watch.providers.kis.auth import KisAuth
from leader_watch.providers.kis.config import KisConfig


class KisApiError(Exception):
    """Raised when a KIS REST call returns a non-200 status or a non-zero rt_cd."""


class _RateLimiter:
    def __init__(
        self,
        max_requests_per_second: int,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._min_interval = 1.0 / max_requests_per_second
        self._sleep_fn = sleep_fn
        self._now_fn = now_fn
        self._last_call_at: float | None = None

    def wait(self) -> None:
        now = self._now_fn()
        if self._last_call_at is not None:
            elapsed = now - self._last_call_at
            remaining = self._min_interval - elapsed
            if remaining > 0:
                self._sleep_fn(remaining)
        self._last_call_at = self._now_fn()


class KisClient:
    def __init__(self, config: KisConfig, auth: KisAuth) -> None:
        self._config = config
        self._auth = auth
        self._rate_limiter = _RateLimiter(config.max_requests_per_second)

    def _get(self, path: str, tr_id: str, params: dict) -> dict:
        self._rate_limiter.wait()
        token = self._auth.get_token()
        response = requests.get(
            f"{self._config.base_url}{path}",
            headers={
                "authorization": f"Bearer {token}",
                "appkey": self._config.app_key,
                "appsecret": self._config.app_secret,
                "tr_id": tr_id,
                "custtype": "P",
            },
            params=params,
            timeout=10,
        )
        if response.status_code != 200:
            raise KisApiError(f"KIS API call to {path} failed with status {response.status_code}: {response.text}")
        body = response.json()
        if body.get("rt_cd") != "0":
            raise KisApiError(f"KIS API call to {path} returned rt_cd={body.get('rt_cd')}: {body.get('msg1')}")
        return body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kis_client_get.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kis/client.py tests/leader_watch/test_kis_client_get.py
git commit -m "feat(leader_watch): add KIS rate-limited authenticated GET client"
```

---

### Task 4: `kis/client.py` — trading-value ranking endpoint

**Files:**
- Modify: `leader_watch/providers/kis/client.py`
- Test: `tests/leader_watch/test_kis_client_ranking.py`

**Interfaces:**
- Consumes: `KisClient._get` (Task 3).
- Produces: `KisClient.get_trading_value_ranking(self, count: int) -> list[dict]`. Used by `providers/real.py` (Task 9) via `kis/mapping.py`'s `parse_ranking_row` (Task 8).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kis_client_ranking.py
from unittest.mock import MagicMock, patch

from leader_watch.providers.kis.client import KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


def _rows(n):
    return [{"stck_shrn_iscd": f"00000{i}", "hts_kor_isnm": f"종목{i}", "data_rank": str(i + 1)} for i in range(n)]


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_trading_value_ranking_returns_top_n_rows(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상", "output": _rows(10)}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    rows = client.get_trading_value_ranking(3)

    assert len(rows) == 3
    assert rows[0]["stck_shrn_iscd"] == "000000"
    args, kwargs = mock_get.call_args
    assert kwargs["headers"]["tr_id"] == "FHPST01710000"
    assert "/uapi/domestic-stock/v1/quotations/volume-rank" in args[0]


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_trading_value_ranking_empty_output(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상", "output": []}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    rows = client.get_trading_value_ranking(50)

    assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kis_client_ranking.py -v`
Expected: FAIL — `AttributeError: 'KisClient' object has no attribute 'get_trading_value_ranking'`

- [ ] **Step 3: Append to `leader_watch/providers/kis/client.py`**

```python
    def get_trading_value_ranking(self, count: int) -> list[dict]:
        """Top `count` KOSPI/KOSDAQ stocks ranked by today's cumulative trading value.

        ASSUMPTION (verify against real KIS docs): TR_ID FHPST01710000,
        path /uapi/domestic-stock/v1/quotations/volume-rank,
        FID_BLNG_CLS_CODE="3" sorts by trading value (거래대금) rather than
        volume. Returns raw KIS response rows unmodified — mapping into
        StockSnapshot fields happens in kis/mapping.py.
        """
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/volume-rank",
            tr_id="FHPST01710000",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_COND_SCR_DIV_CODE": "20171",
                "FID_INPUT_ISCD": "0000",
                "FID_DIV_CLS_CODE": "0",
                "FID_BLNG_CLS_CODE": "3",
                "FID_TRGT_CLS_CODE": "111111111",
                "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                "FID_INPUT_PRICE_1": "",
                "FID_INPUT_PRICE_2": "",
                "FID_VOL_CNT": "",
                "FID_INPUT_DATE_1": "",
            },
        )
        return body.get("output", [])[:count]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kis_client_ranking.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kis/client.py tests/leader_watch/test_kis_client_ranking.py
git commit -m "feat(leader_watch): add KIS trading-value ranking endpoint"
```

---

### Task 5: `kis/client.py` — sector (업종) ranking endpoint

**Files:**
- Modify: `leader_watch/providers/kis/client.py`
- Test: `tests/leader_watch/test_kis_client_sector.py`

**Interfaces:**
- Consumes: `KisClient._get` (Task 3).
- Produces: `KisClient.get_sector_ranking(self) -> list[dict]`. Used by `providers/real.py` (Task 9) via `kis/mapping.py`'s `parse_sector_ranking` (Task 8) as the theme-rank substitute (see design doc "테마 대체" section).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kis_client_sector.py
from unittest.mock import MagicMock, patch

from leader_watch.providers.kis.client import KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_sector_ranking_returns_rows(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "rt_cd": "0", "msg1": "정상",
        "output": [
            {"hts_kor_isnm": "반도체", "data_rank": "1"},
            {"hts_kor_isnm": "2차전지", "data_rank": "2"},
        ],
    }
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    rows = client.get_sector_ranking()

    assert len(rows) == 2
    assert rows[0]["hts_kor_isnm"] == "반도체"
    args, kwargs = mock_get.call_args
    assert kwargs["headers"]["tr_id"] == "FHPST01730000"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kis_client_sector.py -v`
Expected: FAIL — `AttributeError: 'KisClient' object has no attribute 'get_sector_ranking'`

- [ ] **Step 3: Append to `leader_watch/providers/kis/client.py`**

```python
    def get_sector_ranking(self) -> list[dict]:
        """All KRX sector (업종) names ranked by today's change percent.

        Used as a theme substitute (no KIS endpoint returns 테마-level
        groupings like 반도체/2차전지 with trading-value rank — see
        docs/superpowers/specs/2026-08-12-real-provider-kis-design.md,
        "테마 대체" section). Each stock's own sector name comes back on its
        individual quote response (kis/client.py get_quote), and is looked
        up against the rank map built from this endpoint's output.

        ASSUMPTION (verify against real KIS docs): TR_ID FHPST01730000,
        path /uapi/domestic-stock/v1/ranking/industry-fluctuation-rate.
        """
        body = self._get(
            "/uapi/domestic-stock/v1/ranking/industry-fluctuation-rate",
            tr_id="FHPST01730000",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": "0001",
                "FID_DIV_CLS_CODE": "0",
                "FID_RANK_SORT_CLS_CODE": "0",
            },
        )
        return body.get("output", [])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kis_client_sector.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kis/client.py tests/leader_watch/test_kis_client_sector.py
git commit -m "feat(leader_watch): add KIS sector ranking endpoint (theme substitute)"
```

---

### Task 6: `kis/client.py` — single-stock quote endpoint

**Files:**
- Modify: `leader_watch/providers/kis/client.py`
- Test: `tests/leader_watch/test_kis_client_quote.py`

**Interfaces:**
- Consumes: `KisClient._get` (Task 3).
- Produces: `KisClient.get_quote(self, code: str) -> dict`. Used by `providers/real.py` (Task 9) via `kis/mapping.py`'s `quote_to_snapshot` (Task 8).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kis_client_quote.py
from unittest.mock import MagicMock, patch

from leader_watch.providers.kis.client import KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_quote_returns_output_dict(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상", "output": {"stck_prpr": "70000"}}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    quote = client.get_quote("005930")

    assert quote == {"stck_prpr": "70000"}
    args, kwargs = mock_get.call_args
    assert kwargs["headers"]["tr_id"] == "FHKST01010100"
    assert kwargs["params"]["FID_INPUT_ISCD"] == "005930"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_quote_missing_output_returns_empty_dict(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상"}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    quote = client.get_quote("005930")

    assert quote == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kis_client_quote.py -v`
Expected: FAIL — `AttributeError: 'KisClient' object has no attribute 'get_quote'`

- [ ] **Step 3: Append to `leader_watch/providers/kis/client.py`**

```python
    def get_quote(self, code: str) -> dict:
        """Current price/OHLC/cumulative-volume snapshot for a single stock code.

        ASSUMPTION (verify against real KIS docs): TR_ID FHKST01010100,
        path /uapi/domestic-stock/v1/quotations/inquire-price.
        """
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id="FHKST01010100",
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
            },
        )
        return body.get("output", {})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kis_client_quote.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kis/client.py tests/leader_watch/test_kis_client_quote.py
git commit -m "feat(leader_watch): add KIS single-stock current-price endpoint"
```

---

### Task 7: `kis/client.py` — minute-bar endpoint

**Files:**
- Modify: `leader_watch/providers/kis/client.py`
- Test: `tests/leader_watch/test_kis_client_minute_bars.py`

**Interfaces:**
- Consumes: `KisClient._get` (Task 3).
- Produces: `KisClient.get_minute_bars(self, code: str, reference_time: str) -> list[dict]`. `reference_time` is an `HHMMSS` string. Used by `providers/real.py` (Task 9) via `kis/mapping.py`'s `parse_minute_bar` (Task 8).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kis_client_minute_bars.py
from unittest.mock import MagicMock, patch

from leader_watch.providers.kis.client import KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_minute_bars_returns_output2_rows(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "rt_cd": "0", "msg1": "정상",
        "output1": {"some": "meta"},
        "output2": [{"stck_cntg_hour": "093000", "stck_prpr": "70500"}],
    }
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    bars = client.get_minute_bars("005930", "093000")

    assert bars == [{"stck_cntg_hour": "093000", "stck_prpr": "70500"}]
    args, kwargs = mock_get.call_args
    assert kwargs["headers"]["tr_id"] == "FHKST03010200"
    assert kwargs["params"]["FID_INPUT_ISCD"] == "005930"
    assert kwargs["params"]["FID_INPUT_HOUR_1"] == "093000"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_minute_bars_missing_output2_returns_empty_list(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상"}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    bars = client.get_minute_bars("005930", "093000")

    assert bars == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kis_client_minute_bars.py -v`
Expected: FAIL — `AttributeError: 'KisClient' object has no attribute 'get_minute_bars'`

- [ ] **Step 3: Append to `leader_watch/providers/kis/client.py`**

```python
    def get_minute_bars(self, code: str, reference_time: str) -> list[dict]:
        """1-minute OHLCV bars for `code` up to `reference_time` (HHMMSS), most-recent first.

        ASSUMPTION (verify against real KIS docs): TR_ID FHKST03010200,
        path /uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice,
        bar rows returned under the "output2" key (KIS convention: "output1"
        holds per-request metadata, "output2" holds the time series).
        """
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            tr_id="FHKST03010200",
            params={
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_HOUR_1": reference_time,
                "FID_PW_DATA_INCU_YN": "N",
            },
        )
        return body.get("output2", [])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kis_client_minute_bars.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kis/client.py tests/leader_watch/test_kis_client_minute_bars.py
git commit -m "feat(leader_watch): add KIS minute-bar endpoint"
```

---

### Task 8: `kis/mapping.py` — pure response-to-model mapping functions

**Files:**
- Create: `leader_watch/providers/kis/mapping.py`
- Test: `tests/leader_watch/test_kis_mapping.py`

**Interfaces:**
- Consumes: `StockSnapshot`, `MinuteBar` from `leader_watch.models` (existing, unmodified).
- Produces: `parse_ranking_row(row: dict) -> tuple[str, str, int]` (code, name, rank), `parse_sector_ranking(rows: list[dict]) -> dict[str, int]` (sector name -> rank), `quote_to_snapshot(quote: dict, code: str, name: str, market: str, received_at: datetime.datetime, market_rank: int, theme_rank_by_sector: dict[str, int]) -> StockSnapshot`, `parse_minute_bar(row: dict, reference_date: datetime.date) -> MinuteBar`. Used by `providers/real.py` (Task 9).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_kis_mapping.py
import datetime

from leader_watch.providers.kis.mapping import (
    parse_minute_bar,
    parse_ranking_row,
    parse_sector_ranking,
    quote_to_snapshot,
)


def test_parse_ranking_row():
    row = {"stck_shrn_iscd": "005930", "hts_kor_isnm": "삼성전자", "data_rank": "3"}
    code, name, rank = parse_ranking_row(row)
    assert code == "005930"
    assert name == "삼성전자"
    assert rank == 3


def test_parse_sector_ranking_uses_data_rank_when_present():
    rows = [
        {"hts_kor_isnm": "반도체", "data_rank": "1"},
        {"hts_kor_isnm": "2차전지", "data_rank": "2"},
    ]
    ranks = parse_sector_ranking(rows)
    assert ranks == {"반도체": 1, "2차전지": 2}


def test_parse_sector_ranking_falls_back_to_position_when_rank_missing():
    rows = [
        {"hts_kor_isnm": "반도체"},
        {"hts_kor_isnm": "2차전지"},
    ]
    ranks = parse_sector_ranking(rows)
    assert ranks == {"반도체": 1, "2차전지": 2}


def _quote(**overrides):
    base = {
        "stck_prpr": "70500",
        "stck_oprc": "70000",
        "stck_hgpr": "71000",
        "stck_lwpr": "69800",
        "prdy_vrss": "500",
        "acml_vol": "12345678",
        "acml_tr_pbmn": "870123456789",
        "bstp_kor_isnm": "반도체",
        "iscd_stat_cls_code": "00",
    }
    base.update(overrides)
    return base


def test_quote_to_snapshot_maps_core_fields():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={"반도체": 1},
    )
    assert snap.code == "005930"
    assert snap.current_price == 70500.0
    assert snap.prev_close == 70000.0  # 70500 - 500
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


def test_quote_to_snapshot_execution_strength_defaults_to_neutral_when_absent():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.execution_strength == 100.0


def test_quote_to_snapshot_uses_execution_strength_when_present():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(pgtr_symp_str="145.3"), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.execution_strength == 145.3


def test_quote_to_snapshot_theme_none_when_sector_missing():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(bstp_kor_isnm=""), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={"반도체": 1},
    )
    assert snap.theme is None
    assert snap.theme_trading_value_rank is None


def test_quote_to_snapshot_maps_administrative_status_code():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(iscd_stat_cls_code="51"), code="000001", name="관리종목", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_administrative is True
    assert snap.is_investment_alert is False
    assert snap.is_trading_halted is False


def test_quote_to_snapshot_maps_investment_alert_status_code():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(iscd_stat_cls_code="52"), code="000002", name="투자위험", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_investment_alert is True


def test_quote_to_snapshot_maps_trading_halted_status_code():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(iscd_stat_cls_code="58"), code="000003", name="거래정지", market="KOSPI",
        received_at=now, market_rank=90, theme_rank_by_sector={},
    )
    assert snap.is_trading_halted is True


def test_quote_to_snapshot_normal_status_code_excludes_nothing():
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snap = quote_to_snapshot(
        _quote(iscd_stat_cls_code="00"), code="005930", name="삼성전자", market="KOSPI",
        received_at=now, market_rank=5, theme_rank_by_sector={},
    )
    assert snap.is_administrative is False
    assert snap.is_investment_alert is False
    assert snap.is_trading_halted is False


def test_parse_minute_bar():
    row = {"stck_cntg_hour": "093000", "stck_oprc": "70000", "stck_hgpr": "70200", "stck_lwpr": "69900", "stck_prpr": "70100", "cntg_vol": "12345"}
    bar = parse_minute_bar(row, reference_date=datetime.date(2026, 8, 12))
    assert bar.timestamp == datetime.datetime(2026, 8, 12, 9, 30)
    assert bar.open == 70000.0
    assert bar.high == 70200.0
    assert bar.low == 69900.0
    assert bar.close == 70100.0
    assert bar.volume == 12345
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_kis_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leader_watch.providers.kis.mapping'`

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/kis/mapping.py
"""Pure functions mapping raw KIS API response dicts to StockSnapshot/MinuteBar.

All field-name constants below are the implementer's best-effort mapping to
the commonly documented KIS Developers 국내주식 API response schema. They are
named `ASSUMPTION`s — see
docs/superpowers/specs/2026-08-12-real-provider-kis-design.md,
"구현 중 반드시 검증해야 할 가정". If your account's actual response uses
different field names, change ONLY the constants below; the mapping
functions' logic does not need to change.
"""
from __future__ import annotations

import datetime

from leader_watch.models import MinuteBar, StockSnapshot

# --- ASSUMPTION: quote/ranking field names ---
_F_CODE = "stck_shrn_iscd"
_F_NAME = "hts_kor_isnm"
_F_RANK = "data_rank"

_F_CURRENT_PRICE = "stck_prpr"
_F_OPEN_PRICE = "stck_oprc"
_F_HIGH_PRICE = "stck_hgpr"
_F_LOW_PRICE = "stck_lwpr"
_F_PREV_DIFF = "prdy_vrss"  # signed change vs previous close; prev_close is derived from this
_F_ACML_VOLUME = "acml_vol"
_F_ACML_TRADING_VALUE = "acml_tr_pbmn"
_F_SECTOR_NAME = "bstp_kor_isnm"
_F_STATUS_CODE = "iscd_stat_cls_code"
_F_EXECUTION_STRENGTH = "pgtr_symp_str"  # falls back to neutral 100.0 if absent/blank

# --- ASSUMPTION: iscd_stat_cls_code -> exclusion flag, per commonly documented
# KIS 종목상태구분코드 values. Verify the exact code set against real docs. ---
_ADMINISTRATIVE_CODES = {"51"}
_INVESTMENT_ALERT_CODES = {"52", "53", "54"}
_TRADING_HALTED_CODES = {"58"}

# --- ASSUMPTION: minute-bar field names ---
_F_BAR_TIME = "stck_cntg_hour"  # HHMMSS
_F_BAR_OPEN = "stck_oprc"
_F_BAR_HIGH = "stck_hgpr"
_F_BAR_LOW = "stck_lwpr"
_F_BAR_CLOSE = "stck_prpr"
_F_BAR_VOLUME = "cntg_vol"


def parse_ranking_row(row: dict) -> tuple[str, str, int]:
    code = row[_F_CODE]
    name = row[_F_NAME]
    rank = int(row[_F_RANK])
    return code, name, rank


def parse_sector_ranking(rows: list[dict]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for position, row in enumerate(rows, start=1):
        name = row[_F_NAME]
        raw_rank = row.get(_F_RANK)
        ranks[name] = int(raw_rank) if raw_rank else position
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
    current_price = float(quote[_F_CURRENT_PRICE])
    prev_diff = float(quote.get(_F_PREV_DIFF, 0.0))
    prev_close = current_price - prev_diff

    status_code = str(quote.get(_F_STATUS_CODE, ""))
    sector_name = quote.get(_F_SECTOR_NAME) or None
    theme_rank = theme_rank_by_sector.get(sector_name) if sector_name else None

    execution_strength_raw = quote.get(_F_EXECUTION_STRENGTH)
    execution_strength = (
        float(execution_strength_raw) if execution_strength_raw not in (None, "") else 100.0
    )

    return StockSnapshot(
        code=code,
        name=name,
        market=market,
        timestamp=received_at,
        current_price=current_price,
        prev_close=prev_close,
        open_price=float(quote[_F_OPEN_PRICE]),
        high_price=float(quote[_F_HIGH_PRICE]),
        low_price=float(quote[_F_LOW_PRICE]),
        cum_volume=int(float(quote[_F_ACML_VOLUME])),
        cum_trading_value=float(quote[_F_ACML_TRADING_VALUE]),
        market_trading_value_rank=market_rank,
        execution_strength=execution_strength,
        theme=sector_name,
        theme_trading_value_rank=theme_rank,
        news_today=False,
        news_continuing=False,
        is_administrative=status_code in _ADMINISTRATIVE_CODES,
        is_investment_alert=status_code in _INVESTMENT_ALERT_CODES,
        is_trading_halted=status_code in _TRADING_HALTED_CODES,
    )


def parse_minute_bar(row: dict, reference_date: datetime.date) -> MinuteBar:
    time_str = str(row[_F_BAR_TIME]).zfill(6)
    hour, minute = int(time_str[0:2]), int(time_str[2:4])
    timestamp = datetime.datetime(reference_date.year, reference_date.month, reference_date.day, hour, minute)
    return MinuteBar(
        timestamp=timestamp,
        open=float(row[_F_BAR_OPEN]),
        high=float(row[_F_BAR_HIGH]),
        low=float(row[_F_BAR_LOW]),
        close=float(row[_F_BAR_CLOSE]),
        volume=int(float(row[_F_BAR_VOLUME])),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_kis_mapping.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/kis/mapping.py tests/leader_watch/test_kis_mapping.py
git commit -m "feat(leader_watch): add KIS response mapping to StockSnapshot/MinuteBar"
```

---

### Task 9: `providers/real.py` — RealProvider orchestrator

**Files:**
- Modify: `leader_watch/providers/real.py` (full rewrite)
- Modify: `tests/leader_watch/test_providers_real.py` (full rewrite — the two placeholder-era tests no longer apply since `RealProvider` is no longer a stub)

**Interfaces:**
- Consumes: `KisConfig`/`load_kis_config`/`KisConfigError` (Task 1), `KisAuth` (Task 2), `KisClient`/`KisApiError` (Tasks 3-7), `parse_ranking_row`/`parse_sector_ranking`/`quote_to_snapshot`/`parse_minute_bar` (Task 8), `call_with_retry` from `leader_watch.engine` (existing, unmodified — import only), `MarketDataProvider` (existing).
- Produces: `RealProvider(MarketDataProvider)` with `__init__(self, config: KisConfig | None = None)` (constructs its own `KisAuth`/`KisClient` from `config` or `load_kis_config()` if `config` is `None`) and `get_snapshot(self, now: datetime.datetime) -> list[StockSnapshot]`. Consumed by `main.py` (Task 10, unchanged call site `RealProvider()`).

- [ ] **Step 1: Write the failing test**

```python
# tests/leader_watch/test_providers_real.py
import datetime

import pytest
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.kis.client import KisApiError
from leader_watch.providers.kis.config import KisConfig
from leader_watch.providers.real import RealProvider

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


@pytest.fixture
def _no_real_sleep(monkeypatch):
    """RealProvider wraps each KIS call in leader_watch.engine.call_with_retry, whose
    default backoff sleeps for real. Tests that deliberately trigger repeated
    failures (exhausting all retry attempts) patch that sleep to keep the test
    fast, matching the existing convention in tests/leader_watch/test_engine.py
    (which passes base_delay_seconds=0 directly to call_with_retry — not an
    option here since RealProvider calls it internally with its default)."""
    monkeypatch.setattr("leader_watch.engine.time.sleep", lambda seconds: None)


class _FakeClient:
    """Stands in for KisClient — RealProvider only calls these four methods."""

    def __init__(self):
        self.ranking_calls = 0
        self.sector_calls = 0
        self.quote_calls = []
        self.minute_bar_calls = []
        self.ranking_rows = [
            {"stck_shrn_iscd": "005930", "hts_kor_isnm": "삼성전자", "data_rank": "1"},
        ]
        self.sector_rows = [{"hts_kor_isnm": "반도체", "data_rank": "1"}]
        self.quote_by_code = {
            "005930": {
                "stck_prpr": "70500", "stck_oprc": "70000", "stck_hgpr": "71000", "stck_lwpr": "69800",
                "prdy_vrss": "500", "acml_vol": "1000000", "acml_tr_pbmn": "70000000000",
                "bstp_kor_isnm": "반도체", "iscd_stat_cls_code": "00",
            },
        }
        self.minute_bar_by_code = {
            "005930": [{"stck_cntg_hour": "093000", "stck_oprc": "70000", "stck_hgpr": "70200", "stck_lwpr": "69900", "stck_prpr": "70100", "cntg_vol": "12345"}],
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
            raise KisApiError(f"simulated failure for {code}")
        return self.quote_by_code.get(code, {})

    def get_minute_bars(self, code, reference_time):
        self.minute_bar_calls.append((code, reference_time))
        return self.minute_bar_by_code.get(code, [])


def _provider_with_fake_client():
    provider = RealProvider(config=CFG)
    fake_client = _FakeClient()
    provider._client = fake_client
    return provider, fake_client


def test_real_provider_is_a_market_data_provider():
    provider, _ = _provider_with_fake_client()
    assert isinstance(provider, MarketDataProvider)


def test_get_snapshot_returns_snapshot_per_ranked_code():
    provider, client = _provider_with_fake_client()
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert isinstance(snap, StockSnapshot)
    assert snap.code == "005930"
    assert snap.market_trading_value_rank == 1
    assert snap.theme == "반도체"
    assert snap.theme_trading_value_rank == 1
    assert snap.timestamp == now


def test_get_snapshot_includes_minute_bars():
    provider, client = _provider_with_fake_client()
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert len(snapshots[0].minute_bars_1m) == 1
    assert isinstance(snapshots[0].minute_bars_1m[0], MinuteBar)


def test_get_snapshot_does_not_refetch_minute_bar_within_same_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 30))
    assert len(client.minute_bar_calls) == 1


def test_get_snapshot_refetches_minute_bar_on_new_minute():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 31, 0))
    assert len(client.minute_bar_calls) == 2


def test_get_snapshot_accumulates_minute_bars_across_ticks():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    snapshots = provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 31, 0))
    assert len(snapshots[0].minute_bars_1m) == 2


def test_get_snapshot_does_not_refetch_ranking_within_refresh_window():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 5))
    assert client.ranking_calls == 1
    assert client.sector_calls == 1


def test_get_snapshot_refetches_ranking_after_refresh_window_elapses():
    provider, client = _provider_with_fake_client()
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 0))
    provider.get_snapshot(datetime.datetime(2026, 8, 12, 9, 30, 25))  # > 20s KIS_RANKING_REFRESH_SECONDS
    assert client.ranking_calls == 2
    assert client.sector_calls == 2


@pytest.mark.usefixtures("_no_real_sleep")
def test_get_snapshot_skips_codes_whose_quote_fails():
    provider, client = _provider_with_fake_client()
    client.quote_should_fail_for.add("005930")
    now = datetime.datetime(2026, 8, 12, 9, 30)
    snapshots = provider.get_snapshot(now)
    assert snapshots == []


def test_constructor_uses_load_kis_config_when_no_config_given(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "envkey")
    monkeypatch.setenv("KIS_APP_SECRET", "envsecret")
    provider = RealProvider()
    assert provider._config.app_key == "envkey"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_providers_real.py -v`
Expected: FAIL — `RealProvider.get_snapshot` still raises `NotImplementedError` (old stub behavior)

- [ ] **Step 3: Write minimal implementation**

```python
# leader_watch/providers/real.py
"""RealProvider — orchestrates the KIS Developers API client into a MarketDataProvider.

Implements the caching/staleness policy from
docs/superpowers/specs/2026-08-12-real-provider-kis-design.md ("데이터 흐름 & 캐싱
정책"): ranking/sector data is refreshed on a slow cadence, quotes are fetched
fresh every tick (rate-limited by KisClient), and minute bars are fetched only
once per new minute per code.

Note on nested retry: each individual KIS network call inside this module is
wrapped with `leader_watch.engine.call_with_retry` (3 attempts, exponential
backoff), and `engine.py`'s own `run_once` separately wraps the whole
`get_snapshot()` call the same way. This is intentional, not a mistake — both
layers already exist in reviewed code and both are bounded (never infinite),
so a persistent outage fails within a bounded number of attempts either way.
"""
from __future__ import annotations

import datetime

from leader_watch.engine import call_with_retry
from leader_watch.models import MinuteBar, StockSnapshot
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.kis.auth import KisAuth
from leader_watch.providers.kis.client import KisApiError, KisClient
from leader_watch.providers.kis.config import KisConfig, load_kis_config
from leader_watch.providers.kis.mapping import (
    parse_minute_bar,
    parse_ranking_row,
    parse_sector_ranking,
    quote_to_snapshot,
)

# ASSUMPTION: the ranking/quote endpoints used here do not distinguish
# KOSPI vs KOSDAQ in their response; every tracked stock is labeled KOSPI
# until a real account confirms otherwise.
_MARKET = "KOSPI"


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


class RealProvider(MarketDataProvider):
    def __init__(self, config: KisConfig | None = None) -> None:
        self._config = config or load_kis_config()
        self._auth = KisAuth(self._config)
        self._client = KisClient(self._config, self._auth)

        self._ranking_cache: list[tuple[str, str, int]] = []
        self._ranking_cache_at: datetime.datetime | None = None
        self._sector_rank_cache: dict[str, int] = {}
        self._sector_rank_cache_at: datetime.datetime | None = None

        self._bars_1m: dict[str, list[MinuteBar]] = {}
        self._last_bar_minute: dict[str, tuple[int, int]] = {}

    def _refresh_ranking_if_stale(self, now: datetime.datetime) -> None:
        # Staleness is measured against the tick's own `now` (not real wall-clock
        # time.time()) so this is deterministic and testable with simulated
        # timestamps, consistent with `_update_minute_bar` below.
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
        try:
            rows = call_with_retry(lambda: self._client.get_minute_bars(code, now.strftime("%H%M%S")))
        except KisApiError:
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
            except KisApiError:
                continue

            self._update_minute_bar(code, now)
            bars_1m = self._bars_1m.get(code, [])
            bars_5m = _aggregate_5m(bars_1m)

            snapshot = quote_to_snapshot(
                quote,
                code=code,
                name=name,
                market=_MARKET,
                received_at=now,
                market_rank=rank,
                theme_rank_by_sector=self._sector_rank_cache,
            )
            snapshot.minute_bars_1m = bars_1m
            snapshot.minute_bars_5m = bars_5m
            snapshots.append(snapshot)

        return snapshots
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_providers_real.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add leader_watch/providers/real.py tests/leader_watch/test_providers_real.py
git commit -m "feat(leader_watch): implement RealProvider against the KIS Developers API"
```

---

### Task 10: `main.py` — handle missing KIS credentials cleanly

**Files:**
- Modify: `main.py`
- Modify: `tests/leader_watch/test_main_cli.py`

**Interfaces:**
- Consumes: `KisConfigError` from `leader_watch.providers.kis.config` (Task 1).
- Produces: no new public interface — `leader_watch_main` now also catches `KisConfigError` (raised by `RealProvider()`'s constructor when `KIS_APP_KEY`/`KIS_APP_SECRET` are missing) and exits with a clear message instead of a traceback.

- [ ] **Step 1: Write the failing test**

Read the existing `tests/leader_watch/test_main_cli.py` first, then add this test to it (do not remove the existing tests):

```python
# append to tests/leader_watch/test_main_cli.py
from leader_watch.providers.kis.config import KisConfigError


def test_leader_watch_main_reports_missing_kis_credentials_without_traceback(monkeypatch, capsys):
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_APP_SECRET", raising=False)
    exit_code = leader_watch_main(["--provider", "real", "--notifier", "console", "--single-tick"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "KIS_APP_KEY" in captured.err or "KIS" in captured.err
    assert "Traceback" not in captured.err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/leader_watch/test_main_cli.py -v`
Expected: FAIL — `KisConfigError` propagates out of `leader_watch_main` uncaught (pytest reports it as an unhandled exception, not exit code 1)

- [ ] **Step 3: Modify `main.py`**

Add the import and a second `except` clause:

```python
from leader_watch.providers.kis.config import KisConfigError
```

(add this import alongside the existing `leader_watch.*` imports, in the same block as `from leader_watch.providers.real import RealProvider`)

Change the `try/except` block inside `leader_watch_main` from:

```python
    try:
        if args.single_tick:
            now = datetime.datetime.now(ZoneInfo(config.market_timezone)).replace(tzinfo=None)
            engine.run_once(now)
        else:
            engine.run()
    except NotImplementedError as exc:
        # `--provider real` is a stub until a real-time data source is wired up.
        # Report it as a configuration problem instead of dumping a traceback.
        print(
            f"[leader_watch] 실시간 시세 제공자(RealProvider)가 아직 구현되지 않았습니다: {exc}\n"
            "  --provider mock 으로 실행하거나 leader_watch/providers/real.py 를 구현하세요.",
            file=sys.stderr,
        )
        return 1
    return 0
```

to:

```python
    try:
        if args.single_tick:
            now = datetime.datetime.now(ZoneInfo(config.market_timezone)).replace(tzinfo=None)
            engine.run_once(now)
        else:
            engine.run()
    except NotImplementedError as exc:
        # A provider explicitly signaled it isn't wired up yet.
        print(
            f"[leader_watch] 실시간 시세 제공자가 아직 구현되지 않았습니다: {exc}\n"
            "  --provider mock 으로 실행하거나 해당 provider를 구현하세요.",
            file=sys.stderr,
        )
        return 1
    return 0
```

Then move the `provider = MockProvider() if args.provider == "mock" else RealProvider()` construction line inside a new `try/except KisConfigError` block, since `RealProvider()` (Task 9) can now raise `KisConfigError` at construction time, before `engine.run()`/`run_once()` is ever reached. Replace:

```python
    provider = MockProvider() if args.provider == "mock" else RealProvider()
    notifier = ConsoleNotifier() if args.notifier == "console" else TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    store = AlertStore(config.db_path)

    engine = Engine(provider=provider, notifier=notifier, config=config, store=store)
```

with:

```python
    try:
        provider = MockProvider() if args.provider == "mock" else RealProvider()
    except KisConfigError as exc:
        print(f"[leader_watch] {exc}", file=sys.stderr)
        return 1

    notifier = ConsoleNotifier() if args.notifier == "console" else TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    store = AlertStore(config.db_path)

    engine = Engine(provider=provider, notifier=notifier, config=config, store=store)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/leader_watch/test_main_cli.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Run the full leader_watch suite to confirm nothing else broke**

Run: `pytest tests/leader_watch/ -v`
Expected: PASS, no regressions in `test_engine.py`/`test_integration_mock_run.py` (neither touches `RealProvider`).

- [ ] **Step 6: Commit**

```bash
git add main.py tests/leader_watch/test_main_cli.py
git commit -m "feat(leader_watch): report missing KIS credentials cleanly instead of crashing"
```

---

### Task 11: `.env.example` and `README.md` updates

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Append to `.env.example`**

Append after the existing `LEADER_WATCH_DB_PATH=leader_watch/data/alerts.db` line:

```env

# --- KIS Developers API (RealProvider, --provider real) ---
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_ENV=real                          # real | paper
KIS_UNIVERSE_SIZE=100
KIS_RANKING_REFRESH_SECONDS=20
KIS_MAX_REQUESTS_PER_SECOND=15
```

- [ ] **Step 2: Update `README.md`'s config table**

Read the current `README.md` first (its config table is in the "설정값" section). Add these six rows to the existing markdown table, immediately after the `LEADER_WATCH_DB_PATH` row:

```markdown
| KIS_APP_KEY | (없음, 필수) | KIS Developers API 앱키 (--provider real 사용 시 필수) |
| KIS_APP_SECRET | (없음, 필수) | KIS Developers API 앱시크릿 (--provider real 사용 시 필수) |
| KIS_ENV | real | KIS 계정 환경 (real=실전투자, paper=모의투자) |
| KIS_UNIVERSE_SIZE | 100 | 거래대금 상위 몇 종목까지 추적할지 |
| KIS_RANKING_REFRESH_SECONDS | 20 | 거래대금/업종 순위 갱신 주기(초) |
| KIS_MAX_REQUESTS_PER_SECOND | 15 | KIS API 초당 최대 호출 수 (보수적 기본값, 계정 등급에 맞춰 조정) |
```

- [ ] **Step 3: Replace the TODO section's RealProvider bullet**

Find this bullet in the `### TODO / 실 데이터 연동 필요 사항` section:

```markdown
- `leader_watch/providers/real.py`의 `RealProvider`는 아직 구현되지 않았습니다.
  실시간 1분봉/5분봉/체결강도/거래대금순위를 제공하는 증권사 API(예: 한국투자증권
  Open API 등)를 선정한 뒤, 해당 클래스를 구현해야 `--provider real`이 동작합니다.
```

Replace it with:

```markdown
- `leader_watch/providers/real.py`의 `RealProvider`는 한국투자증권(KIS) Developers
  Open API로 구현되어 있습니다 (`.env`에 `KIS_APP_KEY`/`KIS_APP_SECRET` 설정 필요).
  단, 정확한 TR_ID/필드명 일부는 검증되지 않은 가정입니다 — 자세한 내용은
  `docs/superpowers/specs/2026-08-12-real-provider-kis-design.md`의
  "구현 중 반드시 검증해야 할 가정" 절 및 `leader_watch/providers/kis/mapping.py`의
  주석을 참고하세요. 20일 동시간대 평균 거래대금/거래량과 당일 뉴스/공시 감지는
  이번 범위에 포함되지 않았습니다(아래 항목 참고).
```

- [ ] **Step 4: Add a bullet for the two explicitly-deferred data points**

Add this bullet to the same `### TODO / 실 데이터 연동 필요 사항` section (after the bullet replaced in Step 3):

```markdown
- `avg_trading_value_same_time_20d`/`avg_volume_same_time_20d`(20일 동시간대 평균
  거래대금/거래량)는 `RealProvider`에서 항상 `None`으로 채워집니다 — 점수 가산
  로직이 자동으로 건너뛰므로 시스템은 정상 동작하지만, 5배/3배 이상 거래대금 증가
  가산점은 받을 수 없습니다. 별도 작업으로 일봉 시세 조회 API 기반 계산 로직을
  추가해야 합니다.
```

- [ ] **Step 5: Commit**

```bash
git add .env.example README.md
git commit -m "docs: document KIS RealProvider config and remaining gaps"
```

---

### Task 12: Full test suite run and manual verification

**Files:** None — verification only.

**Interfaces:** None.

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: All tests pass, zero failures, zero errors. This includes every existing test plus all new `tests/leader_watch/test_kis_*.py` and the modified `test_providers_real.py`/`test_main_cli.py`.

- [ ] **Step 2: Confirm no real network calls are made by the test suite**

Run: `pytest tests/leader_watch/ -v -k kis` and manually confirm (by reading the test output/names) that every test that exercises `KisClient`/`KisAuth`/`RealProvider` uses `unittest.mock.patch` on `requests.get`/`requests.post` or a fake/stub object — none should require real credentials or network access. If any test is found making a real call, STOP and fix it before proceeding (this violates the plan's Global Constraints).

- [ ] **Step 3: Manually verify the CLI still handles missing credentials gracefully**

Run (from repo root, ensuring `KIS_APP_KEY`/`KIS_APP_SECRET` are NOT set in your shell environment for this check):

```bash
python main.py --provider real --notifier console --single-tick
```

Expected: prints a clear Korean message to stderr naming the missing environment variables, exits with code 1, no Python traceback.

- [ ] **Step 4: Manually verify `--provider mock` still works unaffected**

Run: `python main.py --provider mock --notifier console --single-tick`
Expected: exit code 0 (this path never touches any KIS code).

- [ ] **Step 5: Commit (only if Steps 1-4 required any fixes)**

If all steps passed without needing changes, there is nothing to commit for this task — it is a pure verification checkpoint. If a fix was needed, commit it with a message describing what was found and fixed.
