"""
NEURON Data — Multi-Source Market Data Aggregation
Pulls from Polygon, Finnhub, AlphaVantage, TwelveData, CoinMarketCap, NewsAPI.
Compatible with SYNAPSE data pipeline for combined signals.
"""

import json
import time
import urllib.request
import urllib.parse
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("neuron.data")


@dataclass
class Quote:
    symbol: str
    price: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: int = 0
    change_pct: float = 0.0
    source: str = ""
    timestamp: float = 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class NewsItem:
    title: str
    source: str = ""
    sentiment: float = 0.0
    sentiment_label: str = ""
    url: str = ""
    published: str = ""


class MarketDataEngine:
    """Aggregates market data from multiple sources for NEURON + SYNAPSE."""

    def __init__(self, keys: dict):
        self.keys = keys  # {"polygon": "...", "finnhub": "...", etc}
        self._cache: Dict[str, tuple] = {}  # symbol -> (quote, timestamp)
        self.cache_ttl = 60  # seconds

    def _http_get(self, url: str, headers: dict = None, timeout: int = 10) -> dict:
        try:
            req = urllib.request.Request(url, headers=headers or {})
            resp = urllib.request.urlopen(req, timeout=timeout)
            return json.loads(resp.read())
        except Exception as e:
            logger.error(f"HTTP error: {url[:60]} — {e}")
            return {}

    # -- Polygon --
    def polygon_quote(self, symbol: str) -> Optional[Quote]:
        key = self.keys.get("polygon")
        if not key: return None
        data = self._http_get(f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?apiKey={key}")
        results = data.get("results", [{}])
        if not results: return None
        r = results[0]
        return Quote(symbol=symbol, price=r.get("c", 0), open=r.get("o", 0),
                     high=r.get("h", 0), low=r.get("l", 0), close=r.get("c", 0),
                     volume=r.get("v", 0), source="polygon", timestamp=time.time())

    # -- Finnhub --
    def finnhub_quote(self, symbol: str) -> Optional[Quote]:
        key = self.keys.get("finnhub")
        if not key: return None
        d = self._http_get(f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={key}")
        if not d.get("c"): return None
        return Quote(symbol=symbol, price=d["c"], open=d.get("o", 0),
                     high=d.get("h", 0), low=d.get("l", 0), close=d["c"],
                     change_pct=d.get("dp", 0), source="finnhub", timestamp=time.time())

    # -- TwelveData --
    def twelvedata_quote(self, symbol: str) -> Optional[Quote]:
        key = self.keys.get("twelvedata")
        if not key: return None
        d = self._http_get(f"https://api.twelvedata.com/quote?symbol={symbol}&apikey={key}")
        try:
            return Quote(symbol=symbol, price=float(d.get("close", 0)),
                         open=float(d.get("open", 0)), high=float(d.get("high", 0)),
                         low=float(d.get("low", 0)), close=float(d.get("close", 0)),
                         volume=int(d.get("volume", 0)), source="twelvedata", timestamp=time.time())
        except: return None

    # -- AlphaVantage Sentiment --
    def sentiment(self, tickers: str) -> List[NewsItem]:
        key = self.keys.get("alpha_vantage")
        if not key: return []
        data = self._http_get(f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={tickers}&apikey={key}")
        items = []
        for article in data.get("feed", [])[:10]:
            items.append(NewsItem(
                title=article.get("title", ""),
                source=article.get("source", ""),
                sentiment=float(article.get("overall_sentiment_score", 0)),
                sentiment_label=article.get("overall_sentiment_label", ""),
                url=article.get("url", ""),
                published=article.get("time_published", "")
            ))
        return items

    # -- CoinMarketCap --
    def crypto_top(self, limit: int = 10) -> List[Quote]:
        key = self.keys.get("coinmarketcap")
        if not key: return []
        data = self._http_get(
            f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest?limit={limit}&convert=USD",
            headers={"X-CMC_PRO_API_KEY": key})
        quotes = []
        for c in data.get("data", []):
            usd = c.get("quote", {}).get("USD", {})
            quotes.append(Quote(
                symbol=f"{c['symbol']}/USD", price=usd.get("price", 0),
                change_pct=usd.get("percent_change_24h", 0),
                volume=int(usd.get("volume_24h", 0)),
                source="coinmarketcap", timestamp=time.time()))
        return quotes

    # -- NewsAPI --
    def news(self, query: str = "stock market", limit: int = 5) -> List[NewsItem]:
        key = self.keys.get("newsapi")
        if not key: return []
        q = urllib.parse.quote(query)
        data = self._http_get(f"https://newsapi.org/v2/everything?q={q}&sortBy=publishedAt&pageSize={limit}&apiKey={key}")
        return [NewsItem(title=a.get("title", ""), source=a.get("source", {}).get("name", ""),
                         url=a.get("url", ""), published=a.get("publishedAt", ""))
                for a in data.get("articles", [])]

    # -- Multi-source quote (best of all) --
    def get_quote(self, symbol: str) -> Optional[Quote]:
        """Get the best available quote from any source."""
        # Check cache
        cached = self._cache.get(symbol)
        if cached and time.time() - cached[1] < self.cache_ttl:
            return cached[0]

        # Try sources in order of reliability
        for fetch in [self.polygon_quote, self.finnhub_quote, self.twelvedata_quote]:
            quote = fetch(symbol)
            if quote and quote.price > 0:
                self._cache[symbol] = (quote, time.time())
                return quote
        return None

    def multi_quote(self, symbols: List[str]) -> Dict[str, Quote]:
        """Get quotes for multiple symbols."""
        return {s: q for s in symbols if (q := self.get_quote(s))}
