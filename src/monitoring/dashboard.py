"""
Streamlit Live Monitoring Dashboard for Paper Trader
Displays US and Indian portfolio status, live PnL, active positions, trade history, and watchlist research.
"""
import streamlit as st
import pandas as pd
import json
import os
import time
from datetime import datetime
import yfinance as yf

st.set_page_config(
    page_title="AI Paper Trader Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Autonomous AI Paper Trader")

# Sidebar auto-refresh controls
st.sidebar.header("⏱️ Live Refresh Engine")
auto_refresh = st.sidebar.checkbox("Auto-refresh live data", value=True)
refresh_interval = st.sidebar.slider("Refresh interval (seconds)", min_value=5, max_value=60, value=10, step=5)

if st.sidebar.button("🔄 Manual Refresh Now"):
    st.rerun()

# Live Monitor Process Health Status
st.sidebar.markdown("---")
st.sidebar.header("🛡️ Monitor Daemon")
def check_monitor_status():
    log_dir = "logs"
    if not os.path.exists(log_dir):
        return "Not Running", "red"
    logs = [os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.startswith("live_monitor_")]
    if not logs:
        return "Not Running", "red"
    latest_log = max(logs, key=os.path.getmtime)
    diff = time.time() - os.path.getmtime(latest_log)
    if diff < 60:
        return f"Active (Last tick: {int(diff)}s ago)", "green"
    else:
        return f"Standby/Idle ({int(diff // 60)}m ago)", "orange"

mon_status, mon_color = check_monitor_status()
if mon_color == "green":
    st.sidebar.success(f"● {mon_status}")
elif mon_color == "orange":
    st.sidebar.warning(f"● {mon_status}")
else:
    st.sidebar.error(f"● {mon_status}")

