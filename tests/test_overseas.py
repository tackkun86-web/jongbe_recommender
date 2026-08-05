import overseas

WORLD_HTML = """
<ul class="data_lst" id="worldIndexColumn1">
<li class="on"><dl>
<dt class="dt3"><a href="/world/sise.naver?symbol=DJI@DJI"><span class="blind">다우 산업</span></a></dt>
<dd class="point_status"><strong>14,578.54</strong><em>52.38</em><span><span>+</span>0.36%</span><span class="blind">상승</span></dd>
</dl></li>
</ul>
<ul class="data_lst" id="worldIndexColumn2">
<li class="on"><dl>
<dt class="dt3"><a href="/world/sise.naver?symbol=NAS@IXIC"><span class="blind">나스닥</span></a></dt>
<dd class="point_status"><strong>3,267.52</strong><em>11.00</em><span><span>-</span>0.34%</span><span class="blind">하락</span></dd>
</dl></li>
</ul>
<ul class="data_lst" id="worldIndexColumn3">
<li class="on"><dl>
<dt class="dt3"><a href="/world/sise.naver?symbol=SPI@SPX"><span class="blind">S&amp;P500</span></a></dt>
<dd class="point_status"><strong>1,569.19</strong><em>6.34</em><span><span>+</span>0.41%</span><span class="blind">상승</span></dd>
</dl></li>
</ul>
"""

MARKET_INDEX_HTML = """
<ul id="exchangeList">
<li class="on">
<a class="head usd" href="/marketindex/exchangeDetail.naver?marketindexCd=FX_USDKRW">
<h3 class="h_lst"><span class="blind">미국 USD</span></h3>
<div class="head_info point_dn">
<span class="value">1,425.20</span><span class="change"> 5.80</span>
</div></a>
</li>
</ul>
<ul id="oilGoldList">
<li class="on">
<a class="head wti" href="/marketindex/worldOilDetail.naver?marketindexCd=OIL_CL&amp;fdtc=2">
<h3 class="h_lst"><span class="blind">WTI</span></h3>
<div class="head_info point_up">
<span class="value">75.77</span><span class="change">4.57</span>
</div></a>
</li>
</ul>
"""


def test_parse_world_indices_extracts_signed_pct():
    result = overseas._parse_world_indices(WORLD_HTML)
    assert result["DJI"] == 0.36
    assert result["NAS"] == -0.34
    assert result["SPI"] == 0.41


def test_parse_market_index_list_computes_signed_pct_from_class():
    fx = overseas._parse_market_index_list(MARKET_INDEX_HTML, "exchangeList")
    assert fx["FX_USDKRW"] < 0  # point_dn means the value fell

    oil = overseas._parse_market_index_list(MARKET_INDEX_HTML, "oilGoldList")
    assert oil["OIL_CL"] > 0  # point_up means the value rose


def test_get_overseas_indices_merges_all_sources(monkeypatch):
    def fake_fetch(url):
        if "world" in url:
            return WORLD_HTML
        return MARKET_INDEX_HTML

    monkeypatch.setattr(overseas, "_fetch_html", fake_fetch)
    result = overseas.get_overseas_indices()
    assert result["dow_change_pct"] == 0.36
    assert result["nasdaq_change_pct"] == -0.34
    assert result["sp500_change_pct"] == 0.41
    assert result["usd_krw_change_pct"] is not None
    assert result["wti_change_pct"] is not None


def test_get_overseas_indices_returns_none_fields_on_fetch_failure(monkeypatch):
    def raise_error(url):
        raise ConnectionError("boom")

    monkeypatch.setattr(overseas, "_fetch_html", raise_error)
    result = overseas.get_overseas_indices()
    assert result == {
        "dow_change_pct": None, "nasdaq_change_pct": None, "sp500_change_pct": None,
        "usd_krw_change_pct": None, "wti_change_pct": None,
    }
