from paper_trader.config import settings
from paper_trader.execution.paper_trader import PaperTrader
from paper_trader.history import history_view
from scripts.render_status_page import market_card


def _trader():
    return PaperTrader(1000.0, settings.commission_rate, settings.slippage_rate)


def test_closed_trade_shows_realized_profit_and_orders_newest_first():
    t = _trader()
    t.place_order("b1", "AAA", "BUY", 5.0, 100.0, "S")
    t.place_order("s1", "AAA", "SELL", 5.0, 120.0, "S", reasoning="exit")
    v = history_view(t)
    assert v["num_closed"] == 1 and v["realized_pnl"] > 0
    trade = v["closed_trades"][0]
    assert trade["symbol"] == "AAA" and trade["pnl"] > 0 and trade["pnl_pct"] > 0
    assert [o["side"] for o in v["recent_orders"]] == ["SELL", "BUY"]
    assert v["avg_win"] > 0 and v["avg_loss"] is None


def test_loss_and_rejected_order_are_visible():
    t = _trader()
    t.place_order("b1", "AAA", "BUY", 5.0, 100.0, "S")
    t.place_order("s1", "AAA", "SELL", 5.0, 80.0, "S")
    t.place_order("b2", "BBB", "BUY", 999.0, 100.0, "S")  # cannot afford
    v = history_view(t)
    assert v["realized_pnl"] < 0 and v["avg_loss"] < 0
    assert v["recent_orders"][0]["status"] == "REJECTED" and v["recent_orders"][0]["reason"] == "Insufficient capital"


def test_empty_history_is_explicit():
    v = history_view(_trader())
    assert v["closed_trades"] == [] and v["recent_orders"] == [] and v["num_closed"] == 0


def test_dashboard_card_renders_trade_history():
    t = _trader()
    t.place_order("b1", "AAA", "BUY", 5.0, 100.0, "S")
    t.place_order("s1", "AAA", "SELL", 5.0, 120.0, "S")
    data = {**t.get_performance_metrics(), "positions": [], **history_view(t)}
    html = market_card("US", "US Stocks", data)
    assert "Closed trades" in html and "AAA" in html and "FILLED" in html
    empty = market_card("US", "US Stocks", {**_trader().get_performance_metrics(), "positions": [], **history_view(_trader())})
    assert "nothing has been sold" in empty


def test_sell_order_carries_its_own_pnl():
    t = _trader()
    t.place_order("b1", "AAA", "BUY", 5.0, 100.0, "S")
    sell = t.place_order("s1", "AAA", "SELL", 5.0, 120.0, "S")
    assert sell["pnl"] > 0 and sell["pnl_pct"] > 0


def test_dashboard_trims_float_noise_and_collapses_extra_trades():
    from scripts.render_status_page import qty

    assert qty(0.011499999999999996) == "0.0115" and qty(2.0) == "2" and qty(1500.0) == "1,500"
    t = _trader()
    for i in range(5):
        t.place_order(f"b{i}", "AAA", "BUY", 1.0, 100.0, "S")
        t.place_order(f"s{i}", "AAA", "SELL", 1.0, 110.0, "S")
    data = {**t.get_performance_metrics(), "positions": [], **history_view(t)}
    html = market_card("US", "US Stocks", data)
    assert html.count("Sold ") == 5 and 'class="fold" open' in html  # all rows present, collapsible, open by default (JS closes on phones)


def test_open_position_row_shows_current_price():
    t = _trader()
    t.place_order("b1", "AAA", "BUY", 5.0, 100.0, "S")
    t.update_prices({"AAA": 123.45})
    pos = t.portfolio.positions["AAA"]
    row = {"symbol": "AAA", "quantity": 5.0, "entry_price": pos["entry_price"], "current_price": 123.45,
           "invested": pos["entry_price"] * 5, "current_value": 123.45 * 5,
           "unrealized_pnl": (123.45 - pos["entry_price"]) * 5, "unrealized_pnl_pct": 23.0}
    html = market_card("US", "US Stocks", {**t.get_performance_metrics(), "positions": [row], **history_view(t)})
    assert "123.45" in html and "Avg." in html and "LTP" in html and "Invested" in html


def test_card_labels_market_value_as_in_positions_not_invested():
    t = _trader()
    html = market_card("US", "US Stocks", {**t.get_performance_metrics(), "positions": [], **history_view(t)})
    assert "in positions" in html and "invested $" not in html


def test_broker_style_holdings_summary_and_day_change():
    from scripts.render_status_page import _indian_group, holdings_block, money

    assert _indian_group(398979.88) == "3,98,979.88" and _indian_group(999.5) == "999.50" and _indian_group(12345678.9) == "1,23,45,678.90"
    assert money("₹", -9315.34) == "-₹9,315.34" and money("$", 1234.5) == "$1,234.50"
    pos = [{"symbol": "AAA", "quantity": 14.0, "entry_price": 444.42, "current_price": 465.10, "invested": 6221.9,
            "current_value": 6511.4, "unrealized_pnl": 289.5, "unrealized_pnl_pct": 4.65},
           {"symbol": "BBB", "quantity": 39.0, "entry_price": 319.95, "current_price": 310.51, "invested": 12478.05,
            "current_value": 12109.89, "unrealized_pnl": -368.16, "unrealized_pnl_pct": -2.95}]
    html = holdings_block("₹", pos, {"AAA": -0.19})
    assert "Invested" in html and "Current" in html and "₹18,699.95" in html  # 6221.9 + 12478.05
    assert "Qty. 14 &bull; Avg. 444.42" in html and "LTP 465.10" in html and "-0.19%" in html
    assert "+₹289.50" in html and "-₹368.16" in html
    assert "No open positions" in holdings_block("$", [], {})


def test_times_shown_in_ist():
    from scripts.render_status_page import to_ist

    assert to_ist("2026-10-27 22:25 UTC") == "2026-10-28 03:55 IST"  # crosses midnight
    assert to_ist("2026-09-23 04:41", suffix=False) == "2026-09-23 10:11"
    assert to_ist("garbage") == "garbage"
