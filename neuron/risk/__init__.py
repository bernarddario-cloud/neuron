"""
NEURON Risk — Position Sizing + Risk Management
Protects capital with max drawdown limits, position sizing, and stop-losses.
"""

import logging
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger("neuron.risk")


@dataclass
class RiskAssessment:
    symbol: str
    approved: bool
    position_size_pct: float  # % of portfolio
    position_size_usd: float
    shares: int
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float
    max_loss_usd: float
    reason: str


class RiskManager:
    """Controls position sizing and risk exposure."""

    def __init__(self, max_position_pct: float = 5.0, max_portfolio_risk: float = 20.0,
                 default_stop_pct: float = 3.0, default_target_pct: float = 8.0,
                 max_correlated_positions: int = 3):
        self.max_position_pct = max_position_pct
        self.max_portfolio_risk = max_portfolio_risk
        self.default_stop_pct = default_stop_pct
        self.default_target_pct = default_target_pct
        self.max_correlated_positions = max_correlated_positions
        self.open_risk: Dict[str, float] = {}  # symbol -> risk %

    def assess(self, symbol: str, price: float, portfolio_value: float,
               conviction: float = 50, stop_loss: float = 0,
               target_price: float = 0) -> RiskAssessment:
        """Evaluate whether a trade should be taken and size it."""

        if portfolio_value <= 0 or price <= 0:
            return RiskAssessment(symbol, False, 0, 0, 0, 0, 0, 0, 0,
                                  "Invalid portfolio or price")

        # Calculate stop and target
        stop = stop_loss or price * (1 - self.default_stop_pct / 100)
        target = target_price or price * (1 + self.default_target_pct / 100)
        risk_per_share = price - stop
        reward_per_share = target - price

        if risk_per_share <= 0:
            return RiskAssessment(symbol, False, 0, 0, 0, stop, target, 0, 0,
                                  "Stop loss above entry price")

        risk_reward = reward_per_share / risk_per_share if risk_per_share > 0 else 0

        # Position sizing based on conviction
        base_pct = self.max_position_pct * (conviction / 100)
        base_pct = max(1.0, min(base_pct, self.max_position_pct))

        # Check total portfolio risk
        current_risk = sum(self.open_risk.values())
        remaining_risk = self.max_portfolio_risk - current_risk
        if remaining_risk <= 0:
            return RiskAssessment(symbol, False, 0, 0, 0, stop, target, risk_reward, 0,
                                  f"Max portfolio risk reached ({current_risk:.1f}%)")

        # Adjust position size to not exceed remaining risk
        position_usd = portfolio_value * (base_pct / 100)
        max_loss = position_usd * (self.default_stop_pct / 100)
        max_loss_allowed = portfolio_value * (remaining_risk / 100)
        if max_loss > max_loss_allowed:
            position_usd = max_loss_allowed / (self.default_stop_pct / 100)
            base_pct = (position_usd / portfolio_value) * 100

        shares = int(position_usd / price)
        if shares <= 0:
            return RiskAssessment(symbol, False, base_pct, position_usd, 0,
                                  stop, target, risk_reward, 0, "Position too small")

        actual_usd = shares * price
        actual_loss = shares * risk_per_share

        # Risk/reward gate
        if risk_reward < 1.5 and conviction < 80:
            return RiskAssessment(symbol, False, base_pct, actual_usd, shares,
                                  stop, target, risk_reward, actual_loss,
                                  f"Risk/reward too low: {risk_reward:.1f} (need 1.5+)")

        return RiskAssessment(
            symbol=symbol, approved=True,
            position_size_pct=round(base_pct, 2),
            position_size_usd=round(actual_usd, 2),
            shares=shares, stop_loss=round(stop, 2),
            take_profit=round(target, 2),
            risk_reward_ratio=round(risk_reward, 2),
            max_loss_usd=round(actual_loss, 2),
            reason=f"Approved: {shares} shares @ ${price:.2f}, R:R {risk_reward:.1f}x"
        )

    def register_position(self, symbol: str, risk_pct: float):
        self.open_risk[symbol] = risk_pct

    def close_position(self, symbol: str):
        self.open_risk.pop(symbol, None)

    def total_risk(self) -> float:
        return sum(self.open_risk.values())

    def status(self) -> dict:
        return {
            "total_risk_pct": round(self.total_risk(), 2),
            "max_risk_pct": self.max_portfolio_risk,
            "open_positions_risk": dict(self.open_risk),
            "risk_remaining_pct": round(self.max_portfolio_risk - self.total_risk(), 2)
        }
