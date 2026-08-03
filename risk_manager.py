from config import EXIT_RULES, STOP_LOSS


def generate_exit_rules(pattern: str, current_price: float) -> dict:
    rules = EXIT_RULES.get(pattern, EXIT_RULES["없음"])
    return {
        "take_profit_1": round(current_price * (1 + rules["tp1_pct"] / 100)),
        "take_profit_2": round(current_price * (1 + rules["tp2_pct"] / 100)),
        "stop_loss_tight": round(current_price * (1 - STOP_LOSS["tight_pct"] / 100)),
        "stop_loss_max": round(current_price * (1 - STOP_LOSS["max_pct"] / 100)),
        "time_cut": STOP_LOSS["time_cut"],
        "strategy": rules["strategy"],
    }
