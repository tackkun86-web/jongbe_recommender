import datetime
import pytest
from leader_watch.providers.base import MarketDataProvider
from leader_watch.providers.real import RealProvider


def test_real_provider_is_instantiable_and_is_a_market_data_provider():
    provider = RealProvider()
    assert isinstance(provider, MarketDataProvider)


def test_real_provider_get_snapshot_raises_not_implemented():
    provider = RealProvider()
    with pytest.raises(NotImplementedError):
        provider.get_snapshot(datetime.datetime(2026, 8, 11, 9, 5))
