from unittest.mock import MagicMock, patch

from leader_watch.providers.kis.client import KisClient
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=1000)


class _FakeAuth:
    def get_token(self) -> str:
        return "FAKE_TOKEN"


@patch("leader_watch.providers.kis.client.requests.get")
def test_get_sector_ranking_returns_rows(mock_get):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "rt_cd": "0", "msg1": "정상",
        "output": [
            {"hts_kor_isnm": "반도체", "data_rank": "1"},
            {"hts_kor_isnm": "2차전지", "data_rank": "2"},
        ],
    }
    mock_get.return_value = resp

    client = KisClient(CFG, _FakeAuth())
    rows = client.get_sector_ranking()

    assert len(rows) == 2
    assert rows[0]["hts_kor_isnm"] == "반도체"
    args, kwargs = mock_get.call_args
    assert kwargs["headers"]["tr_id"] == "FHPST01730000"
