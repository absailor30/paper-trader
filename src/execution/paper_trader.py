"""
Paper trading engine
"""
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from loguru import logger
import json

@dataclass
class Portfolio:
    """Paper trading portfolio"""
    capital: float
    positions: Dict = field(default_factory=dict)
    trade_history: List = field(default_factory=list)
    daily_pnl: float = 0.0

    @property
    def total_value(self) -> float:
        """Calculate total portfolio value"""
        positions_value = sum(
            pos['quantity'] * pos['current_price']
            for pos in self.positions.values()
        )
        return self.capital + positions_value

    @property
    def positions_value(self) -> float:
        """Current value of all positions"""
        return sum(
            pos['quantity'] * pos['current_price']
            for pos in self.positions.values()
        )

class PaperTrader:
    """
    Paper trading simulation engine
    Handles order execution, position management, P&L tracking
    """

    def __init__(self, initial_capital: float = 100.0):
        self.portfolio = Portfolio(capital=initial_capital)
        self.initial_capital = initial_capital
        self.orders = []
        self.daily_start_value = initial_capital

    def place_order(
        self,
        symbol: str,
        side: str,  # 'BUY' or 'SELL'
        quantity: float,
        price: float,
        strategy: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reasoning: str = ""
    ) -> dict:
        """
        Place a paper order

        Returns order result
        """
        order = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price': price,
            'strategy': strategy,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'reasoning': reasoning,
            'timestamp': datetime.now().isoformat(),
            'status': 'FILLED'
        }

        if side == 'BUY':
            # Check capital
            cost = quantity * price
            if cost > self.portfolio.capital:
                logger.warning(f"Insufficient capital for {symbol} buy order")
                order['status'] = 'REJECTED'
                order['reason'] = 'Insufficient capital'
                return order

            # Deduct capital
            self.portfolio.capital -= cost

            # Add position
            if symbol in self.portfolio.positions:
                # Average up/down
                existing = self.portfolio.positions[symbol]
                total_qty = existing['quantity'] + quantity
                avg_price = (
                    (existing['quantity'] * existing['entry_price'] + quantity * price)
                    / total_qty
                )
                self.portfolio.positions[symbol] = {
                    'quantity': total_qty,
                    'entry_price': avg_price,
                    'current_price': price,
                    'entry_time': datetime.now().isoformat(),
                    'strategy': strategy,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit
                }
            else:
                self.portfolio.positions[symbol] = {
                    'quantity': quantity,
                    'entry_price': price,
                    'current_price': price,
                    'entry_time': datetime.now().isoformat(),
                    'strategy': strategy,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit
                }

        elif side == 'SELL':
            # Check position exists
            if symbol not in self.portfolio.positions:
                logger.warning(f"No position in {symbol} to sell")
                order['status'] = 'REJECTED'
                order['reason'] = 'No position'
                return order

            position = self.portfolio.positions[symbol]

            # Calculate P&L
            pnl = (price - position['entry_price']) * quantity
            proceeds = quantity * price

            # Add to capital
            self.portfolio.capital += proceeds
            self.portfolio.daily_pnl += pnl

            # Record trade
            trade = {
                'symbol': symbol,
                'side': 'SELL',
                'quantity': quantity,
                'entry_price': position['entry_price'],
                'exit_price': price,
                'pnl': pnl,
                'pnl_pct': pnl / (position['entry_price'] * quantity) * 100,
                'strategy': strategy,
                'entry_time': position['entry_time'],
                'exit_time': datetime.now().isoformat(),
                'reasoning': reasoning
            }
            self.portfolio.trade_history.append(trade)

            # Remove position if fully sold
            if quantity >= position['quantity']:
                del self.portfolio.positions[symbol]
            else:
                position['quantity'] -= quantity

        self.orders.append(order)
        logger.info(f"{side} {quantity} {symbol} @ {price:.2f} - {order['status']}")

        return order

    def update_prices(self, prices: Dict[str, float]):
        """Update current prices for all positions"""
        for symbol, price in prices.items():
            if symbol in self.portfolio.positions:
                self.portfolio.positions[symbol]['current_price'] = price

    def check_stop_losses(self) -> List[dict]:
        """Check and execute stop losses"""
        triggered = []

        for symbol, position in list(self.portfolio.positions.items()):
            current_price = position['current_price']

            # Stop loss check
            if position.get('stop_loss') and current_price <= position['stop_loss']:
                logger.info(f"Stop loss triggered for {symbol}")
                order = self.place_order(
                    symbol=symbol,
                    side='SELL',
                    quantity=position['quantity'],
                    price=current_price,
                    strategy=position['strategy'],
                    reasoning='Stop loss triggered'
                )
                triggered.append(order)

            # Take profit check
            elif position.get('take_profit') and current_price >= position['take_profit']:
                logger.info(f"Take profit triggered for {symbol}")
                order = self.place_order(
                    symbol=symbol,
                    side='SELL',
                    quantity=position['quantity'],
                    price=current_price,
                    strategy=position['strategy'],
                    reasoning='Take profit triggered'
                )
                triggered.append(order)

        return triggered

    def get_performance_metrics(self) -> dict:
        """Calculate performance metrics"""
        total_return = (self.portfolio.total_value - self.initial_capital) / self.initial_capital * 100
        daily_return = (self.portfolio.total_value - self.daily_start_value) / self.daily_start_value * 100

        # Calculate win rate
        if self.portfolio.trade_history:
            wins = [t for t in self.portfolio.trade_history if t['pnl'] > 0]
            losses = [t for t in self.portfolio.trade_history if t['pnl'] < 0]
            win_rate = len(wins) / len(self.portfolio.trade_history) * 100

            avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
            avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
            profit_factor = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses)) if losses and sum(t['pnl'] for t in losses) != 0 else 0
        else:
            win_rate = 0
            avg_win = 0
            avg_loss = 0
            profit_factor = 0

        return {
            'total_value': self.portfolio.total_value,
            'capital': self.portfolio.capital,
            'positions_value': self.portfolio.positions_value,
            'total_return_pct': total_return,
            'daily_return_pct': daily_return,
            'daily_pnl': self.portfolio.daily_pnl,
            'num_positions': len(self.portfolio.positions),
            'num_trades': len(self.portfolio.trade_history),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor
        }

    def reset_daily_metrics(self):
        """Reset daily tracking"""
        self.daily_start_value = self.portfolio.total_value
        self.portfolio.daily_pnl = 0.0

    def save_state(self, filepath: str):
        """Save portfolio state to file"""
        state = {
            'capital': self.portfolio.capital,
            'positions': self.portfolio.positions,
            'trade_history': self.portfolio.trade_history,
            'orders': self.orders
        }
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"Portfolio state saved to {filepath}")

    def load_state(self, filepath: str):
        """Load portfolio state from file"""
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
            self.portfolio.capital = state['capital']
            self.portfolio.positions = state['positions']
            self.portfolio.trade_history = state['trade_history']
            self.orders = state['orders']
            logger.info(f"Portfolio state loaded from {filepath}")
        except FileNotFoundError:
            logger.warning(f"No state file found at {filepath}")


if __name__ == "__main__":
    # Test paper trader
    trader = PaperTrader(initial_capital=100.0)

    # Test buy
    print("Testing buy order...")
    trader.place_order(
        symbol='AAPL',
        side='BUY',
        quantity=1,
        price=150.0,
        strategy='TEST',
        stop_loss=140.0,
        take_profit=170.0
    )

    print(f"Portfolio value: ${trader.portfolio.total_value:.2f}")
    print(f"Positions: {trader.portfolio.positions}")

    # Update price
    trader.update_prices({'AAPL': 160.0})
    print(f"Updated portfolio value: ${trader.portfolio.total_value:.2f}")

    # Test sell
    print("\nTesting sell order...")
    trader.place_order(
        symbol='AAPL',
        side='SELL',
        quantity=1,
        price=160.0,
        strategy='TEST'
    )

    print(f"Final portfolio value: ${trader.portfolio.total_value:.2f}")
    print(f"Performance: {trader.get_performance_metrics()}")
