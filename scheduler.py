import time
import logging

import schedule

import recommender
import notifier
import report_leader_0930

logging.basicConfig(
    filename="logs/scheduler.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _run_and_notify(session: str = "close"):
    try:
        result = recommender.run_analysis(session=session)
        notifier.notify(result)
    except Exception:
        logging.exception("run_analysis failed")


def _run_leader_report():
    try:
        report_leader_0930.run()
    except Exception:
        logging.exception("report_leader_0930 failed")


def start():
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday"):
        getattr(schedule.every(), day).at("09:30").do(_run_leader_report)
        getattr(schedule.every(), day).at("15:10").do(_run_and_notify, session="close")
        getattr(schedule.every(), day).at("19:50").do(_run_and_notify, session="nxt")
    logging.info("scheduler started, waiting for weekday 09:30, 15:10, and 19:50 KST")
    while True:
        schedule.run_pending()
        time.sleep(30)
