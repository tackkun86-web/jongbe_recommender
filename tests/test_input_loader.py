import json
import input_loader


def test_load_returns_empty_defaults_when_file_missing(tmp_path):
    path = str(tmp_path / "nxt_signals.json")
    data = input_loader.load_nxt_signals(path=path, today="2026-08-05")
    assert data["nxt_stocks"] == []
    assert data["overseas"]["sox_change_pct"] is None
    assert data["events"]["major_event_tomorrow"] is False


def test_load_returns_empty_defaults_when_date_stale(tmp_path):
    path = tmp_path / "nxt_signals.json"
    path.write_text(json.dumps({"date": "2026-08-04", "nxt_stocks": [{"code": "000660"}]}),
                     encoding="utf-8")
    data = input_loader.load_nxt_signals(path=str(path), today="2026-08-05")
    assert data["nxt_stocks"] == []


def test_load_passes_through_valid_same_day_data(tmp_path):
    path = tmp_path / "nxt_signals.json"
    payload = {
        "date": "2026-08-05",
        "overseas": {"sox_change_pct": -0.8, "sp500_futures_change_pct": 0.3},
        "events": {"major_event_tomorrow": True, "event_desc": "FOMC", "geopolitical_shock": False},
        "nxt_stocks": [{"code": "000660", "name": "SK하이닉스", "nxt_price": 250000,
                         "nxt_change_pct": 4.5, "nxt_trade_value_eok": 120,
                         "nxt_volume": 50000, "buy_sell_ratio": 1.4}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    data = input_loader.load_nxt_signals(path=str(path), today="2026-08-05")
    assert data["overseas"]["sox_change_pct"] == -0.8
    assert data["overseas"]["nasdaq_futures_change_pct"] is None
    assert data["events"]["major_event_tomorrow"] is True
    assert data["nxt_stocks"][0]["code"] == "000660"


def test_load_handles_malformed_json(tmp_path):
    path = tmp_path / "nxt_signals.json"
    path.write_text("{not valid json", encoding="utf-8")
    data = input_loader.load_nxt_signals(path=str(path), today="2026-08-05")
    assert data["nxt_stocks"] == []


def test_load_coerces_nxt_stocks_dict_to_empty_list(tmp_path):
    path = tmp_path / "nxt_signals.json"
    path.write_text(json.dumps({"date": "2026-08-05", "nxt_stocks": {"code": "000660"}}),
                     encoding="utf-8")
    data = input_loader.load_nxt_signals(path=str(path), today="2026-08-05")
    assert data["nxt_stocks"] == []


def test_load_drops_non_dict_entries_in_nxt_stocks(tmp_path):
    path = tmp_path / "nxt_signals.json"
    path.write_text(json.dumps({
        "date": "2026-08-05",
        "nxt_stocks": ["not a dict", {"code": "000660", "name": "SK하이닉스"}],
    }), encoding="utf-8")
    data = input_loader.load_nxt_signals(path=str(path), today="2026-08-05")
    assert len(data["nxt_stocks"]) == 1
    assert data["nxt_stocks"][0]["code"] == "000660"


def test_load_drops_non_numeric_trade_value_but_keeps_stock(tmp_path):
    path = tmp_path / "nxt_signals.json"
    path.write_text(json.dumps({
        "date": "2026-08-05",
        "nxt_stocks": [{"code": "000660", "name": "SK하이닉스",
                         "nxt_price": 250000, "nxt_trade_value_eok": "120억"}],
    }), encoding="utf-8")
    data = input_loader.load_nxt_signals(path=str(path), today="2026-08-05")
    assert len(data["nxt_stocks"]) == 1
    stock = data["nxt_stocks"][0]
    assert "nxt_trade_value_eok" not in stock
    assert stock["code"] == "000660"
    assert stock["nxt_price"] == 250000.0
