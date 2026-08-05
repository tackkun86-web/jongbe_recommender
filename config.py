import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
REQUEST_SLEEP = 0.1
ENCODING = "euc-kr"

NAVER_URLS = {
    "trade_value": "https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&page={page}",
    "gainers": "https://finance.naver.com/sise/sise_rise.naver?sosok={sosok}&page={page}",
    "daily": "https://finance.naver.com/item/sise_day.naver?code={code}&page={page}",
    "investor": "https://finance.naver.com/item/frgn.naver?code={code}&page={page}",
    "summary": "https://finance.naver.com/item/main.naver?code={code}",
    "kospi_index": "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
    "kosdaq_index": "https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ",
    "world_index": "https://finance.naver.com/world/",
    "market_index": "https://finance.naver.com/marketindex/",
}

EXCLUDED_NAME_KEYWORDS = [
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "인버스", "레버리지",
    "선물", "스팩", "리츠", "HANARO", "KOSEF", "SOL", "ACE",
]

HARD_FILTERS = {
    "min_market_cap_eok": 1000,       # 억원
    "min_daily_return_pct": 3.0,
    "max_daily_return_pct": 15.0,
    "limit_up_pct": 29.0,
    "min_trade_value_eok": 500,       # 억원
    "max_close_off_high_pct": 3.0,    # (high-close)/high*100
}

NXT_HARD_FILTERS = {"min_nxt_trade_ratio_pct": 3.0}

SCORE_WEIGHTS = {
    "trade_value": {"tier1_eok": 2000, "tier1_pts": 15,
                     "tier2_eok": 1000, "tier2_pts": 10,
                     "tier3_eok": 500, "tier3_pts": 5},
    "trend": {"aligned_pts": 10, "above_ma5_pts": 5},
    "candle": {"optimal_low": 3.0, "optimal_high": 8.0, "optimal_pts": 10,
               "good_high": 15.0, "good_pts": 5,
               "close_near_high_pts": 5, "close_near_high_pct": 1.0,
               "close_mid_high_pts": 3, "close_mid_high_pct": 3.0},
    "supply": {"foreign_buy_pts": 8, "inst_buy_pts": 8, "program_buy_pts": 5,
               "both_bonus_pts": 4, "foreign_streak_pts": 5, "cap": 25},
    "theme": {"top3_sector_pts": 8, "leader_pts": 5, "leader_min_eok": 1000,
              "continuity_pts": 2},
    "pattern": {"신고가": 15, "전고점돌파": 12, "눌림회복": 10, "과대낙폭반등": 8, "없음": 0},
    "bonus": {"macd_cross_pts": 2, "rsi_range_pts": 2, "rsi_low": 50, "rsi_high": 70},
    "recommend_threshold": 50,
    "top_n": 5,
    "min_recommend": 3,
}

EXIT_RULES = {
    "신고가": {"tp1_pct": 3, "tp2_pct": 5,
              "strategy": "시초가 갭상승 시 익절, 장초반 슈팅 시 2차 익절"},
    "전고점돌파": {"tp1_pct": 3, "tp2_pct": 6,
                 "strategy": "돌파 후 갭상승 시 익절, 추가 상승 시 추익절"},
    "눌림회복": {"tp1_pct": 2, "tp2_pct": 5,
               "strategy": "반등 시 익절, 5일선 도달 시 전량 익절"},
    "과대낙폭반등": {"tp1_pct": 3, "tp2_pct": 5,
                  "strategy": "반등 갭 시 익절, 20일선 도달 시 전량 익절"},
    "없음": {"tp1_pct": 2, "tp2_pct": 5, "strategy": "시초가 갭상승 시 익절"},
}
STOP_LOSS = {"tight_pct": 2, "max_pct": 4, "time_cut": "10:00"}

VETO_THRESHOLDS = {
    "night_futures_pct": -0.5,
    "sp500_futures_pct": -0.5,
    "fx_change_pct": 0.5,
    "sox_pct": -1.0,
    "kospi_close_pct": -1.5,
    "nxt_trade_value_ratio_pct": 50.0,
    "min_conditions": 2,
}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or None
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or None
