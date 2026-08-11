from unittest.mock import patch, MagicMock

from leader_watch.notifiers.base import AlertNotifier
from leader_watch.notifiers.console import ConsoleNotifier
from leader_watch.notifiers.telegram import TelegramNotifier


def test_console_notifier_prints_title_and_body(capsys):
    notifier = ConsoleNotifier()
    assert isinstance(notifier, AlertNotifier)
    result = notifier.send("[09:10 조기 주도주 후보]", "종목: 테스트전자(005930)")
    captured = capsys.readouterr()
    assert result is True
    assert "[09:10 조기 주도주 후보]" in captured.out
    assert "테스트전자" in captured.out


def test_telegram_notifier_returns_false_when_token_missing():
    notifier = TelegramNotifier(bot_token="", chat_id="")
    assert notifier.send("title", "body") is False


@patch("leader_watch.notifiers.telegram.requests.post")
def test_telegram_notifier_posts_to_bot_api(mock_post):
    mock_post.return_value = MagicMock(status_code=200, ok=True)
    notifier = TelegramNotifier(bot_token="TOKEN123", chat_id="CHAT456")
    result = notifier.send("[제목]", "본문")
    assert result is True
    args, kwargs = mock_post.call_args
    assert "TOKEN123" in args[0]
    assert kwargs["data"]["chat_id"] == "CHAT456"
    assert "[제목]" in kwargs["data"]["text"]


@patch("leader_watch.notifiers.telegram.requests.post")
def test_telegram_notifier_returns_false_on_request_exception(mock_post):
    mock_post.side_effect = Exception("network error")
    notifier = TelegramNotifier(bot_token="TOKEN123", chat_id="CHAT456")
    assert notifier.send("title", "body") is False
