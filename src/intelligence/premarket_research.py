"""
Autonomous Pre-Market Research Engine.
Runs daily at 06:00 AM IST (or on-demand).
- Scans global macro regime and commodities (Crude, Gold, US Futures).
- Screens Nifty 50 and US focus universes across classical quantitative models.
- Updates data/watchlist_research.json.
- Dispatches formatted intelligence briefing directly to Telegram.
"""
import sys
import os
import json
from datetime import datetime
import zoneinfo
import pandas as pd
from loguru import logger

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.data.data_fetcher import DataFetcher
from src.strategies.indicators import sma, rsi, bollinger_bands
from src.notifications import notifier
from config.config import settings

TZ_INDIA = zoneinfo.ZoneInfo("Asia/Kolkata")

def run_premarket_research() -> dict:
    """Execute pre-market research sweep across US and Indian equities"""
    now_ist = datetime.now(TZ_INDIA)
    date_str = now_ist.strftime('%Y-%m-%d')
    time_str = now_ist.strftime('%H:%M IST')

    logger.info(f"Starting Pre-Market Research for {date_str} at {time_str}")

    fetcher = DataFetcher()

    # 1. Macro Regime Check
    macro_tickers = {
        "Crude Oil": "CL=F",
        "Gold": "GC=F",
        "S&P 500 Futures": "ES=F",
        "India Nifty 50": "^NSEI"
    }

    macro_summary = {}
    for name, sym in macro_tickers.items():
        try:
            df = fetcher.fetch_us_stock_data(sym, start_date=(now_ist - pd.Timedelta(days=10)).strftime('%Y-%m-%d'))
            if not df.empty and len(df) >= 2:
                last_c = df['close'].iloc[-1]
                prev_c = df['close'].iloc[-2]
                pct = ((last_c - prev_c) / prev_c) * 100
                macro_summary[name] = f"{last_c:.2f} ({pct:+.2f}%)"
            elif not df.empty:
                macro_summary[name] = f"{df['close'].iloc[-1]:.2f}"
        except Exception:
            pass

    # 2. Indian Universe Screening (Nifty 50 Key constituents)
    india_universe = settings.india_stocks
    india_candidates = []

    for sym in india_universe:
        try:
            df = fetcher.fetch_india_stock_data(sym, start_date=(now_ist - pd.Timedelta(days=365)).strftime('%Y-%m-%d'))
            if df.empty or len(df) < 50:
                continue

            c = df['close'].iloc[-1]
            s50 = sma(df['close'], 50).iloc[-1]
            s150 = sma(df['close'], 150).iloc[-1] if len(df) >= 150 else s50
            r = rsi(df['close'], 14).iloc[-1]
            v_ratio = df['volume'].iloc[-1] / df['volume'].tail(20).mean() if df['volume'].tail(20).mean() > 0 else 0

            # Tag candidate catalysts
            if c > s50 and c > s150 and v_ratio > 1.2:
                india_candidates.append({
                    "Symbol": f"{sym}.NS",
                    "Price": f"INR {c:.2f}",
                    "Setup": "Stage 2 Continuation",
                    "RSI": round(r, 1),
                    "Vol_Surge": f"{v_ratio:.2f}x"
                })
            elif r < 30:
                india_candidates.append({
                    "Symbol": f"{sym}.NS",
                    "Price": f"INR {c:.2f}",
                    "Setup": "Oversold Mean Reversion",
                    "RSI": round(r, 1),
                    "Vol_Surge": f"{v_ratio:.2f}x"
                })
        except Exception:
            pass

    # 3. US Focus Screening
    us_universe = settings.us_stocks
    us_candidates = []

    for sym in us_universe:
        try:
            df = fetcher.fetch_us_stock_data(sym, start_date=(now_ist - pd.Timedelta(days=365)).strftime('%Y-%m-%d'))
            if df.empty or len(df) < 50:
                continue

            c = df['close'].iloc[-1]
            s50 = sma(df['close'], 50).iloc[-1]
            s150 = sma(df['close'], 150).iloc[-1] if len(df) >= 150 else s50
            r = rsi(df['close'], 14).iloc[-1]
            v_ratio = df['volume'].iloc[-1] / df['volume'].tail(20).mean() if df['volume'].tail(20).mean() > 0 else 0

            if c > s50 and c > s150 and v_ratio > 1.2:
                us_candidates.append({
                    "Symbol": sym,
                    "Price": f"${c:.2f}",
                    "Setup": "SEPA / Momentum Breakout",
                    "RSI": round(r, 1),
                    "Vol_Surge": f"{v_ratio:.2f}x"
                })
            elif r < 32:
                us_candidates.append({
                    "Symbol": sym,
                    "Price": f"${c:.2f}",
                    "Setup": "Oversold Pullback",
                    "RSI": round(r, 1),
                    "Vol_Surge": f"{v_ratio:.2f}x"
                })
        except Exception:
            pass

    # Save to data/watchlist_research.json
    research_payload = {
        "last_updated": date_str,
        "market_regime": {
            "GLOBAL": macro_summary,
            "US_COUNT": len(us_candidates),
            "INDIA_COUNT": len(india_candidates)
        },
        "US_CANDIDATES": us_candidates[:5],
        "INDIA_CANDIDATES": india_candidates[:5]
    }

    os.makedirs("data", exist_ok=True)
    with open("data/watchlist_research.json", "w") as f:
        json.dump(research_payload, f, indent=2)

    # 4. Dispatch Telegram Briefing
    macro_text = "\n".join([f"• <b>{k}:</b> {v}" for k, v in macro_summary.items()]) or "Data pending"
    in_text = "\n".join([f"• <b>{x['Symbol']}</b>: {x['Setup']} (RSI: {x['RSI']}, Vol: {x['Vol_Surge']})" for x in india_candidates[:4]]) or "No high-conviction triggers"
    us_text = "\n".join([f"• <b>{x['Symbol']}</b>: {x['Setup']} (RSI: {x['RSI']}, Vol: {x['Vol_Surge']})" for x in us_candidates[:4]]) or "No high-conviction triggers"

    tg_message = (
        f"🌅 <b>6:00 AM IST Pre-Market Intelligence Briefing</b>\n"
        f"📅 Date: <b>{date_str}</b>\n\n"
        f"<b>🌍 Global Macro Indicators:</b>\n{macro_text}\n\n"
        f"<b>🇮🇳 High-Expectancy Indian Watchlist:</b>\n{in_text}\n\n"
        f"<b>🇺🇸 High-Expectancy US Watchlist:</b>\n{us_text}\n\n"
        f"<i>Automated screening complete. Live monitor scheduled for 09:15 IST opening bell.</i>"
    )

    notifier.send_message(tg_message)
    logger.info("Pre-market research completed and Telegram briefing dispatched.")

    return research_payload

if __name__ == "__main__":
    run_premarket_research()
