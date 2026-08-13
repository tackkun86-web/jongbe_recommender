from unittest.mock import MagicMock, patch

import pytest
import requests
from leader_watch.providers.kis.client import KisApiError, KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


def _ok_response(output=None):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상", "output": output if output is not None else []}
    return resp


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_attaches_correct_headers_and_url(mock_get):
    mock_get.return_value = _ok_response(output={"foo": "bar"})
    client = KisClient(CFG, _FakeAuth())
    body = client._get("/uapi/domestic-stock/v1/quotations/inquire-price", tr_id="FHKST01010100", params={"a": "b"})
    assert body["output"] == {"foo": "bar"}
    args, kwargs = mock_get.call_args
    assert args[0] == "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
    assert kwargs["headers"]["authorization"] == "Bearer FAKE_TOKEN"
    assert kwargs["headers"]["appkey"] == "key"
    assert kwargs["headers"]["appsecret"] == "secret"
    assert kwargs["headers"]["tr_id"] == "FHKST01010100"
    assert kwargs["params"] == {"a": "b"}


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_raises_on_non_200(mock_get):
    resp = MagicMock(status_code=500, text="server error")
    mock_get.return_value = resp
    client = KisClient(CFG, _FakeAuth())
    with pytest.raises(KisApiError):
        client._get("/some/path", tr_id="X", params={})


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_raises_on_nonzero_rt_cd(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "1", "msg1": "실패"}
    mock_get.return_value = resp
    client = KisClient(CFG, _FakeAuth())
    with pytest.raises(KisApiError):
        client._get("/some/path", tr_id="X", params={})


@patch("leader_watch.providers.kis.client.time.sleep")
@patch("leader_watch.providers.kis.client.requests.get")
def test_rate_limiter_sleeps_between_rapid_calls(mock_get, mock_sleep):
    mock_get.return_value = _ok_response()
    slow_cfg = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=2)
    client = KisClient(slow_cfg, _FakeAuth())
    client._get("/p", tr_id="X", params={})
    client._get("/p", tr_id="X", params={})
    assert mock_sleep.call_count >= 1


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_network_timeout_raises_kis_api_error_not_raw_requests_exception(mock_get):
    mock_get.side_effect = requests.exceptions.Timeout("connection timed out")
    client = KisClient(CFG, _FakeAuth())
    with pytest.raises(KisApiError):
        client._get("/some/path", tr_id="X", params={})


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_connection_error_raises_kis_api_error_not_raw_requests_exception(mock_get):
    mock_get.side_effect = requests.exceptions.ConnectionError("connection refused")
    client = KisClient(CFG, _FakeAuth())
    with pytest.raises(KisApiError):
        client._get("/some/path", tr_id="X", params={})
