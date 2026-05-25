"""Investing.com — real-time cotton price via embed/undocumented endpoints.

Investing.com uses Cloudflare bot protection on most pages; direct HTML scraping
will almost always return 403/503. We attempt two lightweight JSON endpoints that
sometimes bypass CF. Failure is expected and handled gracefully.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

# These lightweight endpoints occasionally bypass Cloudflare
_ENDPOINTS = [
    "https://api.investing.com/api/financialdata/1652085/historical/chart/?period=P1W&interval=PT5M&pointscount=60",
    "https://tvc4.investing.com/94b0c3224c05e8d2b8c2f9f8929e9a46/1700000000/1/1/8/history?symbol=8985&resolution=5&from=1700000000&to=1800000000",
]
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.investing.com/",
    "X-Requested-With": "XMLHttpRequest",
}


class InvestingCottonFetcher(BaseFetcher):
    """Investing.com cotton price — real-time when Cloudflare allows."""

    def __init__(self) -> None:
        super().__init__(
            name="Investing.com",
            priority=4,
            cache_ttl=300,
            timeout=15,
            enabled=True,
        )

    async def fetch(self) -> FetchResult:
        start = datetime.utcnow()
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
                for url in _ENDPOINTS:
                    result = await self._try_endpoint(session, url, start)
                    if result.success:
                        return result

        except Exception as exc:
            self.logger.debug("Investing.com неожиданная ошибка: %s", exc)

        self.record_failure()
        return FetchResult(success=False, error="Investing.com: Cloudflare заблокировал доступ")

    async def _try_endpoint(
        self,
        session: aiohttp.ClientSession,
        url: str,
        start: datetime,
    ) -> FetchResult:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as resp:
                if resp.status in (403, 503):
                    self.logger.debug("Investing.com Cloudflare %d: %s", resp.status, url)
                    return FetchResult(success=False, error=f"Cloudflare {resp.status}")
                if resp.status != 200:
                    return FetchResult(success=False, error=f"HTTP {resp.status}")

                raw = await resp.json(content_type=None)
                price = self._parse_price(raw)

                if price is None or not (20.0 < price < 500.0):
                    return FetchResult(success=False, error="Цена не найдена или вне диапазона")

                data = PriceData(
                    price=price,
                    source=self.name,
                    timestamp=datetime.utcnow(),
                    unit="c/lb",
                )
                data.confidence = self.calculate_confidence(data)

                ms = (datetime.utcnow() - start).total_seconds() * 1000
                self.record_success()
                self.logger.info("Investing.com: %.2f c/lb (%.0fms)", price, ms)
                return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except aiohttp.ClientError as exc:
            self.logger.debug("Investing.com connection error: %s", exc)
            return FetchResult(success=False, error=str(exc))

    @staticmethod
    def _parse_price(raw: dict) -> Optional[float]:
        """Extract last close/price from various Investing.com JSON shapes."""
        # TradingView-style: {"c": [...], "t": [...]}
        closes = raw.get("c") or []
        if closes:
            try:
                return float(closes[-1])
            except (TypeError, ValueError, IndexError):
                pass

        # Financial data shape: {"data": {"last_close": ...}}
        try:
            return float(raw["data"]["last_close"])
        except (KeyError, TypeError, ValueError):
            pass

        # Flat: {"last": ...} or {"price": ...}
        for key in ("last", "price", "close", "lastClose"):
            if key in raw:
                try:
                    return float(raw[key])
                except (TypeError, ValueError):
                    pass

        return None
