from risk_manager import generate_exit_rules


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
