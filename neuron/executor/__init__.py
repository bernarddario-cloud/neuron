"""
NEURON Executor — Alpaca Order Execution
Places and manages orders through Alpaca's API. Supports live and paper trading.
"""

import json
import time
import urllib.request
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger("neuron.executor")


@dataclass
class Order:
    symbol: str
    side: str       # buy | sell
    qty: int
    order_type: str = "market"
    time_in_force: str = "day"
    limit_price: float = 0.0
    stop_price: float = 0.0
    status: str = "pending"
    order_id: str = ""
    filled_price: float = 0.0
    filled_at: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class AlpacaExecutor:
    """Executes trades on Alpaca."""

    def __init__(self, api_key: str, secret_key: str,
                 base_url: str = "https://api.alpaca.markets"):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type": "application/json"
        }

    def _request(self, endpoint: str, method: str = "GET", data: dict = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        try:
            if data:
                req = urllib.request.Request(url, data=json.dumps(data).encode(),
                    method=method, headers=self._headers)
            else:
                req = urllib.request.Request(url, headers=self._headers)
                if method != "GET": req.method = method
            resp = urllib.request.urlopen(req, timeout=15)
            return json.loads(resp.read())
        except Exception as e:
            logger.error(f"Alpaca API error: {endpoint} — {e}")
            return {"error": str(e)}

    def account(self) -> dict:
        return self._request("/v2/account")

    def portfolio_value(self) -> float:
        acct = self.account()
        return float(acct.get("portfolio_value", 0))

    def buying_power(self) -> float:
        acct = self.account()
        return float(acct.get("buying_power", 0))

    def positions(self) -> List[dict]:
        result = self._request("/v2/positions")
        return result if isinstance(result, list) else []

    def get_position(self, symbol: str) -> Optional[dict]:
        result = self._request(f"/v2/positions/{symbol}")
        return result if "symbol" in result else None

    def place_order(self, symbol: str, qty: int, side: str,
                    order_type: str = "market", limit_price: float = 0,
                    stop_price: float = 0, time_in_force: str = "day") -> Order:
        """Place an order on Alpaca."""
        order = Order(symbol=symbol, qty=qty, side=side,
                      order_type=order_type, time_in_force=time_in_force,
                      limit_price=limit_price, stop_price=stop_price)

        data = {
            "symbol": symbol, "qty": str(qty), "side": side,
            "type": order_type, "time_in_force": time_in_force
        }
        if order_type == "limit" and limit_price:
            data["limit_price"] = str(limit_price)
        if order_type in ("stop", "stop_limit") and stop_price:
            data["stop_price"] = str(stop_price)

        result = self._request("/v2/orders", method="POST", data=data)
        if "id" in result:
            order.order_id = result["id"]
            order.status = result.get("status", "accepted")
            logger.info(f"Order placed: {side} {qty} {symbol} ({order.status})")
        else:
            order.status = "rejected"
            order.error = result.get("error", result.get("message", "Unknown error"))
            logger.error(f"Order rejected: {side} {qty} {symbol} — {order.error}")

        return order

    def place_bracket_order(self, symbol: str, qty: int, side: str,
                            take_profit: float, stop_loss: float) -> Order:
        """Place an order with automatic take-profit and stop-loss."""
        data = {
            "symbol": symbol, "qty": str(qty), "side": side,
            "type": "market", "time_in_force": "gtc",
            "order_class": "bracket",
            "take_profit": {"limit_price": str(take_profit)},
            "stop_loss": {"stop_price": str(stop_loss)}
        }

        result = self._request("/v2/orders", method="POST", data=data)
        order = Order(symbol=symbol, qty=qty, side=side, order_type="bracket")
        if "id" in result:
            order.order_id = result["id"]
            order.status = result.get("status", "accepted")
            logger.info(f"Bracket order: {side} {qty} {symbol} (TP: ${take_profit}, SL: ${stop_loss})")
        else:
            order.status = "rejected"
            order.error = result.get("error", result.get("message", "Unknown"))
        return order

    def cancel_order(self, order_id: str) -> bool:
        result = self._request(f"/v2/orders/{order_id}", method="DELETE")
        return "error" not in result

    def cancel_all(self) -> int:
        result = self._request("/v2/orders", method="DELETE")
        return len(result) if isinstance(result, list) else 0

    def close_position(self, symbol: str) -> Order:
        result = self._request(f"/v2/positions/{symbol}", method="DELETE")
        order = Order(symbol=symbol, qty=0, side="sell")
        if "order_id" in result:
            order.order_id = result["order_id"]
            order.status = "closing"
        else:
            order.error = result.get("error", "Unknown")
        return order

    def close_all_positions(self) -> List[dict]:
        result = self._request("/v2/positions?cancel_orders=true", method="DELETE")
        return result if isinstance(result, list) else []
