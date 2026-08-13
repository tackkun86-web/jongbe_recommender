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
        sleep_fn: Callable[[float], None] | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._min_interval = 1.0 / max_requests_per_second
        self._sleep_fn = sleep_fn or time.sleep
        self._now_fn = now_fn or time.time
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
        try:
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
        except requests.RequestException as exc:
            # Network-level failures (timeouts, connection errors) must be
            # normalized to KisApiError so leader_watch/providers/real.py's
            # `except KisApiError:` per-code handling (and call_with_retry's
            # retry loop) can catch them the same way as an HTTP-level
            # failure — a raw `requests` exception would otherwise escape
            # and kill the whole tick.
            raise KisApiError(f"KIS API call to {path} failed: {exc}") from exc
        if response.status_code != 200:
            raise KisApiError(f"KIS API call to {path} failed with status {response.status_code}: {response.text}")
        body = response.json()
        if body.get("rt_cd") != "0":
            raise KisApiError(f"KIS API call to {path} returned rt_cd={body.get('rt_cd')}: {body.get('msg1')}")
        return body

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
