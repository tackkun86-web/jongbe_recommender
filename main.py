"""Entry point for the 09:00-10:30 morning leader-watch system.

Usage:
    python main.py --provider mock              # simulation, console output
    python main.py --provider real               # requires RealProvider implementation
    python main.py --provider mock --notifier telegram
    python main.py --provider mock --single-tick  # run exactly one poll and exit (testing)

The existing daily close/NXT batch (15:10 / 19:50) now lives in
`run_daily_scheduler.py` and is unaffected by this entry point.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from zoneinfo import ZoneInfo

from leader_watch.config import load_config
from leader_watch.engine import Engine
from leader_watch.notifiers.console import ConsoleNotifier
from leader_watch.notifiers.telegram import TelegramNotifier
from leader_watch.providers.mock import MockProvider
from leader_watch.providers.kis.config import KisConfigError
from leader_watch.providers.real import RealProvider
from leader_watch.store import AlertStore

try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID = "", ""


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="09:00-10:30 morning leader-stock watch system")
    parser.add_argument("--provider", choices=["mock", "real"], default="mock")
    parser.add_argument("--notifier", choices=["console", "telegram"], default="console")
    parser.add_argument("--single-tick", action="store_true", help="run exactly one poll and exit (used by tests/manual checks)")
    return parser


def leader_watch_main(argv: list[str]) -> int:
    args = build_arg_parser().parse_args(argv)
    config = load_config()

    try:
        provider = MockProvider() if args.provider == "mock" else RealProvider()
    except KisConfigError as exc:
        print(f"[leader_watch] {exc}", file=sys.stderr)
        return 1

    notifier = ConsoleNotifier() if args.notifier == "console" else TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    store = AlertStore(config.db_path)

    engine = Engine(provider=provider, notifier=notifier, config=config, store=store)

    try:
        if args.single_tick:
            now = datetime.datetime.now(ZoneInfo(config.market_timezone)).replace(tzinfo=None)
            engine.run_once(now)
        else:
            engine.run()
    except NotImplementedError as exc:
        # A provider explicitly signaled it isn't wired up yet.
        print(
            f"[leader_watch] 실시간 시세 제공자가 아직 구현되지 않았습니다: {exc}\n"
            "  --provider mock 으로 실행하거나 해당 provider를 구현하세요.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(leader_watch_main(sys.argv[1:]))
