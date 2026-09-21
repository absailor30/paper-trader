from unittest.mock import patch

from paper_trader.config import settings
from paper_trader.notify import notify_fetch_failure, notify_order, send_telegram_message


def test_send_telegram_message_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "")
    monkeypatch.setattr(settings, "telegram_chat_id", "")
    with patch("paper_trader.notify.requests.post") as mock_post:
        send_telegram_message("hello")
    mock_post.assert_not_called()


def test_send_telegram_message_posts_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "TOKEN")
    monkeypatch.setattr(settings, "telegram_chat_id", "12345")
    with patch("paper_trader.notify.requests.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        send_telegram_message("hello")
    mock_post.assert_called_once()
    url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
    assert url == "https://api.telegram.org/botTOKEN/sendMessage"
    assert kwargs["json"]["chat_id"] == "12345"
    assert kwargs["json"]["text"] == "hello"


def test_send_telegram_message_never_raises_on_network_failure(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "TOKEN")
    monkeypatch.setattr(settings, "telegram_chat_id", "12345")
    with patch("paper_trader.notify.requests.post", side_effect=ConnectionError("no network")):
        send_telegram_message("hello")  # must not raise


def test_notify_order_sends_for_filled(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "TOKEN")
    monkeypatch.setattr(settings, "telegram_chat_id", "12345")
    order = {"status": "FILLED", "side": "BUY", "symbol": "AMD", "quantity": 0.08, "price": 614.91, "reasoning": "breakout"}
    with patch("paper_trader.notify.send_telegram_message") as mock_send:
        notify_order("US", order)
    mock_send.assert_called_once()
    text = mock_send.call_args[0][0]
    assert "FILLED" in text and "AMD" in text and "US" in text


def test_notify_order_sends_for_rejected_with_reason(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "TOKEN")
    monkeypatch.setattr(settings, "telegram_chat_id", "12345")
    order = {"status": "REJECTED", "side": "BUY", "symbol": "QQQ", "reason": "Insufficient capital"}
    with patch("paper_trader.notify.send_telegram_message") as mock_send:
        notify_order("US", order)
    text = mock_send.call_args[0][0]
    assert "REJECTED" in text and "Insufficient capital" in text


def test_notify_order_silent_for_non_terminal_status():
    with patch("paper_trader.notify.send_telegram_message") as mock_send:
        notify_order("US", {"status": "PENDING"})
    mock_send.assert_not_called()


def test_notify_fetch_failure_sends_when_zero_received():
    with patch("paper_trader.notify.send_telegram_message") as mock_send:
        notify_fetch_failure("CRYPTO", 8, 0)
    mock_send.assert_called_once()
    assert "0/8" in mock_send.call_args[0][0]


def test_notify_fetch_failure_silent_when_some_data_received():
    with patch("paper_trader.notify.send_telegram_message") as mock_send:
        notify_fetch_failure("CRYPTO", 8, 3)
    mock_send.assert_not_called()
