from config import EXIT_RULES, STOP_LOSS, NXT_EXIT_RULES


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


def generate_nxt_exit_rules(nxt_price: float) -> dict:
    w = NXT_EXIT_RULES
    return {
        "entry_target": round(nxt_price),
        "no_chase_price": round(nxt_price * (1 + w["no_chase_pct"] / 100)),
        "take_profit_1": round(nxt_price * (1 + w["tp1_pct"] / 100)),
        "take_profit_2": round(nxt_price * (1 + w["tp2_pct"] / 100)),
        "stop_loss_tight": round(nxt_price * (1 - STOP_LOSS["tight_pct"] / 100)),
        "stop_loss_max": round(nxt_price * (1 - STOP_LOSS["max_pct"] / 100)),
        "time_cut": STOP_LOSS["time_cut"],
        "strategy": "시초가 갭상승 +3%↑: 1차 익절 / 갭하락 시 5분 관망 후 -2% 진입 시 손절",
        "scenario_0900": "갭상승 +3%↑: 1차 익절 / 갭하락: 5분 관망 후 -2% 진입 시 손절",
        "scenario_0910": "고점 돌파 실패 시 절반 축소",
        "scenario_1000": "슈팅 없으면 전량 정리 (본절 또는 손절)",
    }
