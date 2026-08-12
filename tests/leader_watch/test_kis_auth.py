from unittest.mock import MagicMock, patch

import pytest
from leader_watch.providers.kis.auth import KisAuth, KisAuthError
from leader_watch.providers.kis.config import KisConfig

CFG = KisConfig(app_key="key", app_secret="secret", env="real", universe_size=100, ranking_refresh_seconds=20, max_requests_per_second=15)


def _ok_response(token="TOKEN123", expires_in=86400):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"access_token": token, "expires_in": expires_in, "token_type": "Bearer"}
    return resp


@patch("leader_watch.providers.kis.auth.requests.post")
def test_get_token_fetches_on_first_call(mock_post):
    mock_post.return_value = _ok_response()
    auth = KisAuth(CFG, now_fn=lambda: 1000.0)
    token = auth.get_token()
    assert token == "TOKEN123"
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    assert kwargs["json"] == {"grant_type": "client_credentials", "appkey": "key", "appsecret": "secret"}


@patch("leader_watch.providers.kis.auth.requests.post")
def test_get_token_returns_cached_token_before_expiry(mock_post):
    mock_post.return_value = _ok_response(expires_in=3600)
    clock = {"now": 1000.0}
    auth = KisAuth(CFG, now_fn=lambda: clock["now"])
    auth.get_token()
    clock["now"] = 1000.0 + 60  # well before expiry - refresh margin
    auth.get_token()
    assert mock_post.call_count == 1


@patch("leader_watch.providers.kis.auth.requests.post")
def test_get_token_refreshes_near_expiry(mock_post):
    mock_post.return_value = _ok_response(expires_in=3600)
    clock = {"now": 1000.0}
    auth = KisAuth(CFG, now_fn=lambda: clock["now"])
    auth.get_token()
    clock["now"] = 1000.0 + 3600 - 200  # inside the 300s refresh margin
    auth.get_token()
    assert mock_post.call_count == 2


@patch("leader_watch.providers.kis.auth.requests.post")
def test_non_200_raises_kis_auth_error(mock_post):
    resp = MagicMock(status_code=401, text="unauthorized")
    mock_post.return_value = resp
    auth = KisAuth(CFG, now_fn=lambda: 1000.0)
    with pytest.raises(KisAuthError):
        auth.get_token()


@patch("leader_watch.providers.kis.auth.requests.post")
def test_missing_fields_in_response_raises_kis_auth_error(mock_post):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"token_type": "Bearer"}
    mock_post.return_value = resp
    auth = KisAuth(CFG, now_fn=lambda: 1000.0)
    with pytest.raises(KisAuthError):
        auth.get_token()
