"""Existing daily close(15:10)/NXT(19:50) batch scheduler entry point.

This is the former contents of main.py, unchanged, moved here so that
main.py can become the entry point for the new 09:00-10:30 leader-watch
system. Run with: python run_daily_scheduler.py
"""
import scheduler

if __name__ == "__main__":
    scheduler.start()
