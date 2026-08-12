from unittest.mock import MagicMock, patch

from leader_watch.providers.kis.client import KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_minute_bars_returns_output2_rows(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "rt_cd": "0", "msg1": "정상",
        "output1": {"some": "meta"},
        "output2": [{"stck_cntg_hour": "093000", "stck_prpr": "70500"}],
    }
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    bars = client.get_minute_bars("005930", "093000")

    assert bars == [{"stck_cntg_hour": "093000", "stck_prpr": "70500"}]
    args, kwargs = mock_get.call_args
    assert kwargs["headers"]["tr_id"] == "FHKST03010200"
    assert kwargs["params"]["FID_INPUT_ISCD"] == "005930"
    assert kwargs["params"]["FID_INPUT_HOUR_1"] == "093000"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_minute_bars_missing_output2_returns_empty_list(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상"}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    bars = client.get_minute_bars("005930", "093000")

    assert bars == []
