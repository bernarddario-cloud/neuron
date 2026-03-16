"""
NEURON Alerts — Telegram Notifications + Signal Alerts
"""

import json, urllib.request, urllib.parse, time, logging

logger = logging.getLogger("neuron.alerts")


class AlertManager:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, message: str):
        if not self.bot_token or not self.chat_id: return
        for chunk in [message[i:i+4000] for i in range(0, len(message), 4000)]:
            try:
                data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": chunk}).encode()
                req = urllib.request.Request(f"https://api.telegram.org/bot{self.bot_token}/sendMessage", data=data, method="POST")
                urllib.request.urlopen(req, timeout=10)
            except Exception as e:
                logger.error(f"Telegram: {e}")

    def signal_alert(self, symbol, action, conviction, reasoning, source="NEURON"):
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(action, "⚪")
        self.send(f"{emoji} {source} SIGNAL — {symbol}\nAction: {action}\nConviction: {conviction:.0f}%\n{reasoning}")

    def trade_alert(self, symbol, side, qty, price, order_id=""):
        emoji = "🟢" if side == "buy" else "🔴"
        self.send(f"{emoji} TRADE: {side.upper()} {qty} {symbol} @ ${price:.2f}\nOrder: {order_id}")

    def consensus_alert(self, symbol, action, conviction, votes, agreement):
        emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(action, "⚪")
        vote_lines = "\n".join([f"  {m}: {v}" for m, v in votes.items()])
        self.send(f"{emoji} AI CONSENSUS — {symbol}\nVerdict: {action} ({conviction:.0f}%)\nAgreement: {agreement:.0f}%\n\nVotes:\n{vote_lines}")

    def daily_report(self, portfolio_report, signals=""):
        self.send(f"📊 NEURON DAILY — {time.strftime('%Y-%m-%d')}\n\n{portfolio_report}\n\n{signals}")

    def error_alert(self, error, context=""):
        self.send(f"⚠️ NEURON ERROR\n{context}\n{error}")
