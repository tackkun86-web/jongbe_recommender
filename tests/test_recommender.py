import json
import os
from datetime import datetime

import pandas as pd
import recommender
import input_loader
import overseas
import veto


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


def _fake_gap_daily_df():
    closes = [90] * 55 + [95, 96, 97, 98, 100, 101]
    opens = [c * 0.99 for c in closes]
    return pd.DataFrame({
        "date": [f"2026-01-{i+1:02d}" for i in range(61)],
        "close": closes,
        "open": opens,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.96 for c in closes],
        "volume": [1_000_000] * 61,
    })


def _stub_common(monkeypatch):
    monkeypatch.setattr(recommender.data_fetcher, "get_stock_daily_data",
                         lambda code, days_needed=60: _fake_gap_daily_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_investor_data",
                         lambda code, days_needed=5: _fake_investor_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_market_index",
                         lambda: {"kospi": {"index": 2800.0, "change_pct": 0.3},
                                   "kosdaq": {"index": 850.0, "change_pct": 0.1}})
    monkeypatch.setattr(recommender.overseas, "get_overseas_indices",
                         lambda: {"dow_change_pct": 0.2, "nasdaq_change_pct": 0.3,
                                   "sp500_change_pct": 0.1, "usd_krw_change_pct": 0.1,
                                   "wti_change_pct": 0.1})


