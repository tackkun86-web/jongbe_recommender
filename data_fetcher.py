import re
import time

import pandas as pd
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
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


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
        change_text = tds[4].get_text()
        change_pct = _to_number(change_text)
        if "하락" in change_text or ("-" in change_text and change_pct > 0):
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


def _parse_rise_table(html: str) -> list[dict]:
    # sise_rise.naver's columns differ from sise_quant.naver: N, 종목명, 현재가,
    # 전일비, 등락률, 거래량, 매수호가, 매도호가, 매수잔량, 매도잔량, PER, ROE.
    # It has no 거래대금/시가총액 columns, so those must not be read positionally
    # from here (that previously misread a bid/ask price as trade value).
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
        change_text = tds[4].get_text()
        change_pct = _to_number(change_text)
        if "하락" in change_text or ("-" in change_text and change_pct > 0):
            change_pct = -change_pct
        volume = _to_number(tds[5].get_text())
        rows.append({
            "code": code,
            "name": name,
            "price": price,
            "change_pct": change_pct,
            "volume": volume,
            "trade_value_eok": price * volume / 1e8,
            "market_cap_eok": None,
        })
    return rows


def _parse_market_sum_table(html: str) -> list[dict]:
    # sise_market_sum.naver columns: N, 종목명, 현재가, 전일비, 등락률, 액면가,
    # 시가총액, 상장주식수, 외국인비율, 거래량, PER, ROE, 토론실. It is sorted by
    # 시가총액 (market cap), not by trade value, and has no 거래대금 column, so
    # trade_value_eok must be computed as price*volume rather than read
    # positionally or trusted from row order.
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
        if len(tds) < 10:
            continue
        price = _to_number(tds[2].get_text())
        change_text = tds[4].get_text()
        change_pct = _to_number(change_text)
        if "하락" in change_text or ("-" in change_text and change_pct > 0):
            change_pct = -change_pct
        market_cap_eok = _to_number(tds[6].get_text())
        volume = _to_number(tds[9].get_text())
        rows.append({
            "code": code,
            "name": name,
            "price": price,
            "change_pct": change_pct,
            "volume": volume,
            "trade_value_eok": price * volume / 1e8,
            "market_cap_eok": market_cap_eok,
        })
    return rows


def _parse_theme_ranking_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="type_1")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        link = tr.find("td", class_="col_type1")
        link = link.find("a") if link else None
        if link is None:
            continue
        no_match = re.search(r"no=(\d+)", link["href"])
        if no_match is None:
            continue
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        rows.append({
            "theme_no": no_match.group(1),
            "name": link.get_text(strip=True),
            "change_pct": _to_number(tds[1].get_text()),
            "up_count": int(_to_number(tds[3].get_text())),
            "flat_count": int(_to_number(tds[4].get_text())),
            "down_count": int(_to_number(tds[5].get_text())),
        })
    return rows


def _parse_theme_detail_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="type_5")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        name_cell = tr.find("td", class_="name")
        link = name_cell.find("a") if name_cell else None
        if link is None:
            continue
        code_match = re.search(r"code=(\d{6})", link["href"])
        if code_match is None:
            continue
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        rows.append({
            "code": code_match.group(1),
            "name": link.get_text(strip=True),
            "change_pct": _to_number(tds[4].get_text()),
        })
    return rows


