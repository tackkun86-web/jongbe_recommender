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
    "trade_value": "https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}",
    "gainers": "https://finance.naver.com/sise/sise_rise.naver?sosok={sosok}&page={page}",
    "daily": "https://finance.naver.com/item/sise_day.naver?code={code}&page={page}",
    "investor": "https://finance.naver.com/item/frgn.naver?code={code}&page={page}",
    "summary": "https://finance.naver.com/item/main.naver?code={code}",
    "kospi_index": "https://finance.naver.com/sise/sise_index.naver?code=KOSPI",
    "kosdaq_index": "https://finance.naver.com/sise/sise_index.naver?code=KOSDAQ",
    "world_index": "https://finance.naver.com/world/",
    "market_index": "https://finance.naver.com/marketindex/",
    "theme_ranking": "https://finance.naver.com/sise/theme.naver?page={page}",
    "theme_detail": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no={theme_no}",
}

EXCLUDED_NAME_KEYWORDS = [
    "KODEX", "TIGER", "KBSTAR", "ARIRANG", "인버스", "레버리지",
    "선물", "스팩", "리츠", "HANARO", "KOSEF", "SOL", "ACE",
    "RISE", "WOORI", "TIMEFOLIO", "PLUS", "KIWOOM", "1Q", "히어로즈",
    "FOCUS", "마이다스", "ETN",
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

NXT_SCORE_WEIGHTS = {
    "nxt_flow": {"t1_pct": 5.0, "t1_pts": 25, "t2_pct": 3.0, "t2_pts": 20,
                 "t3_pct": 1.0, "t3_pts": 12, "t4_pts": 5,
                 "min_trade_value_eok": 1.0, "thin_pts": 2},
    "supply": {"both_pts": 20, "single_pts": 12, "flat_pts": 6, "sell_pts": 0},
    "theme": {"streak_pts": 20, "single_day_pts": 10, "none_pts": 0},
    "overseas": {"up_pts": 15, "flat_pts": 8, "down_pts": 0, "flat_band_pct": 0.2},
    "technical": {"breakout_pts": 15, "above_ma_pts": 8, "below_ma_pts": 0, "proximity_pct": 7.0},
    "gap": {"freq_high_pct": 60.0, "freq_high_pts": 5,
            "freq_mid_pct": 40.0, "freq_mid_pts": 3, "freq_low_pts": 0},
    "risk": {"night_futures_pts": -5, "fx_surge_pts": -5, "us_futures_pts": -5,
             "overheat_pts": -5, "cap": -20},
    "recommend_threshold": 70,
    "top_n": 5,
}

SECTOR_KEYWORDS = [
    {"keywords": ["하이닉스", "삼성전자", "반도체", "한미반도체"],
     "signal": "sox_change_pct", "label": "반도체(SOX)"},
    {"keywords": ["에너지솔루션", "에코프로", "포스코", "2차전지"],
     "signal": "nasdaq_futures_change_pct", "label": "2차전지(나스닥)"},
    {"keywords": ["에어로스페이스", "로템", "넥스원", "방산"],
     "signal": "sp500_futures_change_pct", "label": "방산(S&P500)"},
    {"keywords": ["이노베이션", "S-Oil", "GS"],
     "signal": "sp500_futures_change_pct", "label": "정유(S&P500)"},
]

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
NXT_EXIT_RULES = {"tp1_pct": 4.0, "tp2_pct": 6.0, "no_chase_pct": 2.0}

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
