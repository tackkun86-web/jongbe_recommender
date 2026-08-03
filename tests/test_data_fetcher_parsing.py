from data_fetcher import _parse_quant_table

FIXTURE_HTML = """
<table class="type_2">
<tr><th>N</th><th>종목명</th><th>현재가</th><th>전일비</th><th>등락률</th>
<th>거래량</th><th>거래대금</th><th>매도호가</th><th>매수호가</th>
<th>시가총액</th><th>PER</th><th>ROE</th></tr>
<tr><td>1</td>
<td><a href="/item/main.naver?code=005930">삼성전자</a></td>
<td>75,000</td><td>2,000</td><td>+2.74%</td>
<td>10,000,000</td><td>750,000</td>
<td>75,100</td><td>75,000</td><td>4,500,000</td><td>12.3</td><td>9.1</td>
</tr>
</table>
"""


def test_parse_quant_table_extracts_code_and_values():
    rows = _parse_quant_table(FIXTURE_HTML)
    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "005930"
    assert row["name"] == "삼성전자"
    assert row["price"] == 75000
    assert row["change_pct"] == 2.74
    assert row["volume"] == 10_000_000
    assert row["trade_value_eok"] == 7500.0  # 750,000 million-won / 100
    assert row["market_cap_eok"] == 4_500_000  # already 억원 on Naver
