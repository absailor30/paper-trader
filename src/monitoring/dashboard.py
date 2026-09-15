"""
Streamlit Live Monitoring Dashboard for Paper Trader
Displays US and Indian portfolio status, live PnL, active positions, trade history, and watchlist research.
"""
import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime

st.set_page_config(
    page_title="AI Paper Trader Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Autonomous AI Paper Trader")
st.caption(f"Real-time Paper Portfolio & Intelligence Monitor | Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def load_portfolio(filepath: str) -> dict:
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

us_pf = load_portfolio("logs/us_portfolio.json")
india_pf = load_portfolio("logs/india_portfolio.json")

tab_us, tab_india, tab_watchlist, tab_benchmark = st.tabs([
    "🇺🇸 US Stocks ($100)",
    "🇮🇳 Indian Stocks (₹10,000)",
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
            pos_data.append({
                "Symbol": sym,
                "Strategy": p.get("strategy", "-"),
                "Shares": p["quantity"],
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
            in_pos_data.append({
                "Symbol": sym,
                "Strategy": p.get("strategy", "-"),
                "Shares": p["quantity"],
                "Entry Price": f"₹{p['entry_price']:.2f}",
                "Current Price": f"₹{p['current_price']:.2f}",
                "Stop Loss": f"₹{p.get('stop_loss', 0):.2f}",
                "Take Profit": f"₹{p.get('take_profit', 0):.2f}",
                "Position PnL": f"₹{pnl:+.2f} ({pnl_pct:+.2f}%)",
            })
        st.dataframe(pd.DataFrame(in_pos_data), use_container_width=True)
    else:
        st.info("No active Indian positions. Cash standing by for high-expectancy setups.")

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
