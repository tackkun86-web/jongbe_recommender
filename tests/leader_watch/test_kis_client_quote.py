from unittest.mock import MagicMock, patch

from leader_watch.providers.kis.client import KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_quote_returns_output_dict(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상", "output": {"stck_prpr": "70000"}}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    quote = client.get_quote("005930")

    assert quote == {"stck_prpr": "70000"}
    args, kwargs = mock_get.call_args
    assert kwargs["headers"]["tr_id"] == "FHKST01010100"
    assert kwargs["params"]["FID_INPUT_ISCD"] == "005930"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_quote_missing_output_returns_empty_dict(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상"}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    quote = client.get_quote("005930")

    assert quote == {}
