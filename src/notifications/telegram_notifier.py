"""
Telegram notifier module for real-time paper trading alerts.
Dispatches messages to user via Telegram Bot API.
Gracefully skips if credentials are not configured.
"""
import requests
from loguru import logger
from typing import Optional
from config.config import settings

class TelegramNotifier:
    """Send trading updates and risk alerts to Telegram"""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or getattr(settings, 'telegram_bot_token', '')
        self.chat_id = chat_id or getattr(settings, 'telegram_chat_id', '')
        self.enabled = bool(self.bot_token and self.chat_id)
        if not self.enabled:
            logger.info("Telegram notifications disabled (missing bot_token or chat_id in .env)")

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send message via Telegram Bot API"""
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        try:
            r = requests.post(url, json=payload, timeout=8)
            if r.status_code == 200:
                return True
            else:
                logger.error(f"Telegram API error ({r.status_code}): {r.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to deliver Telegram notification: {e}")
            return False

    def send_trade_alert(self, order: dict, market: str = "US"):
        """Format and send trade execution notification"""
        sym = order.get("symbol", "?")
        side = order.get("side", "?")
        qty = order.get("quantity", 0)
        p = order.get("price", 0.0)
        strat = order.get("strategy", "-")
        reason = order.get("reasoning", "")
        currency = "$" if market == "US" else "INR "

        emoji = "🟢" if side == "BUY" else "🔴"
        text = (
            f"<b>{emoji} Paper Trade {side} Alert ({market})</b>\n\n"
            f"<b>Symbol:</b> <code>{sym}</code>\n"
            f"<b>Quantity:</b> <code>{qty}</code>\n"
            f"<b>Price:</b> <code>{currency}{p:.2f}</code>\n"
            f"<b>Strategy:</b> <i>{strat}</i>\n"
            f"<b>Reason:</b> {reason[:100]}\n"
        )
        return self.send_message(text)

    def send_heartbeat(self, us_positions: dict, in_positions: dict):
        """Periodic status update sent by live monitor"""
        us_summary = ", ".join([f"{s} (${p['current_price']:.2f})" for s, p in us_positions.items()]) or "Cash only"
        in_summary = ", ".join([f"{s} (INR {p['current_price']:.2f})" for s, p in in_positions.items()]) or "Cash only"

        text = (
            "<b>💓 Live Monitor Heartbeat</b>\n\n"
            f"<b>Status:</b> Active (5s polling)\n"
            f"<b>US Positions:</b> {us_summary}\n"
            f"<b>India Positions:</b> {in_summary}\n"
        )
        return self.send_message(text)

notifier = TelegramNotifier()