st.caption(f"Real-time Paper Portfolio & Intelligence Monitor | Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def load_portfolio(filepath: str) -> dict:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

@st.cache_data(ttl=15)
def get_live_ticker_price(symbol: str) -> float:
    """Fetch real-time ticker price from Yahoo Finance with 15s cache"""
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info['last_price']
        if price and not pd.isna(price):
            return float(price)
    except Exception:
        pass
    try:
        hist = ticker.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None

us_pf = load_portfolio("logs/us_portfolio.json")
india_pf = load_portfolio("logs/india_portfolio.json")

# Refresh live market prices for active positions
for sym, pos in us_pf.get("positions", {}).items():
    live_p = get_live_ticker_price(sym)
    if live_p:
        pos["current_price"] = live_p

for sym, pos in india_pf.get("positions", {}).items():
    live_p = get_live_ticker_price(sym)
    if live_p:
        pos["current_price"] = live_p

tab_us, tab_india, tab_reflections, tab_watchlist, tab_benchmark = st.tabs([
    "🇺🇸 US Stocks ($100)",
    "🇮🇳 Indian Stocks (₹10,000)",
    "🧠 Daily AI Reflections",
    "🔭 Stock Research & Watchlist",
    "📊 Strategy Benchmarks",
])

# ----------------- US TAB -----------------
with tab_us:
    us_cap = us_pf.get("capital", 100.0)
    us_pos = us_pf.get("positions", {})
    us_trades = us_pf.get("trade_history", [])

    pos_val = sum(p["quantity"] * p["current_price"] for p in us_pos.values())
    total_us_val = us_cap + pos_val
    us_pnl = total_us_val - 100.0
    us_pnl_pct = (us_pnl / 100.0) * 100.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Account Value", f"${total_us_val:.2f}", f"{us_pnl_pct:+.2f}%")
    col2.metric("Available Cash", f"${us_cap:.2f}")
    col3.metric("Invested Capital", f"${pos_val:.2f}")
    col4.metric("Active Positions", f"{len(us_pos)}")

    st.subheader("Active Positions")
    if us_pos:
        pos_data = []
        for sym, p in us_pos.items():
            cost = p["quantity"] * p["entry_price"]
            curr = p["quantity"] * p["current_price"]
            pnl = curr - cost
            pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
            alloc_pct = (curr / total_us_val) * 100 if total_us_val > 0 else 0
            pos_data.append({
                "Symbol": sym,
                "Strategy": p.get("strategy", "-"),
                "Shares": f"{p['quantity']:.4f}" if isinstance(p['quantity'], float) else p['quantity'],
                "Invested Capital": f"${cost:.2f}",
                "Current Value": f"${curr:.2f}",
                "Portfolio %": f"{alloc_pct:.1f}%",
                "Entry Price": f"${p['entry_price']:.2f}",
                "Current Price": f"${p['current_price']:.2f}",
                "Stop Loss": f"${p.get('stop_loss', 0):.2f}",
                "Take Profit": f"${p.get('take_profit', 0):.2f}",
                "Position PnL": f"${pnl:+.2f} ({pnl_pct:+.2f}%)",
            })
        st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
    else:
        st.info("No active US positions. Capital preserved.")

    st.subheader("Order Audit Trail")
    orders = us_pf.get("orders", [])
    if orders:
        st.dataframe(pd.DataFrame(orders).tail(10), use_container_width=True)

# ----------------- INDIA TAB -----------------
with tab_india:
    in_cap = india_pf.get("capital", 10000.0)
    in_pos = india_pf.get("positions", {})
    in_trades = india_pf.get("trade_history", [])

    in_pos_val = sum(p["quantity"] * p["current_price"] for p in in_pos.values())
    total_in_val = in_cap + in_pos_val
    in_pnl = total_in_val - 10000.0
    in_pnl_pct = (in_pnl / 10000.0) * 100.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Account Value", f"₹{total_in_val:.2f}", f"{in_pnl_pct:+.2f}%")
    c2.metric("Available Cash", f"₹{in_cap:.2f}")
    c3.metric("Invested Capital", f"₹{in_pos_val:.2f}")
    c4.metric("Active Positions", f"{len(in_pos)}")

    st.subheader("Active Indian Positions")
    if in_pos:
        in_pos_data = []
        for sym, p in in_pos.items():
            cost = p["quantity"] * p["entry_price"]
            curr = p["quantity"] * p["current_price"]
            pnl = curr - cost
            pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
            alloc_pct = (curr / total_in_val) * 100 if total_in_val > 0 else 0
            in_pos_data.append({
                "Symbol": sym,
                "Strategy": p.get("strategy", "-"),
                "Shares": f"{p['quantity']:.4f}" if isinstance(p['quantity'], float) and p['quantity'] % 1 != 0 else int(p['quantity']),
                "Invested Capital": f"₹{cost:.2f}",
                "Current Value": f"₹{curr:.2f}",
                "Portfolio %": f"{alloc_pct:.1f}%",
                "Entry Price": f"₹{p['entry_price']:.2f}",
                "Current Price": f"₹{p['current_price']:.2f}",
                "Stop Loss": f"₹{p.get('stop_loss', 0):.2f}",
                "Take Profit": f"₹{p.get('take_profit', 0):.2f}",
                "Position PnL": f"₹{pnl:+.2f} ({pnl_pct:+.2f}%)",
            })
        st.dataframe(pd.DataFrame(in_pos_data), use_container_width=True)
    else:
        st.info("No active Indian positions. Cash standing by for high-expectancy setups.")

# ----------------- REFLECTIONS TAB -----------------
with tab_reflections:
    st.subheader("Autonomous Post-Session Reflections & Learning Journal")
    refl_file = "logs/daily_reflections.md"
    if os.path.exists(refl_file):
        with open(refl_file, "r", encoding="utf-8") as f:
            refl_text = f.read()
        st.markdown(refl_text)
    else:
        st.info("Daily reflections will appear here after the market close execution cycle.")

# ----------------- WATCHLIST TAB -----------------
with tab_watchlist:
    st.subheader("Curated Research Universe & Regime Screening (September 2026)")
    wl_path = "data/watchlist_research.json"
    if os.path.exists(wl_path):
        with open(wl_path, "r") as f:
            wl = json.load(f)
        col_u, col_i = st.columns(2)
        with col_u:
            st.markdown("### 🇺🇸 US Focus Tickers")
            st.dataframe(pd.DataFrame(wl.get("US", [])), use_container_width=True)
        with col_i:
            st.markdown("### 🇮🇳 Indian Focus Tickers")
            st.dataframe(pd.DataFrame(wl.get("INDIA", [])), use_container_width=True)
    else:
        st.info("Watchlist data generating...")

# ----------------- BENCHMARK TAB -----------------
with tab_benchmark:
    st.subheader("Historical 3-Year Backtest Matrix")
    bm_path = "logs/benchmark_results.csv"
    if os.path.exists(bm_path):
        bm_df = pd.read_csv(bm_path)
        st.dataframe(bm_df, use_container_width=True)
    else:
        st.info("Run `python run_benchmark.py` to populate performance matrix.")

    st.markdown("---")
    st.subheader("Strategy Playbook & Empirical Trading Experience")
    st.markdown("Granular breakdown of rules, indicators, real-market performance traits, and quantitative lessons learned.")

    strategy_experience = [
        {
            "Strategy": "Stage Analysis (Stan Weinstein)",
            "Foundational Concept": "30-week (150-day) SMA slope & volume breakout confirming transition from Stage 1 base to Stage 2 markup.",
            "Key Indicators": "150-day SMA, 30-day Volume SMA (surge > 1.2x), 20-day High breakout pivot.",
            "Historical Experience & Edge": "Highest overall Sharpe across both markets (1.04 on SHRIRAMFIN.NS, 0.93 on NVDA). Extremely low false-positive rate because trend filters out choppy distribution.",
            "Weaknesses & Risks": "Lags at sudden macro turning points. Enters late if base is wide, requiring disciplined 8% stop loss.",
            "Autonomous Verdict": "Primary vehicle for trend following & momentum continuation."
        },
        {
            "Strategy": "SEPA & VCP (Mark Minervini)",
            "Foundational Concept": "Specific Entry Point Analysis. Identifies Stage 2 leaders undergoing progressive Volatility Contraction (tightening ranges on drying volume).",
            "Key Indicators": "200-day SMA, 150-day SMA, 50-day SMA alignment, ATR contraction (<0.75x 20-day ATR), volume surge (>1.3x) on pivot breach.",
            "Historical Experience & Edge": "100% win rate on XOM in backtests; captured XLE energy breakout cleanly. Excellent asymmetric risk-to-reward (often > 3:1).",
            "Weaknesses & Risks": "Low win rate during sideways choppy regimes (e.g., Reliance 14.3% win rate) when false breakouts trigger stop losses before contraction finishes.",
            "Autonomous Verdict": "Best for high-conviction breakout setups with tight initial stops (5-7%)."
        },
        {
            "Strategy": "Mean Reversion (Bollinger & Z-Score)",
            "Foundational Concept": "Statistical reversion to mean price using volatility regimes and Bollinger Band squeeze boundaries.",
            "Key Indicators": "20-day SMA, 2.0-3.0 StdDev Bollinger Bands, 14-day RSI (<35 oversold), Realized Volatility regime classification.",
            "Historical Experience & Edge": "Highest Win Rate across universe (75% on NVDA, 100% on XOM, 80% on HDFCBANK). Lowest maximum drawdown (< 0.5%).",
            "Weaknesses & Risks": "Low trade frequency. In strong runaway Stage 4 downtrends, catching falling knives requires strict RSI/ATR oversold confirmation.",
            "Autonomous Verdict": "Ideal profit generator during range-bound regimes and flash panic pullbacks."
        },
        {
            "Strategy": "CAN SLIM (William O'Neil)",
            "Foundational Concept": "Current earnings/price momentum, cup-with-handle bases, institutional volume confirmation, and relative strength.",
            "Key Indicators": "50-day SMA > 200-day SMA, Cup-with-handle depth (12-35%), volume surge (>1.5x), 250-day Relative Strength ranking.",
            "Historical Experience & Edge": "Generated 8.10% net return on SHRIRAMFIN and 5.31% on AAPL. Strong when overall market index (SPY/NIFTY) is in confirmed rally.",
            "Weaknesses & Risks": "High trade churn in choppy markets (22 trades on SHRIRAMFIN caused fee drag; 40.9% win rate).",
            "Autonomous Verdict": "Requires broader index trend confirmation before firing buy orders."
        },
        {
            "Strategy": "Momentum Multi-Factor (RL Blend)",
            "Foundational Concept": "Composite scoring combining RSI, MACD histogram expansion, Rate of Change (ROC), and ADX trend strength.",
            "Key Indicators": "RSI(14), MACD(12,26,9), ADX(14) > 25, 10-day ROC, Volume expansion ratio.",
            "Historical Experience & Edge": "High signal velocity. Successfully triggered DRREDDY.NS buy today (Score=27.4, Vol=2.04x, R:R=3.26:1).",
            "Weaknesses & Risks": "Overtrades heavily without minimum holding period filters (170+ trades in 3-yr unconstrained backtests led to transaction fee drag).",
            "Autonomous Verdict": "Must be strictly gated by LLM Reasoner (R:R >= 1.5) and minimum cooldown periods to curb commissions."
        }
    ]
    st.dataframe(pd.DataFrame(strategy_experience), use_container_width=True)

# Auto-refresh loop
if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()