def _fetch_json(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    time.sleep(REQUEST_SLEEP)
    return resp.json()


def _parse_theme_groups_json(data: dict) -> list[dict]:
    rows = []
    for g in data.get("groups") or []:
        rows.append({
            "theme_no": str(g["no"]),
            "name": g["name"],
            "change_pct": _to_number(str(g.get("changeRate", ""))),
            "up_count": int(g.get("riseCount", 0)),
            "flat_count": int(g.get("steadyCount", 0)),
            "down_count": int(g.get("fallCount", 0)),
        })
    return rows


def _parse_theme_members_json(data: dict) -> list[dict]:
    return [{
        "code": s["itemCode"],
        "name": s["stockName"],
        "change_pct": _to_number(str(s.get("fluctuationsRatio", ""))),
    } for s in data.get("stocks") or []]


# theme.naver / sise_group_detail.naver became JS-rendered (empty HTML tables),
# so themes now come from the mobile JSON API.
def get_theme_ranking(pages: int = 1) -> list[dict]:
    results = []
    for page in range(1, pages + 1):
        url = NAVER_URLS["theme_ranking"].format(page=page)
        results.extend(_parse_theme_groups_json(_fetch_json(url)))
    return results


def get_theme_members(theme_no: str) -> list[dict]:
    url = NAVER_URLS["theme_detail"].format(theme_no=theme_no)
    return _parse_theme_members_json(_fetch_json(url))


def get_all_themes(max_pages: int = 60) -> list[dict]:
    # The API answers 404 for pages past the end; a short page is the last one.
    results = []
    for page in range(1, max_pages + 1):
        url = NAVER_URLS["theme_ranking"].format(page=page)
        try:
            rows = _parse_theme_groups_json(_fetch_json(url))
        except requests.HTTPError:
            if page == 1:
                raise
            break
        results.extend(rows)
        if len(rows) < 100:
            break
    return results


_MARKET_NAMES = {0: "KOSPI", 1: "KOSDAQ"}
_PAGE_SIZE = 100


def _parse_stock_list_json(data: dict) -> list[dict]:
    # m.stock.naver.com reports accumulatedTradingValue and marketValue in
    # millions of KRW, so /100 gives 억.
    rows = []
    for s in data.get("stocks") or []:
        market_value = s.get("marketValue")
        rows.append({
            "code": s["itemCode"],
            "name": s["stockName"],
            "price": _to_number(str(s.get("closePrice", ""))),
            "change_pct": _to_number(str(s.get("fluctuationsRatio", ""))),
            "volume": _to_number(str(s.get("accumulatedTradingVolume", ""))),
            "trade_value_eok": _to_number(str(s.get("accumulatedTradingValue", ""))) / 100,
            "market_cap_eok": _to_number(str(market_value)) / 100 if market_value else None,
        })
    return rows


def get_top_stocks_by_trade_value(sosok: int, max_pages: int = 60) -> list[dict]:
    # sise_market_sum.naver is JS-rendered now; walk the mobile API's full
    # market list (sorted by market cap) so callers can rank by trade value.
    market = _MARKET_NAMES[sosok]
    results = []
    for page in range(1, max_pages + 1):
        url = NAVER_URLS["trade_value"].format(market=market, page=page, size=_PAGE_SIZE)
        rows = _parse_stock_list_json(_fetch_json(url))
        results.extend(rows)
        if len(rows) < _PAGE_SIZE:
            break
    return results


def get_top_gainers(sosok: int, pages: int = 3) -> list[dict]:
    market = _MARKET_NAMES[sosok]
    results = []
    for page in range(1, pages + 1):
        url = NAVER_URLS["gainers"].format(market=market, page=page, size=_PAGE_SIZE)
        rows = _parse_stock_list_json(_fetch_json(url))
        for r in rows:
            r["market_cap_eok"] = None
        results.extend(rows)
        if len(rows) < _PAGE_SIZE:
            break
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
            if "하락" in change_text and change_pct > 0:
                change_pct = -change_pct
            out[market] = {"index": index_num, "change_pct": change_pct}
        except Exception:
            out[market] = {"index": None, "change_pct": None}
    return out


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
    table = soup.find("table", summary=re.compile("외국인 기관 순매매"))
    if table is None:
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
        change_text = tds[3].get_text(strip=True)
        change_val = _to_number(change_text)
        if "하락" in tr.get_text() and change_val > 0:
            change_val = -change_val
        rows.append({
            "date": date_text.replace(".", "-"),
            "close": _to_number(tds[1].get_text()),
            "change_pct": change_val,
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
    if df.empty:
        return df
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
    if df.empty:
        return df
    df = df.sort_values("date").reset_index(drop=True)
    return df.tail(days_needed).reset_index(drop=True)


def get_stock_summary(code: str) -> dict:
    out = {"market_cap_eok": 0.0, "week52_high": 0.0, "week52_low": 0.0, "per": 0.0}
    try:
        html = _fetch_html(NAVER_URLS["summary"].format(code=code))
        soup = BeautifulSoup(html, "lxml")
        cap_tag = soup.select_one("#_market_sum")
        if cap_tag:
            out["market_cap_eok"] = _to_number(
                cap_tag.get_text().replace("\n", "").replace("\t", "")
            )
    except Exception:
        pass
    return out
