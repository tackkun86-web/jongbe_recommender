from kiwoom_bridge.http_server import handle_request

TOKEN = "tok"


class _FakeTrClient:
    def __init__(self):
        self.ranking_calls = []
        self.sector_calls = 0
        self.quote_calls = []
        self.minute_bar_calls = []
        self.raise_on_quote_for: set[str] = set()

    def get_trading_value_ranking(self, count):
        self.ranking_calls.append(count)
        return [{"code": "005930", "name": "삼성전자", "rank": 1}][:count]

    def get_sector_ranking(self):
        self.sector_calls += 1
        return [{"name": "반도체", "rank": 1}]

    def get_quote(self, code):
        self.quote_calls.append(code)
        if code in self.raise_on_quote_for:
            raise RuntimeError(f"TR failure for {code}")
        return {"current_price": 70500}

    def get_minute_bars(self, code, reference_time):
        self.minute_bar_calls.append((code, reference_time))
        return [{"time": reference_time}]


def test_missing_token_returns_401():
    status, body = handle_request("GET", "/health", {}, _FakeTrClient(), TOKEN)
    assert status == 401


def test_wrong_token_returns_401():
    status, body = handle_request("GET", "/health", {"X-Bridge-Token": "wrong"}, _FakeTrClient(), TOKEN)
    assert status == 401


def test_health_returns_200_ok():
    status, body = handle_request("GET", "/health", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN)
    assert status == 200
    assert body == {"status": "ok"}


def test_non_get_method_returns_404():
    status, body = handle_request("POST", "/health", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN)
    assert status == 404


def test_ranking_trading_value_passes_count_query_param():
    client = _FakeTrClient()
    status, body = handle_request(
        "GET", "/ranking/trading-value?count=1", {"X-Bridge-Token": TOKEN}, client, TOKEN
    )
    assert status == 200
    assert body == [{"code": "005930", "name": "삼성전자", "rank": 1}]
    assert client.ranking_calls == [1]


def test_ranking_trading_value_defaults_count_to_100_when_missing():
    client = _FakeTrClient()
    handle_request("GET", "/ranking/trading-value", {"X-Bridge-Token": TOKEN}, client, TOKEN)
    assert client.ranking_calls == [100]


def test_ranking_sector_returns_rows():
    status, body = handle_request(
        "GET", "/ranking/sector", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN
    )
    assert status == 200
    assert body == [{"name": "반도체", "rank": 1}]


def test_quote_route_extracts_code_from_path():
    client = _FakeTrClient()
    status, body = handle_request("GET", "/quote/005930", {"X-Bridge-Token": TOKEN}, client, TOKEN)
    assert status == 200
    assert body == {"current_price": 70500}
    assert client.quote_calls == ["005930"]


def test_quote_route_missing_code_returns_404():
    status, body = handle_request("GET", "/quote/", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN)
    assert status == 404


def test_minute_bars_route_requires_reference_time_query_param():
    status, body = handle_request(
        "GET", "/minute-bars/005930", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN
    )
    assert status == 400


def test_minute_bars_route_returns_rows():
    client = _FakeTrClient()
    status, body = handle_request(
        "GET", "/minute-bars/005930?reference_time=093000", {"X-Bridge-Token": TOKEN}, client, TOKEN
    )
    assert status == 200
    assert body == [{"time": "093000"}]
    assert client.minute_bar_calls == [("005930", "093000")]


def test_unknown_route_returns_404():
    status, body = handle_request("GET", "/nonsense", {"X-Bridge-Token": TOKEN}, _FakeTrClient(), TOKEN)
    assert status == 404


def test_tr_client_exception_becomes_503_not_a_raised_exception():
    client = _FakeTrClient()
    client.raise_on_quote_for.add("005930")
    status, body = handle_request("GET", "/quote/005930", {"X-Bridge-Token": TOKEN}, client, TOKEN)
    assert status == 503
    assert "error" in body
