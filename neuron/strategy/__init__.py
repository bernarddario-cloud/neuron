"""
NEURON Strategy — Multi-Strategy Signal Generation
Momentum, Sentiment, Breakout strategies + SYNAPSE signal fusion.
"""

import logging
from typing import List, Optional
from dataclasses import dataclass
from neuron.data import Quote, NewsItem

logger = logging.getLogger("neuron.strategy")


@dataclass
class Signal:
    symbol: str
    strategy: str
    action: str  # BUY, SELL, HOLD
    strength: float  # 0-100
    reasoning: str
    entry_price: float = 0.0
    target_price: float = 0.0
    stop_loss: float = 0.0

    @property
    def is_actionable(self) -> bool:
        return self.action in ("BUY", "SELL") and self.strength >= 60


class MomentumStrategy:
    """Price momentum — trend following based on price action."""
    NAME = "momentum"

    def analyze(self, quote: Quote, history: List[Quote] = None) -> Signal:
        if not quote or quote.price <= 0:
            return Signal(quote.symbol if quote else "?", self.NAME, "HOLD", 0, "No data")

        # Intra-day momentum
        change = ((quote.close - quote.open) / quote.open * 100) if quote.open > 0 else 0
        range_pct = ((quote.high - quote.low) / quote.low * 100) if quote.low > 0 else 0

        if change > 2 and range_pct < 8:
            return Signal(quote.symbol, self.NAME, "BUY", min(80, 50 + change * 10),
                          f"Strong upward momentum: +{change:.1f}%",
                          entry_price=quote.close,
                          target_price=quote.close * 1.05,
                          stop_loss=quote.close * 0.97)
        elif change < -2 and range_pct < 8:
            return Signal(quote.symbol, self.NAME, "SELL", min(80, 50 + abs(change) * 10),
                          f"Downward momentum: {change:.1f}%",
                          entry_price=quote.close,
                          target_price=quote.close * 0.95,
                          stop_loss=quote.close * 1.03)
        return Signal(quote.symbol, self.NAME, "HOLD", 30,
                      f"Flat momentum: {change:+.1f}%, range: {range_pct:.1f}%")


class SentimentStrategy:
    """News sentiment — trades based on sentiment scores from AI + news."""
    NAME = "sentiment"

    def analyze(self, symbol: str, news: List[NewsItem]) -> Signal:
        if not news:
            return Signal(symbol, self.NAME, "HOLD", 0, "No news data")

        scores = [n.sentiment for n in news if n.sentiment != 0]
        if not scores:
            return Signal(symbol, self.NAME, "HOLD", 20, "No sentiment scores")

        avg = sum(scores) / len(scores)
        bullish = sum(1 for s in scores if s > 0.1)
        bearish = sum(1 for s in scores if s < -0.1)

        if avg > 0.2 and bullish > bearish:
            strength = min(85, 50 + avg * 100)
            return Signal(symbol, self.NAME, "BUY", strength,
                          f"Bullish sentiment: {avg:.2f} ({bullish}/{len(scores)} positive)")
        elif avg < -0.2 and bearish > bullish:
            strength = min(85, 50 + abs(avg) * 100)
            return Signal(symbol, self.NAME, "SELL", strength,
                          f"Bearish sentiment: {avg:.2f} ({bearish}/{len(scores)} negative)")
        return Signal(symbol, self.NAME, "HOLD", 30,
                      f"Neutral sentiment: {avg:.2f}")


class BreakoutStrategy:
    """Volume/price breakout detection."""
    NAME = "breakout"

    def analyze(self, quote: Quote, avg_volume: int = 0) -> Signal:
        if not quote or quote.price <= 0:
            return Signal(quote.symbol if quote else "?", self.NAME, "HOLD", 0, "No data")

        range_pct = ((quote.high - quote.low) / quote.low * 100) if quote.low > 0 else 0
        close_at_high = (quote.close - quote.low) / (quote.high - quote.low) if quote.high != quote.low else 0.5
        vol_ratio = quote.volume / avg_volume if avg_volume > 0 else 1.0

        # Breakout: wide range + closing near high + above-avg volume
        if range_pct > 3 and close_at_high > 0.7 and vol_ratio > 1.5:
            return Signal(quote.symbol, self.NAME, "BUY", min(85, 50 + range_pct * 5),
                          f"Bullish breakout: {range_pct:.1f}% range, closing at {close_at_high:.0%}, vol {vol_ratio:.1f}x",
                          entry_price=quote.close,
                          target_price=quote.close * 1.06,
                          stop_loss=quote.low)
        elif range_pct > 3 and close_at_high < 0.3 and vol_ratio > 1.5:
            return Signal(quote.symbol, self.NAME, "SELL", min(85, 50 + range_pct * 5),
                          f"Bearish breakdown: {range_pct:.1f}% range, closing at {close_at_high:.0%}",
                          entry_price=quote.close,
                          target_price=quote.close * 0.94,
                          stop_loss=quote.high)
        return Signal(quote.symbol, self.NAME, "HOLD", 20, "No breakout pattern")


class StrategyEngine:
    """Runs multiple strategies and combines signals."""

    def __init__(self):
        self.momentum = MomentumStrategy()
        self.sentiment_strat = SentimentStrategy()
        self.breakout = BreakoutStrategy()

    def scan(self, quote: Quote, news: List[NewsItem] = None,
             avg_volume: int = 0) -> List[Signal]:
        """Run all strategies on a symbol."""
        signals = []
        signals.append(self.momentum.analyze(quote))
        if news:
            signals.append(self.sentiment_strat.analyze(quote.symbol, news))
        signals.append(self.breakout.analyze(quote, avg_volume))
        return signals

    def combined_signal(self, signals: List[Signal]) -> Signal:
        """Combine multiple strategy signals into one."""
        if not signals:
            return Signal("?", "combined", "HOLD", 0, "No signals")

        actions = [s.action for s in signals if s.strength > 30]
        if not actions:
            return Signal(signals[0].symbol, "combined", "HOLD", 20, "All signals weak")

        buy_count = actions.count("BUY")
        sell_count = actions.count("SELL")
        total = len(actions)

        buy_strength = sum(s.strength for s in signals if s.action == "BUY")
        sell_strength = sum(s.strength for s in signals if s.action == "SELL")

        if buy_count > sell_count and buy_strength > sell_strength:
            avg = buy_strength / max(1, buy_count)
            agreement = buy_count / total * 100
            return Signal(signals[0].symbol, "combined", "BUY", avg * (agreement / 100),
                          f"{buy_count}/{total} strategies agree BUY (avg strength {avg:.0f})")
        elif sell_count > buy_count and sell_strength > buy_strength:
            avg = sell_strength / max(1, sell_count)
            agreement = sell_count / total * 100
            return Signal(signals[0].symbol, "combined", "SELL", avg * (agreement / 100),
                          f"{sell_count}/{total} strategies agree SELL (avg strength {avg:.0f})")
        return Signal(signals[0].symbol, "combined", "HOLD", 30, "Mixed signals — no consensus")
