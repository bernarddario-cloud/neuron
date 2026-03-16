"""
NEURON Portfolio — Tracking, P&L, and Performance Metrics
Tracks all positions, calculates returns, and generates performance reports.
"""

import json
import time
import logging
from typing import Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger("neuron.portfolio")


@dataclass
class PositionRecord:
    symbol: str
    side: str
    qty: int
    entry_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: float = 0.0
    strategy: str = ""

    @property
    def return_pct(self) -> float:
        if self.entry_price <= 0: return 0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100


@dataclass
class TradeRecord:
    symbol: str
    side: str
    qty: int
    entry_price: float
    exit_price: float
    pnl: float
    strategy: str = ""
    opened_at: float = 0.0
    closed_at: float = 0.0

    @property
    def return_pct(self) -> float:
        if self.entry_price <= 0: return 0
        return ((self.exit_price - self.entry_price) / self.entry_price) * 100


class PortfolioTracker:
    """Tracks portfolio performance and trade history."""

    def __init__(self, initial_capital: float = 0):
        self.initial_capital = initial_capital
        self.positions: Dict[str, PositionRecord] = {}
        self.trade_history: List[TradeRecord] = []
        self.peak_value: float = initial_capital

    def add_position(self, symbol: str, side: str, qty: int,
                     price: float, strategy: str = ""):
        self.positions[symbol] = PositionRecord(
            symbol=symbol, side=side, qty=qty, entry_price=price,
            current_price=price, opened_at=time.time(), strategy=strategy)
        logger.info(f"Position opened: {side} {qty} {symbol} @ ${price:.2f}")

    def close_position(self, symbol: str, exit_price: float) -> float:
        pos = self.positions.pop(symbol, None)
        if not pos: return 0
        pnl = (exit_price - pos.entry_price) * pos.qty
        if pos.side == "sell": pnl = -pnl  # Short
        trade = TradeRecord(
            symbol=symbol, side=pos.side, qty=pos.qty,
            entry_price=pos.entry_price, exit_price=exit_price,
            pnl=pnl, strategy=pos.strategy,
            opened_at=pos.opened_at, closed_at=time.time())
        self.trade_history.append(trade)
        logger.info(f"Position closed: {symbol} P&L: ${pnl:+,.2f}")
        return pnl

    def update_prices(self, prices: Dict[str, float]):
        for symbol, price in prices.items():
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos.current_price = price
                pos.unrealized_pnl = (price - pos.entry_price) * pos.qty

    @property
    def total_unrealized(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values())

    @property
    def total_realized(self) -> float:
        return sum(t.pnl for t in self.trade_history)

    @property
    def win_rate(self) -> float:
        if not self.trade_history: return 0
        wins = sum(1 for t in self.trade_history if t.pnl > 0)
        return wins / len(self.trade_history) * 100

    @property
    def avg_win(self) -> float:
        wins = [t.pnl for t in self.trade_history if t.pnl > 0]
        return sum(wins) / len(wins) if wins else 0

    @property
    def avg_loss(self) -> float:
        losses = [t.pnl for t in self.trade_history if t.pnl < 0]
        return sum(losses) / len(losses) if losses else 0

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trade_history if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trade_history if t.pnl < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float('inf')

    def performance_report(self) -> str:
        lines = ["NEURON PERFORMANCE REPORT", "=" * 40]
        lines.append(f"Realized P&L: ${self.total_realized:+,.2f}")
        lines.append(f"Unrealized P&L: ${self.total_unrealized:+,.2f}")
        lines.append(f"Total Trades: {len(self.trade_history)}")
        lines.append(f"Win Rate: {self.win_rate:.1f}%")
        lines.append(f"Avg Win: ${self.avg_win:+,.2f}")
        lines.append(f"Avg Loss: ${self.avg_loss:+,.2f}")
        lines.append(f"Profit Factor: {self.profit_factor:.2f}")
        lines.append(f"Open Positions: {len(self.positions)}")

        if self.positions:
            lines.append(f"\nOPEN POSITIONS:")
            for sym, pos in self.positions.items():
                lines.append(f"  {sym}: {pos.qty} @ ${pos.entry_price:.2f} → ${pos.current_price:.2f} ({pos.return_pct:+.1f}%)")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "realized_pnl": self.total_realized,
            "unrealized_pnl": self.total_unrealized,
            "total_trades": len(self.trade_history),
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "open_positions": len(self.positions)
        }
