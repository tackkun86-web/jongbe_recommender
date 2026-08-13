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


from leader_watch.providers.kis.config import KisConfigError


def test_leader_watch_main_reports_missing_kis_credentials_without_traceback(monkeypatch, capsys):
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_APP_SECRET", raising=False)
    exit_code = leader_watch_main(["--provider", "real", "--notifier", "console", "--single-tick"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "KIS_APP_KEY" in captured.err or "KIS" in captured.err
    assert "Traceback" not in captured.err


@patch("main.Engine")
def test_leader_watch_main_reports_not_implemented_provider_without_traceback(mock_engine_cls, capsys):
    # `main.py`'s `except NotImplementedError:` branch is reachable by any
    # provider's `engine.run()`/`run_once()` raising it — not specific to
    # RealProvider (which is no longer a stub). Drive it via a mocked Engine
    # so this test never touches RealProvider()/KIS credentials at all.
    instance = mock_engine_cls.return_value
    instance.run_once.side_effect = NotImplementedError("some provider message")
    exit_code = leader_watch_main(["--provider", "mock", "--notifier", "console", "--single-tick"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "some provider message" in captured.err
    assert "Traceback" not in captured.err
