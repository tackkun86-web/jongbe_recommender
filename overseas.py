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
