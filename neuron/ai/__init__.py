"""
NEURON AI — Multi-Model Consensus Engine
Asks Claude + Grok + OpenAI in parallel for trading signals, combines into one verdict.
Designed to complement SYNAPSE's single-model analysis with consensus voting.
"""

import json
import time
import urllib.request
import threading
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass

logger = logging.getLogger("neuron.ai")


@dataclass
class AISignal:
    model: str
    action: str  # BUY, SELL, HOLD
    conviction: float  # 0-100
    reasoning: str
    target_price: float = 0.0
    stop_loss: float = 0.0
    timeframe: str = ""
    raw_response: str = ""


@dataclass
class ConsensusSignal:
    symbol: str
    action: str  # BUY, SELL, HOLD
    conviction: float
    votes: Dict[str, str]  # model -> action
    signals: List[AISignal]
    agreement_pct: float = 0.0
    timestamp: float = 0.0

    @property
    def is_strong(self) -> bool:
        return self.conviction >= 70 and self.agreement_pct >= 66


class AIEngine:
    """Multi-model AI engine for trading analysis."""

    TRADE_PROMPT = """Analyze {symbol} for trading. Current data: {market_data}

You MUST respond in this exact JSON format:
{{"action": "BUY|SELL|HOLD", "conviction": 0-100, "reasoning": "brief explanation",
  "target_price": 0.0, "stop_loss": 0.0, "timeframe": "1d|1w|1m"}}

Only recommend assets tradeable on Alpaca (US stocks + major crypto pairs).
Be decisive. No hedging."""

    def __init__(self, keys: dict):
        self.keys = keys  # {"anthropic": "...", "xai": "...", "openai": "..."}

    def _call_claude(self, prompt: str, max_tokens: int = 800) -> str:
        key = self.keys.get("anthropic")
        if not key: return ""
        try:
            data = json.dumps({
                "model": "claude-sonnet-4-20250514", "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]
            }).encode()
            req = urllib.request.Request("https://api.anthropic.com/v1/messages",
                data=data, method="POST",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=60)
            result = json.loads(resp.read())
            return result["content"][0]["text"]
        except Exception as e:
            logger.error(f"Claude error: {e}")
            return ""

    def _call_grok(self, prompt: str, max_tokens: int = 800) -> str:
        key = self.keys.get("xai")
        if not key: return ""
        try:
            data = json.dumps({
                "model": "grok-3-mini", "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            }).encode()
            req = urllib.request.Request("https://api.x.ai/v1/chat/completions",
                data=data, method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=60)
            return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Grok error: {e}")
            return ""

    def _call_openai(self, prompt: str, max_tokens: int = 800) -> str:
        key = self.keys.get("openai")
        if not key: return ""
        try:
            data = json.dumps({
                "model": "gpt-4o-mini", "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            }).encode()
            req = urllib.request.Request("https://api.openai.com/v1/chat/completions",
                data=data, method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=60)
            return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenAI error: {e}")
            return ""

    def _parse_signal(self, model: str, response: str) -> AISignal:
        """Parse JSON signal from AI response."""
        try:
            # Find JSON in response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                obj = json.loads(response[start:end])
                return AISignal(
                    model=model,
                    action=obj.get("action", "HOLD").upper(),
                    conviction=float(obj.get("conviction", 50)),
                    reasoning=obj.get("reasoning", ""),
                    target_price=float(obj.get("target_price", 0)),
                    stop_loss=float(obj.get("stop_loss", 0)),
                    timeframe=obj.get("timeframe", "1d"),
                    raw_response=response[:500]
                )
        except: pass
        # Fallback: parse action from text
        action = "HOLD"
        text_upper = response.upper()
        if "BUY" in text_upper and "SELL" not in text_upper: action = "BUY"
        elif "SELL" in text_upper and "BUY" not in text_upper: action = "SELL"
        return AISignal(model=model, action=action, conviction=50,
                        reasoning=response[:200], raw_response=response[:500])

    def analyze(self, symbol: str, market_data: str) -> ConsensusSignal:
        """Multi-model consensus analysis. All 3 AIs vote in parallel."""
        prompt = self.TRADE_PROMPT.format(symbol=symbol, market_data=market_data)
        results = {}
        threads = []

        def ask(name, call_fn):
            results[name] = call_fn(prompt)

        for name, fn in [("Claude", self._call_claude), ("Grok", self._call_grok),
                         ("OpenAI", self._call_openai)]:
            t = threading.Thread(target=ask, args=(name, fn))
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=90)

        # Parse signals
        signals = []
        for model, response in results.items():
            if response:
                signals.append(self._parse_signal(model, response))

        if not signals:
            return ConsensusSignal(symbol=symbol, action="HOLD", conviction=0,
                                   votes={}, signals=[], timestamp=time.time())

        # Determine consensus
        votes = {s.model: s.action for s in signals}
        action_counts = {}
        for s in signals:
            action_counts[s.action] = action_counts.get(s.action, 0) + 1

        consensus_action = max(action_counts, key=action_counts.get)
        agreement = action_counts[consensus_action] / len(signals) * 100
        avg_conviction = sum(s.conviction for s in signals) / len(signals)

        return ConsensusSignal(
            symbol=symbol, action=consensus_action,
            conviction=avg_conviction * (agreement / 100),
            votes=votes, signals=signals,
            agreement_pct=agreement, timestamp=time.time()
        )

    def quick_signal(self, symbol: str, market_data: str, model: str = "claude") -> AISignal:
        """Single-model quick analysis."""
        prompt = self.TRADE_PROMPT.format(symbol=symbol, market_data=market_data)
        call_fn = {"claude": self._call_claude, "grok": self._call_grok,
                   "openai": self._call_openai}.get(model, self._call_claude)
        response = call_fn(prompt)
        return self._parse_signal(model, response) if response else AISignal(
            model=model, action="HOLD", conviction=0, reasoning="No response")
