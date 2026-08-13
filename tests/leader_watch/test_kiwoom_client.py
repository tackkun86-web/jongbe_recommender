# tests/leader_watch/test_kiwoom_client.py
from unittest.mock import MagicMock, patch

import pytest
import requests
from leader_watch.providers.kiwoom.client import KiwoomApiError, KiwoomClient
from leader_watch.providers.kiwoom.config import KiwoomConfig

CFG = KiwoomConfig(bridge_url="http://127.0.0.1:8000", bridge_token="tok", universe_size=100, ranking_refresh_seconds=20)


def _ok_response(body):
    resp = MagicMock(status_code=200)
    resp.json.return_value = body
    return resp


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_check_health_calls_health_endpoint_with_token_header(mock_get):
    mock_get.return_value = _ok_response({"status": "ok"})
    KiwoomClient(CFG).check_health()
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/health"
    assert kwargs["headers"]["X-Bridge-Token"] == "tok"


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_trading_value_ranking_passes_count_and_returns_list(mock_get):
    mock_get.return_value = _ok_response([{"code": "005930", "name": "삼성전자", "rank": 1}])
    rows = KiwoomClient(CFG).get_trading_value_ranking(50)
    assert rows == [{"code": "005930", "name": "삼성전자", "rank": 1}]
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/ranking/trading-value"
    assert kwargs["params"] == {"count": 50}


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_sector_ranking_returns_list(mock_get):
    mock_get.return_value = _ok_response([{"name": "반도체", "rank": 1}])
    rows = KiwoomClient(CFG).get_sector_ranking()
    assert rows == [{"name": "반도체", "rank": 1}]
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/ranking/sector"


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_quote_returns_dict(mock_get):
    mock_get.return_value = _ok_response({"current_price": 70500})
    quote = KiwoomClient(CFG).get_quote("005930")
    assert quote == {"current_price": 70500}
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/quote/005930"


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_minute_bars_passes_reference_time_and_returns_list(mock_get):
    mock_get.return_value = _ok_response([{"time": "093000"}])
    bars = KiwoomClient(CFG).get_minute_bars("005930", "093000")
    assert bars == [{"time": "093000"}]
    args, kwargs = mock_get.call_args
    assert args[0] == "http://127.0.0.1:8000/minute-bars/005930"
    assert kwargs["params"] == {"reference_time": "093000"}


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_non_200_raises_kiwoom_api_error(mock_get):
    mock_get.return_value = MagicMock(status_code=401, text="invalid token")
    with pytest.raises(KiwoomApiError):
        KiwoomClient(CFG).check_health()


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_request_exception_is_normalized_to_kiwoom_api_error(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("refused")
    with pytest.raises(KiwoomApiError):
        KiwoomClient(CFG).check_health()


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_quote_missing_dict_body_returns_empty_dict(mock_get):
    mock_get.return_value = _ok_response(["not", "a", "dict"])
    quote = KiwoomClient(CFG).get_quote("005930")
    assert quote == {}


@patch("leader_watch.providers.kiwoom.client.requests.get")
def test_get_trading_value_ranking_missing_list_body_returns_empty_list(mock_get):
    mock_get.return_value = _ok_response({"not": "a list"})
    rows = KiwoomClient(CFG).get_trading_value_ranking(50)
    assert rows == []
