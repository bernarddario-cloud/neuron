# NEURON — OpenClaw's Autonomous Trading System

NEURON is OpenClaw's own version of the SYNAPSE trading architecture. An autonomous, AI-powered trading and portfolio management system.

## Architecture

```
┌──────────────────────────────────────────────────┐
│                 NEURON CORE                      │
│  OpenClaw's Autonomous Trading Intelligence      │
├──────────────┬───────────────┬───────────────────┤
│  MARKET DATA │   AI ENGINE   │  RISK MANAGEMENT  │
│  Multi-feed  │  Multi-model  │  Position sizing  │
│  Real-time   │  Consensus    │  Stop-loss mgmt   │
├──────────────┼───────────────┼───────────────────┤
│   STRATEGY   │   EXECUTOR    │    PORTFOLIO      │
│  Multi-strat │  Alpaca API   │  Tracking + P&L   │
│  Signals     │  Order mgmt   │  Rebalancing      │
├──────────────┴───────────────┴───────────────────┤
│              REPORTING + ALERTS                   │
│  Telegram notifications, logs, audit trail        │
└──────────────────────────────────────────────────┘
```

## Modules

| Module | Description |
|--------|------------|
| `neuron.data` | Market data aggregation (Polygon, Finnhub, Alpha Vantage, TwelveData, CoinMarketCap) |
| `neuron.ai` | Multi-model AI engine (Claude, Grok, OpenAI) with consensus voting |
| `neuron.strategy` | Trading strategies (momentum, mean-reversion, breakout, sentiment) |
| `neuron.risk` | Risk management, position sizing, stop-losses, max drawdown protection |
| `neuron.executor` | Alpaca order execution, order management, fills tracking |
| `neuron.portfolio` | Portfolio tracking, P&L calculation, rebalancing |
| `neuron.alerts` | Telegram notifications, signal alerts, daily reports |

## Quick Start

```bash
pip install -e .

# Run a scan (dry run)
neuron scan --dry-run

# Execute trades
neuron trade

# Check portfolio
neuron portfolio

# Get AI consensus on a ticker
neuron analyze NVDA

# Start autonomous mode
neuron daemon --interval 60
```

## Strategies

- **Momentum** — RSI + MACD trend following
- **Mean Reversion** — Bollinger Band bounces
- **Breakout** — Volume + price breakout detection
- **Sentiment** — News-driven signals via AI analysis
- **Consensus** — Multi-model AI voting (Claude + Grok + GPT)

## Configuration

```yaml
trading:
  account: alpaca
  mode: paper  # paper | live
  max_position_pct: 5
  max_portfolio_risk: 20
  stop_loss_pct: 3
  take_profit_pct: 8

strategies:
  - momentum
  - sentiment
  - consensus

data_sources:
  - polygon
  - finnhub
  - alpha_vantage

ai_models:
  - claude
  - grok
  - openai
```

## License

MIT — Bernard Dario / OpenClaw
