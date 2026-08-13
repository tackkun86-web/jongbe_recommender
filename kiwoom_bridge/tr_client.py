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

Login is NOT assumed to be established externally: OpenAPI+ login state
belongs to the OCX control instance WITHIN a given process, so a freshly
constructed control inside this bridge process has no session regardless of
what any other process (e.g. a previously-logged-in KOA Studio/HTS window)
did. `KiwoomTrClient.__init__` therefore calls `CommConnect()` itself and
blocks (via the same threading.Event + pythoncom.PumpWaitingMessages
pattern used for TR requests) until `OnEventConnect` reports success or a
timeout elapses. This is a one-time cost at bridge startup — starting
bridge.py triggers the Kiwoom OpenAPI+ login popup, and the user completes
the interactive login (ID/password/certificate) when it appears.
"""
from __future__ import annotations

import threading
import time

import pythoncom
import win32com.client


class KiwoomTrError(Exception):
    """Raised when a Kiwoom TR request fails, times out, or returns malformed data."""


class _KiwoomEvents:
    """Event-sink class for win32com.client.DispatchWithEvents.

    Plain `win32com.client.Dispatch(...)` returns a bare CDispatch object
    with NO event sink: assigning a callable to an attribute like
    `OnReceiveTrData` on that object does NOT subscribe to the OCX's COM
    connection point (outgoing interface), so the callback would simply
    never fire. `DispatchWithEvents` is pywin32's documented mechanism for
    binding a COM object's outgoing event interface to a Python class's
    methods, matched by method name (e.g. `OnReceiveTrData`,
    `OnEventConnect`) — it is required here, not merely a stylistic choice.

    `DispatchWithEvents` constructs and OWNS an instance of this class
    itself when wiring up the event sink; it does NOT run
    `KiwoomTrClient.__init__` on it, so this class has no access to
    `KiwoomTrClient`'s per-instance state (its `threading.Event`s) through
    normal `__init__` args. Instead, `KiwoomTrClient.__init__` sets an
    `_owner` attribute on the object `DispatchWithEvents` returns (which IS
    an instance of a dynamically-generated subclass of this class, merging
    the COM dispatch methods with these event methods) immediately after
    construction. The event methods below read `self._owner` at call time
    to reach back into the owning `KiwoomTrClient` instance and signal its
    events. This is the standard pywin32 idiom for this situation.
    """

    def OnReceiveTrData(self, scrno, rqname, trcode, recordname, prevnext, *_args) -> None:
        owner = getattr(self, "_owner", None)
        if owner is not None:
            owner._on_receive_tr_data(scrno, rqname, trcode, recordname, prevnext)

    def OnEventConnect(self, err_code) -> None:
        owner = getattr(self, "_owner", None)
        if owner is not None:
            owner._on_event_connect(err_code)


# ASSUMPTION: 거래대금상위 조회 TR. Commonly documented as opt10032
# (당일거래량상위/거래대금상위 계열) — verify the exact TR code and the
# 종목코드/종목명/순위 출력 field names against a real login.
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
# ASSUMPTION: this field is often documented as a plain 6-digit "HHMMSS"
# string, but real 분봉차트 TR responses commonly return a 14-digit
# "YYYYMMDDHHMMSS" timestamp instead. `get_minute_bars` below truncates to
# the trailing 6 characters unconditionally so the bridge always emits a
# normalized HHMMSS string — leader_watch/providers/kiwoom/mapping.py's
# parse_minute_bar assumes exactly that 6-digit schema and must NOT be
# changed to handle a 14-digit value itself. VERIFY the real format against
# a real login.
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
# Login involves a GUI popup and human interaction (ID/password/certificate),
# so it needs a much longer timeout than a single TR request — but this cost
# is paid once at bridge startup, not per-request.
_CONNECT_TIMEOUT_SECONDS = 30.0


def _map_status(raw: str) -> str:
    return _STATUS_MAP.get(raw.strip(), "normal")


def _parse_num(raw: str) -> str:
    """Strip Kiwoom's signed/zero-padded numeric-string convention.

    ASSUMPTION: Kiwoom's GetCommData commonly returns price/volume fields as
    signed, zero-padded strings like "-070500", where the leading sign
    encodes today's price-direction vs. yesterday's close (up/down) rather
    than the actual sign of the price or volume. A naive float()/int() on
    such a string would produce a negative price and silently corrupt
    change_pct and everything downstream in scoring. This strips the sign
    (and any zero-padding) by round-tripping through int(). VERIFY against a
    real login: the exact sign convention, and whether it applies uniformly
    to every field this is used on below, needs confirmation once real data
    is available — adjust this helper if reality differs.
    """
    raw = raw.strip()
    if not raw:
        return raw
    try:
        return str(abs(int(raw)))
    except ValueError:
        return raw


def _parse_bar_time(raw: str) -> str:
    """Normalize 체결시간 to a 6-digit HHMMSS string.

    See the `_F_BAR_TIME` ASSUMPTION comment above: real Kiwoom minute-bar
    responses commonly return a 14-digit YYYYMMDDHHMMSS timestamp instead of
    the documented 6-digit HHMMSS. Always take the trailing 6 characters so
    the bridge's JSON schema stays normalized to HHMMSS regardless of which
    format the real TR turns out to use.
    """
    raw = raw.strip()
    return raw[-6:] if len(raw) > 6 else raw


class KiwoomTrClient:
    """Blocking wrapper: `__init__` logs in (via CommConnect, waiting on
    OnEventConnect) and each public method afterwards sends one TR request
    and waits (via a threading.Event set inside OnReceiveTrData) for its
    response, raising KiwoomTrError on timeout or a Kiwoom-reported
    failure."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._connect_event = threading.Event()
        self._connect_err_code: int | None = None
        # See _KiwoomEvents' docstring above for why DispatchWithEvents (not
        # plain Dispatch) is required to receive OnReceiveTrData/OnEventConnect.
        self._ocx = win32com.client.DispatchWithEvents("KHOPENAPI.KHOpenAPICtrl.1", _KiwoomEvents)
        # DispatchWithEvents instantiates the event-sink class itself and
        # does not run KiwoomTrClient.__init__ on it, so we set a
        # back-reference attribute after the fact for the event methods to
        # find this owning instance (see _KiwoomEvents' docstring).
        self._ocx._owner = self
        self._connect()

    def _on_receive_tr_data(self, scrno, rqname, trcode, recordname, prevnext) -> None:
        self._event.set()

    def _on_event_connect(self, err_code) -> None:
        self._connect_err_code = err_code
        self._connect_event.set()

    def _connect(self) -> None:
        self._connect_event.clear()
        ret = self._ocx.CommConnect()
        if ret != 0:
            raise KiwoomTrError(f"CommConnect() failed with return code {ret}")
        deadline = time.time() + _CONNECT_TIMEOUT_SECONDS
        while not self._connect_event.is_set():
            if time.time() > deadline:
                raise KiwoomTrError(
                    f"Kiwoom OpenAPI+ login timed out after {_CONNECT_TIMEOUT_SECONDS}s"
                )
            pythoncom.PumpWaitingMessages()
            time.sleep(0.05)
        if self._connect_err_code != 0:
            raise KiwoomTrError(
                f"Kiwoom OpenAPI+ login failed with err_code {self._connect_err_code}"
            )

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
        # constants above) once a real field is confirmed. See repo-root
        # README.md's TODO section for the resulting scoring-rule impact.
        return {
            "current_price": _parse_num(field(_F_CURRENT_PRICE)),
            "open": _parse_num(field(_F_OPEN)),
            "high": _parse_num(field(_F_HIGH)),
            "low": _parse_num(field(_F_LOW)),
            "prev_close": _parse_num(field(_F_PREV_CLOSE)),
            "volume": _parse_num(field(_F_VOLUME)),
            "trading_value": _parse_num(field(_F_TRADING_VALUE)),
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
                "time": _parse_bar_time(self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_TIME).strip()),
                "open": _parse_num(self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_OPEN).strip()),
                "high": _parse_num(self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_HIGH).strip()),
                "low": _parse_num(self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_LOW).strip()),
                "close": _parse_num(self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_CLOSE).strip()),
                "volume": _parse_num(self._ocx.GetCommData(_TR_MINUTE_BARS, rqname, i, _F_BAR_VOLUME).strip()),
            })
        return rows
