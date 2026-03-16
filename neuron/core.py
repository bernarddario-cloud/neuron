"""
NEURON Core — OpenClaw's Autonomous Trading System.
Orchestrates all modules and bridges to SYNAPSE for combined signal power.
"""

import json
import time
import os
import logging
import threading
from pathlib import Path

from neuron.data import MarketDataEngine
from neuron.ai import AIEngine
from neuron.strategy import StrategyEngine
from neuron.risk import RiskManager
from neuron.executor import AlpacaExecutor
from neuron.portfolio import PortfolioTracker
from neuron.alerts import AlertManager

logger = logging.getLogger("neuron")

DEFAULT_WATCHLIST = ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOG", "META",
                     "AMD", "PLTR", "COIN", "SOFI", "SPY", "QQQ"]


class NeuronCore:
    """
    NEURON — OpenClaw's trading system. Works in tandem with SYNAPSE.

    Usage:
        core = NeuronCore.from_env()
        core.scan_and_trade(watchlist)
        core.consensus("NVDA")
        print(core.portfolio_report())
    """

    def __init__(self, config: dict):
        self.config = config
        self.watchlist = config.get("watchlist", DEFAULT_WATCHLIST)

        # Initialize all subsystems
        self.data = MarketDataEngine({
            "polygon": config.get("polygon_key"),
            "finnhub": config.get("finnhub_key"),
            "twelvedata": config.get("twelvedata_key"),
            "alpha_vantage": config.get("alpha_vantage_key"),
            "coinmarketcap": config.get("coinmarketcap_key"),
            "newsapi": config.get("newsapi_key"),
        })

        self.ai = AIEngine({
            "anthropic": config.get("anthropic_key"),
            "xai": config.get("xai_key"),
            "openai": config.get("openai_key"),
            "groq": config.get("groq_key"),
        })

        self.strategy = StrategyEngine()
        self.risk = RiskManager(
            max_position_pct=config.get("max_position_pct", 5),
            max_portfolio_risk=config.get("max_portfolio_risk", 20),
            default_stop_pct=config.get("stop_loss_pct", 3),
            default_target_pct=config.get("take_profit_pct", 8),
        )

        self.executor = AlpacaExecutor(
            config.get("alpaca_key", ""),
            config.get("alpaca_secret", ""),
            config.get("alpaca_base_url", "https://api.alpaca.markets"),
        )

        self.portfolio = PortfolioTracker(self.executor.portfolio_value())

        self.alerts = AlertManager(
            config.get("bot_token", ""),
            config.get("chat_id", ""),
        )

        logger.info(f"NEURON initialized — watchlist: {len(self.watchlist)} symbols")

    @classmethod
    def from_env(cls) -> "NeuronCore":
        """Load config from environment variables (compatible with synapse_env.conf)."""
        def e(key, default=""): return os.environ.get(key, default)
        return cls({
            "polygon_key": e("POLYGON_API_KEY"),
            "finnhub_key": e("FINNHUB_API_KEY"),
            "twelvedata_key": e("TWELVEDATA_API_KEY"),
            "alpha_vantage_key": e("ALPHA_VANTAGE_API_KEY"),
            "coinmarketcap_key": e("COINMARKETCAP_API_KEY"),
            "newsapi_key": e("NEWSAPI_KEY"),
            "anthropic_key": e("ANTHROPIC_API_KEY"),
            "xai_key": e("XAI_API_KEY"),
            "openai_key": e("OPENAI_API_KEY"),
            "groq_key": e("GROQ_API_KEY"),
            "alpaca_key": e("ALPACA_API_KEY"),
            "alpaca_secret": e("ALPACA_SECRET_KEY"),
            "alpaca_base_url": e("ALPACA_BASE_URL", "https://api.alpaca.markets"),
            "bot_token": e("ANTIGRAVITY_BOT_TOKEN"),
            "chat_id": e("TELEGRAM_OWNER_CHAT_ID"),
        })

    # ── Scanning ──
    def scan(self, symbols: list = None, dry_run: bool = True) -> list:
        """Scan symbols for trading opportunities."""
        symbols = symbols or self.watchlist
        results = []

        for symbol in symbols:
            quote = self.data.get_quote(symbol)
            if not quote:
                continue

            # Run strategies
            news = self.data.sentiment(symbol)
            signals = self.strategy.scan(quote, news)
            combined = self.strategy.combined_signal(signals)

            if combined.is_actionable:
                results.append({
                    "symbol": symbol, "action": combined.action,
                    "strength": combined.strength, "reasoning": combined.reasoning,
                    "price": quote.price, "signals": len(signals)
                })

                if not dry_run:
                    self._execute_signal(symbol, combined, quote.price)

        logger.info(f"Scan complete: {len(results)} actionable out of {len(symbols)}")
        return results

    def _execute_signal(self, symbol: str, signal, price: float):
        """Risk-check and execute a signal."""
        portfolio_val = self.executor.portfolio_value()
        assessment = self.risk.assess(
            symbol, price, portfolio_val,
            conviction=signal.strength,
            stop_loss=signal.stop_loss if hasattr(signal, 'stop_loss') else 0,
            target_price=signal.target_price if hasattr(signal, 'target_price') else 0)

        if not assessment.approved:
            logger.info(f"Risk rejected {symbol}: {assessment.reason}")
            return

        side = "buy" if signal.action == "BUY" else "sell"
        order = self.executor.place_bracket_order(
            symbol, assessment.shares, side,
            assessment.take_profit, assessment.stop_loss)

        if order.status != "rejected":
            self.portfolio.add_position(symbol, side, assessment.shares, price, signal.strategy)
            self.risk.register_position(symbol, assessment.position_size_pct)
            self.alerts.trade_alert(symbol, side, assessment.shares, price, order.order_id)

    # ── AI Consensus ──
    def consensus(self, symbol: str) -> dict:
        """Get multi-model AI consensus on a symbol."""
        quote = self.data.get_quote(symbol)
        market_data = f"Price: ${quote.price:.2f}, Change: {quote.change_pct:+.1f}%" if quote else "No data"

        result = self.ai.analyze(symbol, market_data)
        self.alerts.consensus_alert(symbol, result.action, result.conviction,
                                     result.votes, result.agreement_pct)
        return {
            "symbol": symbol, "action": result.action,
            "conviction": result.conviction,
            "agreement": result.agreement_pct,
            "votes": result.votes,
            "strong": result.is_strong
        }

    # ── Portfolio ──
    def portfolio_report(self) -> str:
        """Full portfolio + Alpaca account report."""
        acct = self.executor.account()
        positions = self.executor.positions()

        lines = ["NEURON PORTFOLIO", "=" * 35]
        lines.append(f"Value: ${float(acct.get('portfolio_value', 0)):,.2f}")
        lines.append(f"Buying Power: ${float(acct.get('buying_power', 0)):,.2f}")
        lines.append(f"Day P&L: ${float(acct.get('equity', 0)) - float(acct.get('last_equity', 0)):+,.2f}")

        if positions:
            lines.append(f"\nPositions ({len(positions)}):")
            for p in positions:
                pnl = float(p.get("unrealized_pl", 0))
                lines.append(f"  {p['symbol']}: {p['qty']} @ ${float(p.get('avg_entry_price', 0)):.2f} P&L: ${pnl:+,.2f}")

        return "\n".join(lines)

    # ── SYNAPSE Bridge ──
    def synapse_signal(self, synapse_data: dict) -> dict:
        """Accept a signal from SYNAPSE and combine with NEURON's own analysis."""
        symbol = synapse_data.get("symbol", "")
        synapse_action = synapse_data.get("action", "HOLD")
        synapse_conviction = synapse_data.get("conviction", 50)

        # NEURON does its own analysis
        quote = self.data.get_quote(symbol)
        if not quote:
            return {"combined_action": synapse_action, "source": "synapse_only"}

        news = self.data.sentiment(symbol)
        our_signals = self.strategy.scan(quote, news)
        our_combined = self.strategy.combined_signal(our_signals)

        # Combine: if both agree, boost conviction
        neuron_action = our_combined.action
        if synapse_action == neuron_action:
            combined_conviction = (synapse_conviction + our_combined.strength) / 2 * 1.2
            return {
                "combined_action": synapse_action,
                "conviction": min(95, combined_conviction),
                "agreement": "SYNAPSE + NEURON agree",
                "source": "combined"
            }
        else:
            return {
                "combined_action": "HOLD",
                "conviction": 30,
                "agreement": f"Disagree: SYNAPSE={synapse_action}, NEURON={neuron_action}",
                "source": "conflict"
            }

    def status(self) -> dict:
        return {
            "version": "1.0.0",
            "watchlist": len(self.watchlist),
            "risk": self.risk.status(),
            "portfolio": self.portfolio.to_dict(),
        }
