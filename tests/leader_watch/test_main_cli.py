import argparse
from unittest.mock import patch

from main import build_arg_parser, leader_watch_main


def test_arg_parser_defaults():
    parser = build_arg_parser()
    args = parser.parse_args([])
    assert args.provider == "mock"
    assert args.notifier == "console"


def test_arg_parser_accepts_real_and_telegram():
    parser = build_arg_parser()
    args = parser.parse_args(["--provider", "real", "--notifier", "telegram"])
    assert args.provider == "real"
    assert args.notifier == "telegram"


def test_arg_parser_rejects_invalid_provider():
    parser = build_arg_parser()
    try:
        parser.parse_args(["--provider", "bogus"])
        assert False, "should have raised"
    except SystemExit:
        pass


@patch("main.Engine")
def test_leader_watch_main_mock_provider_runs_single_tick_in_test_mode(mock_engine_cls):
    instance = mock_engine_cls.return_value
    exit_code = leader_watch_main(["--provider", "mock", "--notifier", "console", "--single-tick"])
    assert exit_code == 0
    instance.run_once.assert_called_once()
