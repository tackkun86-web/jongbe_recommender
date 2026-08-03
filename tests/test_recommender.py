import pandas as pd
import recommender


def _fake_daily_df():
    closes = [90] * 55 + [95, 96, 97, 98, 100]
    return pd.DataFrame({
        "date": [f"2026-01-{i+1:02d}" for i in range(60)],
        "close": closes,
        "open": [c * 0.97 for c in closes],
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.96 for c in closes],
        "volume": [1_000_000] * 60,
    })


def _fake_investor_df():
    return pd.DataFrame({
        "date": ["2026-08-01", "2026-08-02", "2026-08-03"],
        "foreign_net": [10, 10, 10],
        "inst_net": [10, 10, 10],
        "close": [98, 99, 100],
        "change_pct": [1, 1, 2],
        "volume": [1_000_000] * 3,
    })


def test_evaluate_candidate_builds_pick_dict(monkeypatch):
    monkeypatch.setattr(recommender.data_fetcher, "get_stock_daily_data",
                         lambda code, days_needed=60: _fake_daily_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_investor_data",
                         lambda code, days_needed=5: _fake_investor_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_stock_summary",
                         lambda code: {"market_cap_eok": 5000, "week52_high": 100,
                                        "week52_low": 50, "per": 10})

    candidate = {"code": "005930", "name": "삼성전자", "market": "KOSPI",
                 "price": 100, "change_pct": 5.0, "volume": 1_000_000,
                 "trade_value_eok": 2500, "market_cap_eok": 5_000_000}

    pick = recommender._evaluate_candidate(candidate, prev_top_codes=set())
    assert pick is not None
    assert pick["code"] == "005930"
    assert pick["pattern"] == "신고가"
    assert pick["score"] >= 50
    assert "exit_rules" in pick
    assert pick["exit_rules"]["take_profit_1"] > pick["current_price"]


def test_evaluate_candidate_returns_none_when_hard_filtered():
    candidate = {"code": "999999", "name": "KODEX 200", "market": "KOSPI",
                 "price": 100, "change_pct": 5.0, "volume": 1_000_000,
                 "trade_value_eok": 2500, "market_cap_eok": 5_000_000}
    pick = recommender._evaluate_candidate(candidate, prev_top_codes=set())
    assert pick is None
