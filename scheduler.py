import time
import logging

import schedule

import report_leader_0930

logging.basicConfig(
    filename="logs/scheduler.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _run_leader_report():
    try:
        report_leader_0930.run()
    except Exception:
        logging.exception("report_leader_0930 failed")


def register_jobs():
    """Register only the 09:30 leader report.

    15:00 (top30) is owned by the Windows
    Task Scheduler entry JongbeTop30TradeValueReport. The close (15:10) and NXT (19:50)
    closing-bet messages were removed on request. The old double-registration made
    every Telegram message fire twice.
    """
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        getattr(schedule.every(), day).at("09:30").do(_run_leader_report)


def start():
    register_jobs()
    logging.info("scheduler started, waiting for weekday 09:30 KST")
    while True:
        schedule.run_pending()
        time.sleep(30)
