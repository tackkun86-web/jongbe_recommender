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
