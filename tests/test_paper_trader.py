import pytest

from paper_trader.execution.paper_trader import PaperTrader


def make_trader(capital=1000.0):
    return PaperTrader(initial_capital=capital, commission_rate=0.001, slippage_rate=0.0005)


def test_buy_deducts_capital_and_opens_position():
    trader = make_trader()
    order = trader.place_order("order-1", "AAPL", "BUY", 1, 100.0, "TEST")
    assert order["status"] == "FILLED"
    assert "AAPL" in trader.portfolio.positions
    assert trader.portfolio.capital < 1000.0


def test_insufficient_capital_rejects_order():
    trader = make_trader(capital=10.0)
    order = trader.place_order("order-1", "AAPL", "BUY", 1, 500.0, "TEST")
    assert order["status"] == "REJECTED"
    assert "AAPL" not in trader.portfolio.positions
    assert trader.portfolio.capital == 10.0


def test_sell_without_position_rejects():
    trader = make_trader()
    order = trader.place_order("order-1", "AAPL", "SELL", 1, 100.0, "TEST")
    assert order["status"] == "REJECTED"


def test_same_client_order_id_is_idempotent():
    trader = make_trader()
    order1 = trader.place_order("dup-order", "AAPL", "BUY", 1, 100.0, "TEST")
    capital_after_first = trader.portfolio.capital
    order2 = trader.place_order("dup-order", "AAPL", "BUY", 1, 100.0, "TEST")

    assert order1 == order2
    assert trader.portfolio.capital == capital_after_first
    assert len(trader.orders) == 1
    assert trader.portfolio.positions["AAPL"]["quantity"] == 1


def test_full_round_trip_pnl():
    trader = make_trader(capital=2000.0)
    trader.place_order("buy-1", "AAPL", "BUY", 10, 100.0, "TEST")
    trader.update_prices({"AAPL": 110.0})
    trader.place_order("sell-1", "AAPL", "SELL", 10, 110.0, "TEST")

    assert "AAPL" not in trader.portfolio.positions
    assert len(trader.portfolio.trade_history) == 1
    assert trader.portfolio.trade_history[0]["pnl"] > 0


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    import paper_trader.persistence.state_store as state_store
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    state_store.Base.metadata.create_all(engine)
    monkeypatch.setattr(state_store, "_engine", engine)
    monkeypatch.setattr(state_store, "_Session", sessionmaker(bind=engine))

    trader = make_trader()
    trader.place_order("buy-1", "AAPL", "BUY", 5, 100.0, "TEST")
    trader.save("test_portfolio")

    trader2 = make_trader()
    found = trader2.load("test_portfolio")
    assert found is True
    assert trader2.portfolio.positions["AAPL"]["quantity"] == 5
    assert trader2.portfolio.capital == trader.portfolio.capital

    # Idempotency survives a reload: replaying the same order id after
    # loading persisted state must still be a no-op.
    trader2.place_order("buy-1", "AAPL", "BUY", 5, 100.0, "TEST")
    assert trader2.portfolio.positions["AAPL"]["quantity"] == 5
