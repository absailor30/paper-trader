"""
Autonomous Real-Time Price Monitor, Strategy Executor & Risk Daemon.
Runs 24/7 in cloud container:
- 06:00 AM IST: Pre-market global macro screening & watchlist research.
- 09:35 AM IST: Autonomous Indian market regime analysis & trade entries.
- 15:35 IST: Indian market close EOD reflection & performance report.
- 09:45 AM EST: Autonomous US market regime analysis & trade entries.
- 16:05 EST: US market close EOD reflection & performance report.
- Continuous 5-second tick loop during market hours:
  - Real-time mark-to-market prices.
  - Automatic dynamic trailing stop ratchet (+10% gain -> trail 5% below peak).
  - Instant stop-loss (-6%) and take-profit auto-execution.
  - Instant Telegram trade alerts.
  - Hourly status heartbeat to Telegram.
"""
import sys
import os
import time
from datetime import datetime, time as dtime, timedelta
import zoneinfo
import yfinance as yf
from loguru import logger

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.main import TradingBot
from src.execution.paper_trader import PaperTrader
from src.notifications import notifier
from src.intelligence.premarket_research import run_premarket_research
from config.config import settings

# Timezones
TZ_INDIA = zoneinfo.ZoneInfo("Asia/Kolkata")
TZ_US = zoneinfo.ZoneInfo("America/New_York")

# Market working hours (Monday=0 to Friday=4)
INDIA_OPEN = dtime(9, 15)
INDIA_CLOSE = dtime(15, 30)

US_OPEN = dtime(9, 30)
US_CLOSE = dtime(16, 0)

# Configure logging
os.makedirs("logs", exist_ok=True)
logger.add(
    "logs/live_monitor_{time}.log",
    rotation="1 day",
    retention="7 days",
    level="INFO"
)

def is_india_market_open() -> bool:
    """Check if Indian market (NSE) is currently open"""
    now_ist = datetime.now(TZ_INDIA)
    if now_ist.weekday() > 4:
        return False
    current_time = now_ist.time()
    return INDIA_OPEN <= current_time <= INDIA_CLOSE

def is_us_market_open() -> bool:
    """Check if US market (NYSE/NASDAQ) is currently open"""
    now_us = datetime.now(TZ_US)
    if now_us.weekday() > 4:
        return False
    current_time = now_us.time()
    return US_OPEN <= current_time <= US_CLOSE

def fetch_live_price(symbol: str) -> float:
    """Fetch latest price via fast_info with intraday bar fallback"""
    try:
        t = yf.Ticker(symbol)
        price = t.fast_info['last_price']
        if price and not (isinstance(price, float) and price != price):
            return float(price)
    except Exception:
        pass

    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.debug(f"Failed to fetch live price for {symbol}: {e}")

    return None

def monitor_pass(us_trader: PaperTrader, india_trader: PaperTrader) -> bool:
    """Execute one pass of live price update and stop-loss check"""
    us_open = is_us_market_open()
    india_open = is_india_market_open()

    if not us_open and not india_open:
        return False

    us_state_path = "logs/us_portfolio.json"
    india_state_path = "logs/india_portfolio.json"

    if os.path.exists(us_state_path):
        us_trader.load_state(us_state_path)
    if os.path.exists(india_state_path):
        india_trader.load_state(india_state_path)

    changes = False

    # 1. Monitor US positions during US market hours
    if us_open and us_trader.portfolio.positions:
        us_prices = {}
        for sym, pos in list(us_trader.portfolio.positions.items()):
            p = fetch_live_price(sym)
            if p:
                us_prices[sym] = p
                entry = pos.get('entry_price', p)
                sl = pos.get('stop_loss', 0)
                tp = pos.get('take_profit', 0)
                pnl_pct = ((p - entry) / entry) * 100 if entry > 0 else 0
                logger.info(f"[US 5s TICK] {sym}: Live=${p:.2f} | Entry=${entry:.2f} | PnL={pnl_pct:+.2f}% | SL=${sl:.2f} | TP=${tp:.2f}")

        if us_prices:
            us_trader.update_prices(us_prices)
            us_exits = us_trader.check_stop_losses()
            if us_exits:
                logger.warning(f"[US STOP TRIGGERED] Orders: {[x['symbol'] for x in us_exits]}")
                for order in us_exits:
                    notifier.send_trade_alert(order, market="US")
            changes = True

    # 2. Monitor Indian positions during Indian market hours
    if india_open and india_trader.portfolio.positions:
        in_prices = {}
        for sym, pos in list(india_trader.portfolio.positions.items()):
            fetch_sym = sym if sym.endswith(('.NS', '.BO')) else f"{sym}.NS"
            p = fetch_live_price(fetch_sym)
            if p:
                in_prices[sym] = p
                entry = pos.get('entry_price', p)
                sl = pos.get('stop_loss', 0)
                tp = pos.get('take_profit', 0)
                pnl_pct = ((p - entry) / entry) * 100 if entry > 0 else 0
                logger.info(f"[INDIA 5s TICK] {sym}: Live=INR {p:.2f} | Entry=INR {entry:.2f} | PnL={pnl_pct:+.2f}% | SL=INR {sl:.2f} | TP=INR {tp:.2f}")

        if in_prices:
            india_trader.update_prices(in_prices)
            india_exits = india_trader.check_stop_losses()
            if india_exits:
                logger.warning(f"[INDIA STOP TRIGGERED] Orders: {[x['symbol'] for x in india_exits]}")
                for order in india_exits:
                    notifier.send_trade_alert(order, market="INDIA")
            changes = True

    if changes:
        us_trader.save_state(us_state_path)
        india_trader.save_state(india_state_path)

    return True

