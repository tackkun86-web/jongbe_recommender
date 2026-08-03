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
