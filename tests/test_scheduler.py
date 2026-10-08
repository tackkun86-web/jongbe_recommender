import schedule

import scheduler

WEEKDAYS = 5


def _registered_times():
    schedule.clear()
    scheduler.register_jobs()
    times = {}
    for job in schedule.jobs:
        key = job.at_time.strftime("%H:%M")
        times[key] = times.get(key, 0) + 1
    schedule.clear()
    return times


def test_registers_only_the_leader_report():
    """15:00/15:10/19:50 are owned by Windows Task Scheduler.

    Registering them here too made every close/NXT/top30 Telegram message
    fire twice, once from this resident process and once from the task.
    """
    assert _registered_times() == {"09:30": WEEKDAYS}


def test_leader_report_runs_on_every_weekday():
    schedule.clear()
    scheduler.register_jobs()
    days = sorted(job.start_day for job in schedule.jobs)
    schedule.clear()
    assert days == ["friday", "monday", "thursday", "tuesday", "wednesday"]
