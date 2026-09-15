"""
Continuous background price monitor and auto-exit manager.
Polls live prices for active positions every 5 seconds ONLY during active market hours:
- Indian Market (NSE/BSE): 09:15 to 15:30 IST (Monday - Friday)
- US Market (NYSE/NASDAQ): 09:30 to 16:00 EST/EDT (Monday - Friday)

Outside market hours:
- Fully halts 5-second polling to conserve compute and avoid rate limits.
- Calculates exact remaining seconds until 06:00:00 AM IST.
- At 06:00 AM IST: executes pre-market quantitative screening, updates watchlist,
  and dispatches daily morning intelligence digest to Telegram.
- Re-enters monitor mode before 09:15 IST opening bell.
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
                entry = pos['entry_price']
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
                entry = pos['entry_price']
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

def seconds_until_6am_ist() -> float:
    """Calculate exact seconds until next 06:00:00 AM IST"""
    now_ist = datetime.now(TZ_INDIA)
    target = now_ist.replace(hour=6, minute=0, second=0, microsecond=0)
    if now_ist >= target:
        target += timedelta(days=1)
    return (target - now_ist).total_seconds()

def run_live_monitor():
    """Main loop: 5s poll during market hours, scheduled 6 AM IST research when closed"""
    logger.info("=" * 65)
    logger.info("AUTONOMOUS REAL-TIME PRICE & RISK MONITOR LAUNCHED")
    logger.info("Active Market Polling: 5 seconds")
    logger.info("NSE Hours: 09:15 - 15:30 IST | US Hours: 09:30 - 16:00 EST")
    logger.info("Off-Market Schedule: Sleep until 06:00 AM IST for autonomous research")
    logger.info("=" * 65)

    us_trader = PaperTrader(initial_capital=settings.us_capital)
    india_trader = PaperTrader(initial_capital=settings.india_capital)

    last_heartbeat = 0
    heartbeat_interval = getattr(settings, 'telegram_heartbeat_hours', 1) * 3600
    last_research_date = None

    while True:
        try:
            market_active = monitor_pass(us_trader, india_trader)

            now_ist = datetime.now(TZ_INDIA)
            current_date_ist = now_ist.strftime('%Y-%m-%d')

            # Trigger 6:00 AM IST research once per calendar day
            if now_ist.hour == 6 and now_ist.minute < 15 and last_research_date != current_date_ist:
                logger.info("06:00 AM IST reached. Executing autonomous pre-market research routine.")
                try:
                    run_premarket_research()
                    last_research_date = current_date_ist
                except Exception as res_err:
                    logger.error(f"Pre-market research error: {res_err}")

            if market_active:
                # Active market polling
                now = time.time()
                if now - last_heartbeat >= heartbeat_interval:
                    notifier.send_heartbeat(us_trader.portfolio.positions, india_trader.portfolio.positions)
                    last_heartbeat = now
                time.sleep(5)
            else:
                # Both markets closed: do not poll prices
                sleep_secs = seconds_until_6am_ist()
                # If within 15 minutes of 6am, sleep in short 30s checks so we hit the window cleanly
                if sleep_secs > 900:
                    hours_rem = sleep_secs / 3600
                    logger.info(f"Markets closed. Halting price polling. Sleeping {hours_rem:.2f} hrs until 06:00 AM IST research.")
                    # Sleep in 60s intervals to remain responsive to interruptions and state changes
                    time.sleep(60)
                else:
                    time.sleep(30)

        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_live_monitor()
