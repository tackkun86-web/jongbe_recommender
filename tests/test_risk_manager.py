from risk_manager import generate_exit_rules, generate_nxt_exit_rules


def test_generate_exit_rules_new_high_pattern():
    rules = generate_exit_rules("신고가", 1_567_000)
    assert rules["take_profit_1"] == round(1_567_000 * 1.03)
    assert rules["take_profit_2"] == round(1_567_000 * 1.05)
    assert rules["stop_loss_tight"] == round(1_567_000 * 0.98)
    assert rules["stop_loss_max"] == round(1_567_000 * 0.96)
    assert rules["time_cut"] == "10:00"
    assert "갭상승" in rules["strategy"]


def test_generate_exit_rules_unknown_pattern_falls_back_to_general():
    rules = generate_exit_rules("없음", 10000)
    assert rules["take_profit_1"] == round(10000 * 1.02)
    assert rules["take_profit_2"] == round(10000 * 1.05)


def test_generate_nxt_exit_rules_computes_prices():
    rules = generate_nxt_exit_rules(250_000)
    assert rules["entry_target"] == 250_000
    assert rules["no_chase_price"] == round(250_000 * 1.02)
    assert rules["take_profit_1"] == round(250_000 * 1.04)
    assert rules["take_profit_2"] == round(250_000 * 1.06)
    assert rules["stop_loss_tight"] == round(250_000 * 0.98)
    assert rules["stop_loss_max"] == round(250_000 * 0.96)
    assert rules["time_cut"] == "10:00"


def test_generate_nxt_exit_rules_includes_scenarios():
    rules = generate_nxt_exit_rules(10_000)
    assert "scenario_0900" in rules
    assert "scenario_0910" in rules
    assert "scenario_1000" in rules
    assert "strategy" in rules
