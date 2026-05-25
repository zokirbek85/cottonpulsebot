"""UzRTSB — O'zbekiston Respublikasi tovar-xom ashyo birjasi spot cotton prices.

The exchange publishes daily cotton spot prices on uzrtxb.uz.
The site is SSR-rendered but with limited structure; we try a few known
price-containing pages and parse with regex.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

_URLS = [
    "https://uzrtxb.uz/en/market-data/",
    "https://uzrtxb.uz/en/cotton-price/",
    "https://uzrtxb.uz/en/",
]
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Patterns: match USD/kg price (Uzbek exchange quotes in USD/kg)
_PRICE_PATTERNS = [
    r"(\d+\.\d{2,3})\s*(?:USD|US\$)\s*/\s*kg",
    r"(?:USD|US\$)\s*(\d+\.\d{2,3})\s*/\s*kg",
    r"cotton[^>]*?>\s*(\d+\.\d{2,3})",
]


def _usd_kg_to_cents_lb(usd_per_kg: float) -> float:
    """Convert USD/kg to cents/lb for unified comparison."""
    return usd_per_kg / 2.20462 * 100.0


class UzRTXBCottonFetcher(BaseFetcher):
    """UzRTSB Uzbekistan commodity exchange — spot cotton price in USD/kg."""

    def __init__(self) -> None:
        super().__init__(
            name="UzRTSB (Spot)",
            priority=7,
            cache_ttl=3600,
            timeout=15,
            enabled=True,
        )

    async def fetch(self) -> FetchResult:
        start = datetime.utcnow()
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
                for url in _URLS:
                    price_usd_kg = await self._scrape_page(session, url)
                    if price_usd_kg is not None:
                        # Convert to c/lb for unified unit
                        price_cents_lb = _usd_kg_to_cents_lb(price_usd_kg)

                        if not (20.0 < price_cents_lb < 500.0):
                            continue

                        data = PriceData(
                            price=price_cents_lb,
                            source=self.name,
                            timestamp=datetime.utcnow(),
                            unit="c/lb",
                            metadata={"raw_usd_kg": price_usd_kg, "url": url},
                        )
                        data.confidence = self.calculate_confidence(data)

                        ms = (datetime.utcnow() - start).total_seconds() * 1000
                        self.record_success()
                        self.logger.info(
                            "UzRTSB: %.4f USD/kg → %.2f c/lb (%.0fms)",
                            price_usd_kg,
                            price_cents_lb,
                            ms,
                        )
                        return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except Exception as exc:
            self.logger.debug("UzRTSB неожиданная ошибка: %s", exc)

        self.record_failure()
        return FetchResult(success=False, error="UzRTSB: цена не найдена на сайте")

    async def _scrape_page(
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

                for pat in _PRICE_PATTERNS:
                    for m in re.finditer(pat, text, re.IGNORECASE):
                        val = float(m.group(1))
                        # Uzbek spot cotton is typically 1.2–3.0 USD/kg
                        if 0.5 < val < 10.0:
                            return val
        except Exception as exc:
            self.logger.debug("UzRTSB scrape error (%s): %s", url, exc)
        return None
