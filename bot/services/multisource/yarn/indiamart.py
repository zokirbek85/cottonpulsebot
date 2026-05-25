"""IndiaMART — cotton yarn prices from Indian B2B marketplace."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

# IndiaMART cotton yarn search — price typically in INR/kg; we look for USD quotes
_URLS = [
    "https://dir.indiamart.com/search.mp?ss=cotton+yarn+30s&priceMin=1&priceMax=500&cq=USD",
    "https://dir.indiamart.com/search.mp?ss=30s+carded+cotton+yarn",
]
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Patterns: "USD 2.50 per kg", "$2.50/kg", "2.50 USD/kg"
_USD_PATTERNS = [
    r"USD\s+(\d+\.?\d*)\s+per\s+kg",
    r"\$\s*(\d+\.?\d*)\s*/\s*(?:Kg|kg|KG)",
    r"(\d+\.?\d*)\s+USD\s*/\s*(?:Kg|kg|KG)",
    r"(\d+\.?\d*)\s+USD\s+per\s+kg",
]


class IndiaMARTYarnFetcher(BaseFetcher):
    """IndiaMART B2B marketplace yarn price (USD quotes only)."""

    def __init__(self) -> None:
        super().__init__(
            name="IndiaMART",
            priority=4,
            cache_ttl=7200,
            timeout=20,
            enabled=True,
        )

    async def fetch(self) -> FetchResult:
        start = datetime.utcnow()
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
                for url in _URLS:
                    price = await self._try_url(session, url)
                    if price is not None:
                        data = PriceData(
                            price=price,
                            source=self.name,
                            timestamp=datetime.utcnow(),
                            unit="USD/kg",
                            is_estimated=True,
                            metadata={"market": "India", "type": "B2B listing"},
                        )
                        data.confidence = self.calculate_confidence(data) * 0.7

                        ms = (datetime.utcnow() - start).total_seconds() * 1000
                        self.record_success()
                        self.logger.info("IndiaMART: %.2f USD/kg (%.0fms)", price, ms)
                        return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except Exception as exc:
            self.logger.debug("IndiaMART неожиданная ошибка: %s", exc)

        self.record_failure()
        return FetchResult(success=False, error="IndiaMART: цена в USD не найдена")

    async def _try_url(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[float]:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text(errors="replace")
                text = re.sub(r"<[^>]+>", " ", html)

                prices: list[float] = []
                for pat in _USD_PATTERNS:
                    for m in re.finditer(pat, text, re.IGNORECASE):
                        try:
                            val = float(m.group(1))
                            if 1.0 < val < 20.0:
                                prices.append(val)
                        except (ValueError, IndexError):
                            pass

                if not prices:
                    return None
                prices.sort()
                # Return median to avoid outliers
                return prices[len(prices) // 2]

        except Exception as exc:
            self.logger.debug("IndiaMART error (%s): %s", url, exc)
        return None
