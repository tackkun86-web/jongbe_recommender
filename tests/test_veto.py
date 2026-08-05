from veto import check_veto_conditions


def _overseas(**kwargs):
    base = {
        "kospi200_night_futures_change_pct": None,
        "sp500_futures_change_pct": None,
        "usd_krw_change_pct": None,
        "sox_change_pct": None,
    }
    base.update(kwargs)
    return base


def test_no_conditions_met_does_not_block():
    blocked, reasons = check_veto_conditions(
        _overseas(kospi200_night_futures_change_pct=0.1, sp500_futures_change_pct=0.2,
                   usd_krw_change_pct=0.1, sox_change_pct=0.3),
        kospi_change_pct=0.5, events={}, nxt_trade_value_ratio_pct=120.0,
    )
    assert blocked is False
    assert reasons == []


def test_single_condition_does_not_block():
    blocked, reasons = check_veto_conditions(
        _overseas(kospi200_night_futures_change_pct=-0.8),
        kospi_change_pct=0.5, events={}, nxt_trade_value_ratio_pct=120.0,
    )
    assert blocked is False
    assert len(reasons) == 1


def test_two_conditions_blocks():
    blocked, reasons = check_veto_conditions(
        _overseas(kospi200_night_futures_change_pct=-0.8, sp500_futures_change_pct=-0.6),
        kospi_change_pct=0.5, events={}, nxt_trade_value_ratio_pct=120.0,
    )
    assert blocked is True
    assert len(reasons) == 2


def test_missing_data_is_not_counted():
    blocked, reasons = check_veto_conditions(
        _overseas(),  # all None
        kospi_change_pct=None, events={}, nxt_trade_value_ratio_pct=None,
    )
    assert blocked is False
    assert reasons == []


def test_event_flags_trigger_conditions():
    blocked, reasons = check_veto_conditions(
        _overseas(), kospi_change_pct=None,
        events={"major_event_tomorrow": True, "geopolitical_shock": True},
        nxt_trade_value_ratio_pct=None,
    )
    assert blocked is True
    assert len(reasons) == 2


def test_nxt_trade_value_ratio_below_threshold_triggers():
    blocked, reasons = check_veto_conditions(
        _overseas(kospi200_night_futures_change_pct=-0.8), kospi_change_pct=None,
        events={}, nxt_trade_value_ratio_pct=30.0,
    )
    assert blocked is True
    assert len(reasons) == 2