def run_live_monitor():
    """Main loop: 24/7 autonomous scheduling and real-time risk monitor"""
    logger.info("=" * 65)
    logger.info("AUTONOMOUS AI TRADING AGENT - 24/7 CLOUD DAEMON")
    logger.info("Market Regime Analysis | Autonomous Entry & Exit | Trailing Stops")
    logger.info("NSE Hours: 09:15 - 15:30 IST | US Hours: 09:30 - 16:00 EST")
    logger.info("=" * 65)

    bot = TradingBot()
    us_trader = bot.us_trader
    india_trader = bot.india_trader

    last_heartbeat = 0
    heartbeat_interval = getattr(settings, 'telegram_heartbeat_hours', 1) * 3600
    last_research_date = None
    last_india_entry_date = None
    last_india_eod_date = None
    last_us_entry_date = None
    last_us_eod_date = None

    while True:
        try:
            now_ist = datetime.now(TZ_INDIA)
            now_us = datetime.now(TZ_US)
            date_ist = now_ist.strftime('%Y-%m-%d')
            date_us = now_us.strftime('%Y-%m-%d')

            # 1. 06:00 AM IST: Pre-Market Global Macro Screening
            if now_ist.hour == 6 and now_ist.minute < 15 and last_research_date != date_ist:
                logger.info("06:00 AM IST reached. Executing autonomous pre-market research routine.")
                try:
                    run_premarket_research()
                    last_research_date = date_ist
                except Exception as res_err:
                    logger.error(f"Pre-market research error: {res_err}")

            # 2. 09:35 AM IST: Indian Market Autonomous Entry Cycle
            if now_ist.weekday() < 5 and now_ist.hour == 9 and 35 <= now_ist.minute <= 50 and last_india_entry_date != date_ist:
                logger.info("09:35 AM IST reached. Running autonomous Indian market entry cycle.")
                try:
                    bot.execute_market_cycle("INDIA")
                    last_india_entry_date = date_ist
                except Exception as in_err:
                    logger.error(f"Indian market entry cycle error: {in_err}")

            # 3. 15:35 IST: Indian Market Close EOD Reflection
            if now_ist.weekday() < 5 and now_ist.hour == 15 and 35 <= now_ist.minute <= 50 and last_india_eod_date != date_ist:
                logger.info("15:35 IST reached. Recording Indian market EOD reflection.")
                try:
                    bot.record_daily_reflection("INDIA")
                    last_india_eod_date = date_ist
                except Exception as in_eod_err:
                    logger.error(f"Indian market EOD reflection error: {in_eod_err}")

            # 4. 09:45 AM EST: US Market Autonomous Entry Cycle
            if now_us.weekday() < 5 and now_us.hour == 9 and 45 <= now_us.minute <= 59 and last_us_entry_date != date_us:
                logger.info("09:45 AM EST reached. Running autonomous US market entry cycle.")
                try:
                    bot.execute_market_cycle("US")
                    last_us_entry_date = date_us
                except Exception as us_err:
                    logger.error(f"US market entry cycle error: {us_err}")

            # 5. 16:05 EST: US Market Close EOD Reflection
            if now_us.weekday() < 5 and now_us.hour == 16 and 5 <= now_us.minute <= 20 and last_us_eod_date != date_us:
                logger.info("16:05 EST reached. Recording US market EOD reflection.")
                try:
                    bot.record_daily_reflection("US")
                    last_us_eod_date = date_us
                except Exception as us_eod_err:
                    logger.error(f"US market EOD reflection error: {us_eod_err}")

            # 6. Intraday price monitoring & trailing stops (5s ticks during active hours)
            market_active = monitor_pass(us_trader, india_trader)

            if market_active:
                now = time.time()
                if now - last_heartbeat >= heartbeat_interval:
                    notifier.send_heartbeat(us_trader.portfolio.positions, india_trader.portfolio.positions)
                    last_heartbeat = now
                time.sleep(5)
            else:
                # Outside active market hours: sleep 30s to keep loop responsive
                time.sleep(30)

        except Exception as e:
            logger.error(f"Error in autonomous live monitor loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_live_monitor()
