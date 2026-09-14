"""
Test script for Paper Trader system
"""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from data.data_fetcher import DataFetcher
from strategies import CANSLIMStrategy, SEPAStrategy
from execution.paper_trader import PaperTrader
from config.config import settings

def test_data_fetch():
    """Test data fetching"""
    print("=" * 50)
    print("Testing Data Fetcher")
    print("=" * 50)

    fetcher = DataFetcher()

    # Test US stock
    print("\n1. Fetching US stock data (AAPL)...")
    aapl = fetcher.fetch_us_stock_data('AAPL', start_date='2024-01-01')
    if not aapl.empty:
        print(f"   AAPL: {len(aapl)} bars")
        print(f"   Latest: {aapl['close'].iloc[-1]:.2f}")
    else:
        print("   ERROR: No data returned")

    # Test Indian stock
    print("\n2. Fetching Indian stock data (RELIANCE)...")
    reliance = fetcher.fetch_india_stock_data('RELIANCE', start_date='2024-01-01')
    if not reliance.empty:
        print(f"   RELIANCE: {len(reliance)} bars")
        print(f"   Latest: {reliance['close'].iloc[-1]:.2f}")
    else:
        print("   ERROR: No data returned")

    return aapl, reliance

def test_strategies(data):
    """Test strategy generation"""
    print("\n" + "=" * 50)
    print("Testing Strategies")
    print("=" * 50)

    if data.empty:
        print("   ERROR: No data to test")
        return

    # Test CAN SLIM
    print("\n1. Testing CAN SLIM Strategy...")
    can_slim = CANSLIMStrategy()
    signals = can_slim.generate_signals(data)
    print(f"   Generated {len(signals)} signal(s)")
    for signal in signals:
        print(f"   - {signal.signal_type.value} {signal.symbol} @ {signal.price:.2f}")

    # Test SEPA/VCP
    print("\n2. Testing SEPA/VCP Strategy...")
    sepa = SEPAStrategy()
    signals = sepa.generate_signals(data)
    print(f"   Generated {len(signals)} signal(s)")
    for signal in signals:
        print(f"   - {signal.signal_type.value} {signal.symbol} @ {signal.price:.2f}")

def test_paper_trader():
    """Test paper trading"""
    print("\n" + "=" * 50)
    print("Testing Paper Trader")
    print("=" * 50)

    trader = PaperTrader(initial_capital=100.0)
    print(f"\n   Initial capital: ${trader.portfolio.total_value:.2f}")

    # Test buy
    print("\n1. Placing BUY order...")
    trader.place_order(
        symbol='AAPL',
        side='BUY',
        quantity=1,
        price=150.0,
        strategy='TEST',
        stop_loss=140.0,
        take_profit=165.0
    )
    print(f"   Portfolio value: ${trader.portfolio.total_value:.2f}")

    # Update price
    print("\n2. Updating price to $160...")
    trader.update_prices({'AAPL': 160.0})
    print(f"   Portfolio value: ${trader.portfolio.total_value:.2f}")

    # Test sell
    print("\n3. Placing SELL order...")
    trader.place_order(
        symbol='AAPL',
        side='SELL',
        quantity=1,
        price=160.0,
        strategy='TEST'
    )
    print(f"   Final value: ${trader.portfolio.total_value:.2f}")

    # Performance
    print("\n4. Performance Metrics:")
    metrics = trader.get_performance_metrics()
    for key, value in metrics.items():
        print(f"   - {key}: {value}")

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("PAPER TRADER SYSTEM TEST")
    print("=" * 50)

    # Run tests
    us_data, india_data = test_data_fetch()
    test_strategies(us_data)
    test_paper_trader()

    print("\n" + "=" * 50)
    print("TEST COMPLETE")
    print("=" * 50)