def test_run_nxt_analysis_blocks_on_veto(monkeypatch, tmp_path):
    _stub_common(monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")
    input_path = tmp_path / "nxt_signals.json"
    input_path.write_text(json.dumps({
        "date": today,
        "overseas": {"kospi200_night_futures_change_pct": -1.0, "sp500_futures_change_pct": -1.0},
        "events": {}, "nxt_stocks": [{"code": "000660", "name": "SK하이닉스",
                                       "nxt_price": 100, "nxt_change_pct": 5.0,
                                       "nxt_trade_value_eok": 300}],
    }), encoding="utf-8")
    monkeypatch.setattr(recommender.input_loader, "DEFAULT_PATH", str(input_path))
    monkeypatch.setattr(recommender, "_load_recent_nxt_totals", lambda max_days=5: [])

    result = recommender.run_analysis(session="nxt")
    assert result["veto_blocked"] is True
    assert result["picks"] == []
    assert len(result["veto_reasons"]) >= 2


def test_run_nxt_analysis_returns_no_recommendation_when_no_stocks(monkeypatch, tmp_path):
    _stub_common(monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")
    input_path = tmp_path / "nxt_signals.json"
    input_path.write_text(json.dumps({"date": today, "overseas": {}, "events": {},
                                        "nxt_stocks": []}), encoding="utf-8")
    monkeypatch.setattr(recommender.input_loader, "DEFAULT_PATH", str(input_path))
    monkeypatch.setattr(recommender, "_load_recent_nxt_totals", lambda max_days=5: [])

    result = recommender.run_analysis(session="nxt")
    assert result["picks"] == []
    assert result["veto_blocked"] is False


def test_run_nxt_analysis_produces_ranked_picks(monkeypatch, tmp_path):
    _stub_common(monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")
    input_path = tmp_path / "nxt_signals.json"
    input_path.write_text(json.dumps({
        "date": today,
        "overseas": {"sox_change_pct": 1.0, "kospi200_night_futures_change_pct": 0.2,
                      "sp500_futures_change_pct": 0.3, "usd_krw_change_pct": 0.1},
        "events": {},
        "nxt_stocks": [{"code": "000660", "name": "SK하이닉스", "nxt_price": 250000,
                         "nxt_change_pct": 6.0, "nxt_trade_value_eok": 300,
                         "nxt_volume": 1000, "buy_sell_ratio": 1.4}],
    }), encoding="utf-8")
    monkeypatch.setattr(recommender.input_loader, "DEFAULT_PATH", str(input_path))
    monkeypatch.setattr(recommender, "_load_recent_nxt_totals", lambda max_days=5: [])
    monkeypatch.setattr(recommender, "_nxt_theme_streak", lambda code, max_days=5: 2)

    result = recommender.run_analysis(session="nxt")
    assert result["session"] == "nxt"
    if result["picks"]:
        pick = result["picks"][0]
        assert pick["code"] == "000660"
        assert pick["rank"] == 1
        assert "exit_rules" in pick
        assert "entry_target" in pick["exit_rules"]


def test_nxt_theme_streak_counts_consecutive_recent_days(tmp_path, monkeypatch):
    monkeypatch.setattr(recommender, "OUTPUT_DIR", str(tmp_path))
    for i, day in enumerate(["20260801", "20260802", "20260803"]):
        with open(os.path.join(str(tmp_path), f"{day}_nxt.json"), "w", encoding="utf-8") as f:
            json.dump({"picks": [{"code": "000660"}]}, f)
    streak = recommender._nxt_theme_streak("000660")
    assert streak == 3


def test_nxt_theme_streak_stops_at_first_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(recommender, "OUTPUT_DIR", str(tmp_path))
    with open(os.path.join(str(tmp_path), "20260801_nxt.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": [{"code": "000660"}]}, f)
    with open(os.path.join(str(tmp_path), "20260802_nxt.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": []}, f)
    with open(os.path.join(str(tmp_path), "20260803_nxt.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": [{"code": "000660"}]}, f)
    streak = recommender._nxt_theme_streak("000660")
    assert streak == 1


def test_nxt_theme_streak_excludes_todays_own_file(tmp_path, monkeypatch):
    monkeypatch.setattr(recommender, "OUTPUT_DIR", str(tmp_path))
    today = datetime.now().strftime("%Y%m%d")
    # A prior day's file establishes a streak of 1.
    with open(os.path.join(str(tmp_path), "20250101_nxt.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": [{"code": "000660"}]}, f)
    # Today's own file (e.g. from a manual re-run) must not be counted.
    with open(os.path.join(str(tmp_path), f"{today}_nxt.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": [{"code": "000660"}]}, f)
    streak = recommender._nxt_theme_streak("000660", max_days=5)
    assert streak == 1


def test_load_prev_top_codes_prefers_close_file_over_nxt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(recommender, "OUTPUT_DIR", str(tmp_path))
    with open(os.path.join(str(tmp_path), "20260804_close.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": [{"code": "005930"}]}, f)
    with open(os.path.join(str(tmp_path), "20260804_nxt.json"), "w", encoding="utf-8") as f:
        json.dump({"picks": [{"code": "000660"}]}, f)
    codes = recommender._load_prev_top_codes()
    assert codes == {"005930"}


def test_run_nxt_analysis_does_not_crash_on_garbage_trade_value(monkeypatch, tmp_path):
    _stub_common(monkeypatch)
    today = datetime.now().strftime("%Y-%m-%d")
    input_path = tmp_path / "nxt_signals.json"
    input_path.write_text(json.dumps({
        "date": today,
        "overseas": {},
        "events": {},
        "nxt_stocks": [{"code": "000660", "name": "SK하이닉스", "nxt_price": 100,
                         "nxt_change_pct": 5.0, "nxt_trade_value_eok": "120억"}],
    }), encoding="utf-8")
    monkeypatch.setattr(recommender.input_loader, "DEFAULT_PATH", str(input_path))
    monkeypatch.setattr(recommender, "_load_recent_nxt_totals", lambda max_days=5: [])

    result = recommender.run_analysis(session="nxt")
    assert result["session"] == "nxt"
    assert result["nxt_total_trade_value_eok"] == 0


def test_evaluate_nxt_candidate_returns_none_when_nxt_price_missing(monkeypatch):
    monkeypatch.setattr(recommender.data_fetcher, "get_stock_daily_data",
                         lambda code, days_needed=60: _fake_gap_daily_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_investor_data",
                         lambda code, days_needed=5: _fake_investor_df())
    stock = {"code": "000660", "name": "SK하이닉스", "nxt_change_pct": 5.0}
    pick = recommender._evaluate_nxt_candidate(stock, overseas_signals={})
    assert pick is None


def test_evaluate_nxt_candidate_returns_none_when_nxt_change_pct_missing(monkeypatch):
    monkeypatch.setattr(recommender.data_fetcher, "get_stock_daily_data",
                         lambda code, days_needed=60: _fake_gap_daily_df())
    monkeypatch.setattr(recommender.data_fetcher, "get_investor_data",
                         lambda code, days_needed=5: _fake_investor_df())
    stock = {"code": "000660", "name": "SK하이닉스", "nxt_price": 250000}
    pick = recommender._evaluate_nxt_candidate(stock, overseas_signals={})
    assert pick is None
