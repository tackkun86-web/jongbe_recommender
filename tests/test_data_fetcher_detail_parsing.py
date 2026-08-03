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
