from unittest.mock import MagicMock, patch

from leader_watch.providers.kis.client import KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


def _rows(n):
    return [{"stck_shrn_iscd": f"00000{i}", "hts_kor_isnm": f"종목{i}", "data_rank": str(i + 1)} for i in range(n)]


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_trading_value_ranking_returns_top_n_rows(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상", "output": _rows(10)}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    rows = client.get_trading_value_ranking(3)

    assert len(rows) == 3
    assert rows[0]["stck_shrn_iscd"] == "000000"
    args, kwargs = mock_get.call_args
    assert kwargs["headers"]["tr_id"] == "FHPST01710000"
    assert "/uapi/domestic-stock/v1/quotations/volume-rank" in args[0]


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_trading_value_ranking_empty_output(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"rt_cd": "0", "msg1": "정상", "output": []}
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    rows = client.get_trading_value_ranking(50)

    assert rows == []
