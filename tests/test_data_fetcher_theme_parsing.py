from data_fetcher import _parse_theme_detail_table, _parse_theme_ranking_table

THEME_RANKING_FIXTURE = """
<table class="type_1">
<tr class="udline"><th>테마</th><th>등락률</th><th>최근3일</th>
<th colspan="3">등락 현황</th><th colspan="2">주도주</th></tr>
<tr class="udline"><th>상승</th><th>보합</th><th>하락</th></tr>
<tr><td class="blank_07" colspan="8"></td></tr>
<tr>
<td class="col_type1"><a href="/sise/sise_group_detail.naver?type=theme&amp;no=575">클라우드</a></td>
<td class="number col_type2"><span class="tah p11 red01">+5.62%</span></td>
<td class="number col_type3"><span class="tah p11 red01">+0.19%</span></td>
<td class="number col_type4">2</td>
<td class="number col_type4">0</td>
<td class="number col_type4">3</td>
<td class="ls col_type5"><a href="/item/main.naver?code=294570">에스씨</a></td>
<td class="ls col_type6"><a href="/item/main.naver?code=094480">메타랩스</a></td>
</tr>
<tr>
<td class="col_type1"><a href="/sise/sise_group_detail.naver?type=theme&amp;no=126">로봇</a></td>
<td class="number col_type2"><span class="tah p11 red01">+2.60%</span></td>
<td class="number col_type3"><span class="tah p11 nv01">-1.00%</span></td>
<td class="number col_type4">1</td>
<td class="number col_type4">0</td>
<td class="number col_type4">0</td>
<td class="ls col_type5"><a href="/item/main.naver?code=017670">SK로봇</a></td>
<td class="ls col_type6"><a href="/item/main.naver?code=032640">LG로봇</a></td>
</tr>
</table>
"""


def test_parse_theme_ranking_table_extracts_theme_no_and_change_pct():
    rows = _parse_theme_ranking_table(THEME_RANKING_FIXTURE)
    assert len(rows) == 2
    first = rows[0]
    assert first["theme_no"] == "575"
    assert first["name"] == "클라우드"
    assert first["change_pct"] == 5.62
    assert first["up_count"] == 2
    assert first["flat_count"] == 0
    assert first["down_count"] == 3


def test_parse_theme_ranking_table_handles_negative_recent3days_without_affecting_change_pct():
    rows = _parse_theme_ranking_table(THEME_RANKING_FIXTURE)
    second = rows[1]
    assert second["change_pct"] == 2.60
    assert second["up_count"] == 1


THEME_DETAIL_FIXTURE = """
<table class="type_5">
<tr><th colspan="2">종목명</th><th>현재가</th><th>전일비</th><th>등락률</th>
<th>매수호가</th><th>매도호가</th><th>거래량</th><th>거래대금</th><th>전일거래량</th><th>토론</th></tr>
<tr><td class="blank_09" colspan="12"></td></tr>
<tr onmouseout="mouseOut(this)" onmouseover="mouseOver(this)">
<td class="name"><div class="name_area"><a href="/item/main.naver?code=294570">에스씨</a> <span class="dot">*</span></div></td>
<td><div class="theme_info_area"></div></td>
<td class="number">26,850</td>
<td class="number"><span class="tah p11 red02">5,050</span></td>
<td class="number"><span class="tah p11 red01">+23.17%</span></td>
<td class="number">26,800</td><td class="number">26,850</td>
<td class="number">694,333</td><td class="number">17,873</td><td class="number">37,619</td>
<td class="center"></td>
</tr>
<tr onmouseout="mouseOut(this)" onmouseover="mouseOver(this)">
<td class="name"><div class="name_area"><a href="/item/main.naver?code=053580">위닉스</a> <span class="dot">*</span></div></td>
<td><div class="theme_info_area"></div></td>
<td class="number">6,980</td>
<td class="number"><span class="tah p11 nv01">140</span></td>
<td class="number"><span class="tah p11 nv01">-1.97%</span></td>
<td class="number">6,900</td><td class="number">6,980</td>
<td class="number">53,454</td><td class="number">381</td><td class="number">16,520</td>
<td class="center"></td>
</tr>
</table>
"""


def test_parse_theme_detail_table_extracts_code_name_and_signed_change_pct():
    rows = _parse_theme_detail_table(THEME_DETAIL_FIXTURE)
    assert len(rows) == 2
    assert rows[0] == {"code": "294570", "name": "에스씨", "change_pct": 23.17}
    assert rows[1] == {"code": "053580", "name": "위닉스", "change_pct": -1.97}
