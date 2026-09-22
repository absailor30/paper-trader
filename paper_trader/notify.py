"""
Telegram push notifications for real trade events (fills, rejections) and
fetch-pipeline failures -- the "no trade for 3 days, is the fetch even
working?" question this project kept hitting by hand, automated.

No-ops silently whenever telegram_bot_token/telegram_chat_id aren't
configured, so local dev and every test run needs zero Telegram
credentials and never makes a network call.
"""
import requests
from loguru import logger

from paper_trader.config import settings


def send_telegram_message(text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        # A failed notification must never break a trading cycle.
        logger.warning(f"Telegram notification failed: {e}")


def notify_order(market: str, order: dict) -> None:
    status = order.get("status")
    if status not in ("FILLED", "REJECTED"):
        return

    emoji = "\U0001F7E2" if status == "FILLED" else "\U0001F534"
    side = order.get("side", "?")
    symbol = order.get("symbol", "?")
    qty = order.get("quantity")
    price = order.get("price")

    lines = [f"{emoji} <b>{status}</b> {side} {symbol} ({market})"]
    if qty is not None and price is not None:
        lines.append(f"{qty} @ ${price:,.2f}")
    if status == "REJECTED" and order.get("reason"):
        lines.append(f"Reason: {order['reason']}")
    elif order.get("reasoning"):
        lines.append(order["reasoning"])

    send_telegram_message("\n".join(lines))


def notify_circuit_breaker(market: str, reason: str) -> None:
    """Call when check_risk_limits() trips (daily loss or max drawdown) --
    this silently blocks all new entries for the rest of the cycle with
    only a log line, otherwise (e.g. the real -5.61% US daily-loss trip
    that motivated this)."""
    send_telegram_message(f"\U0001F6D1 <b>{market} circuit breaker</b>\n{reason} -- new entries blocked this cycle.")


def notify_fetch_failure(market: str, requested: int, received: int) -> None:
    """Call when a fetch cycle comes back with far less data than
    requested -- e.g. every symbol 451ing/404ing silently, the exact
    failure mode that went unnoticed for 3+ days on crypto before this
    project started actually checking job logs by hand."""
    if received > 0:
        return
    send_telegram_message(
        f"⚠️ <b>{market} fetch failure</b>\n"
        f"0/{requested} symbols returned data -- check the data source, "
        f"not just whether the job reported \"success\"."
    )
