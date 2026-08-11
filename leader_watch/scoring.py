"""100-point leading-stock scoring rubric (거래대금30/테마20/가격25/분봉15/뉴스10)."""
from __future__ import annotations

from leader_watch.config import Config
from leader_watch.models import ScoreBreakdown, StockSnapshot, safe_ratio


def _trading_value_points(snapshot: StockSnapshot) -> tuple[float, list[str]]:
    rank = snapshot.market_trading_value_rank
    if rank <= 10:
        points = 30.0
    elif rank <= 20:
        points = 25.0
    elif rank <= 30:
        points = 20.0
    elif rank <= 50:
        points = 15.0
    elif rank <= 100:
        points = 5.0
    else:
        return 0.0, []

    basis = [f"거래대금 순위 {rank}위"]
    if snapshot.avg_trading_value_same_time_20d:
        ratio = safe_ratio(snapshot.cum_trading_value, snapshot.avg_trading_value_same_time_20d)
        if ratio >= 5:
            points = min(30.0, points + 5)
            basis.append("동시간대 평균 대비 5배 이상 거래대금 증가")
        elif ratio >= 3:
            points = min(30.0, points + 3)
            basis.append("동시간대 평균 대비 3배 이상 거래대금 증가")
    if snapshot.change_pct > 0:
        points = min(30.0, points + 2)
        basis.append("거래대금 증가와 함께 주가 상승")
    return round(min(points, 30.0), 2), basis


def _theme_points(snapshot: StockSnapshot, theme_follower_count: int) -> tuple[float, list[str], list[str]]:
    if snapshot.theme is None or snapshot.theme_trading_value_rank is None:
        return 0.0, [], ["theme_leadership"]

    rank = snapshot.theme_trading_value_rank
    if rank == 1:
        points = 20.0
    elif rank == 2:
        points = 14.0
    elif rank == 3:
        points = 8.0
    else:
        points = 0.0

    basis = [f"테마({snapshot.theme}) 내 거래대금 {rank}위"]
    if theme_follower_count >= 2:
        points = min(20.0, points + 2)
        basis.append(f"동반 상승 테마 종목 {theme_follower_count}개")
    elif theme_follower_count == 0:
        points = max(0.0, points - 4)
        basis.append("테마 내 후속 종목 없음 (감점)")
    return round(points, 2), basis, []


def _price_strength_points(snapshot: StockSnapshot) -> tuple[float, list[str]]:
    if snapshot.vs_open_pct < 0:
        return 0.0, ["시가 이탈 후 회복하지 못해 가격 강도 0점"]

    points = 0.0
    basis = []
    change = snapshot.change_pct
    if change >= 5:
        points += 10
        basis.append(f"등락률 +{change:.1f}% (+5% 이상)")
    elif change >= 3:
        points += 8
        basis.append(f"등락률 +{change:.1f}% (+3% 이상)")
    elif change >= 2:
        points += 5
        basis.append(f"등락률 +{change:.1f}% (+2% 이상)")

    points += 5
    basis.append("시가 대비 플러스 유지")

    if snapshot.current_price >= snapshot.high_price * 0.99:
        points += 5
        basis.append("장중 고점 갱신")

    return round(min(points, 25.0), 2), basis


def _minute_flow_points(history: list[StockSnapshot]) -> tuple[float, list[str], list[str]]:
    bars: list = []
    for snap in history:
        bars.extend(snap.minute_bars_1m)
    if len(bars) < 2:
        return 0.0, [], ["minute_flow"]

    points = 0.0
    basis = []
    rising_volume = any(
        bars[i].close > bars[i].open and bars[i].volume > bars[i - 1].volume
        for i in range(1, len(bars))
    )
    if rising_volume:
        points += 5
        basis.append("상승 시 거래량 증가 확인")

    pullback_volume_down = any(
        bars[i].close < bars[i - 1].close and bars[i].volume < bars[i - 1].volume
        for i in range(1, len(bars))
    )
    if pullback_volume_down:
        points += 5
        basis.append("눌림 구간 거래량 감소 확인")

    rebreak_volume_up = any(
        bars[i].high >= max(b.high for b in bars[:i]) and bars[i].volume > bars[i - 1].volume
        for i in range(1, len(bars))
    )
    if rebreak_volume_up:
        points += 5
        basis.append("직전 고점 재돌파 시 거래량 재증가")

    return round(points, 2), basis, []


def _news_points(snapshot: StockSnapshot) -> tuple[float, list[str]]:
    if snapshot.news_today:
        return 10.0, ["당일 신규 뉴스/공시 확인"]
    if snapshot.news_continuing:
        return 5.0, ["전일 뉴스 지속 확산"]
    return 0.0, ["재료 없음"]


def calculate_leader_score(
    snapshot: StockSnapshot,
    history: list[StockSnapshot],
    theme_follower_count: int,
    config: Config,
) -> ScoreBreakdown:
    trading_value, tv_basis = _trading_value_points(snapshot)
    theme_leadership, theme_basis, theme_missing = _theme_points(snapshot, theme_follower_count)
    price_strength, price_basis = _price_strength_points(snapshot)
    minute_flow, flow_basis, flow_missing = _minute_flow_points(history)
    news, news_basis = _news_points(snapshot)

    return ScoreBreakdown(
        trading_value=trading_value,
        theme_leadership=theme_leadership,
        price_strength=price_strength,
        minute_flow=minute_flow,
        news=news,
        missing_categories=theme_missing + flow_missing,
        basis=tv_basis + theme_basis + price_basis + flow_basis + news_basis,
    )
