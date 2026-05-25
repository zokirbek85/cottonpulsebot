"""Alibaba B2B — cotton yarn price ranges via product listing scraping.

Alibaba product listings show price ranges rather than single prices.
We extract the midpoint of the range as an approximate market price.
Bot protection is high; this source frequently fails.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

# Search results for cotton yarn 30s; sorted by price for price discovery
_SEARCH_URL = (
    "https://www.alibaba.com/trade/search?SearchText=cotton+yarn+30s+carded"
    "&sortType=byPriceAsc&viewtype=G"
)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Patterns: "$2.50 - $3.00 / Kilogram", "USD 2.50-3.00 /kg"
_RANGE_PATTERNS = [
    r"\$\s*(\d+\.?\d*)\s*[-–]\s*\$?\s*(\d+\.?\d*)\s*/\s*(?:Kilogram|KG|kg)",
    r"USD\s+(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*/\s*(?:Kilogram|KG|kg)",
    r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s+USD\s*/\s*(?:Kilogram|KG|kg)",
]


class AlibabaYarnFetcher(BaseFetcher):
    """Alibaba B2B price range for cotton yarn 30s (midpoint estimate)."""

    def __init__(self) -> None:
        super().__init__(
            name="Alibaba B2B",
            priority=3,
            cache_ttl=7200,
            timeout=20,
            enabled=True,
        )

    async def fetch(self) -> FetchResult:
        start = datetime.utcnow()
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
                async with session.get(
                    _SEARCH_URL,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    allow_redirects=True,
                ) as resp:
                    self.logger.debug("Alibaba: HTTP %d", resp.status)
                    if resp.status != 200:
                        self.record_failure()
                        return FetchResult(success=False, error=f"HTTP {resp.status}")

                    html = await resp.text(errors="replace")
                    text = re.sub(r"<[^>]+>", " ", html)
                    price = self._extract_midpoint(text)

                    if price is None:
                        self.record_failure()
                        return FetchResult(
                            success=False, error="Alibaba: диапазон цен не найден"
                        )

                    data = PriceData(
                        price=price,
                        source=self.name,
                        timestamp=datetime.utcnow(),
                        unit="USD/kg",
                        is_estimated=True,
                        metadata={"note": "midpoint of listed price range"},
                    )
                    data.confidence = self.calculate_confidence(data) * 0.7  # B2B ranges are approximate

                    ms = (datetime.utcnow() - start).total_seconds() * 1000
                    self.record_success()
                    self.logger.info("Alibaba: %.2f USD/kg midpoint (%.0fms)", price, ms)
                    return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except aiohttp.ClientError as exc:
            self.record_failure()
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            self.record_failure()
            self.logger.error("Alibaba ошибка: %s", exc)
            return FetchResult(success=False, error=str(exc))

    def _extract_midpoint(self, text: str) -> Optional[float]:
        prices: list[float] = []
        for pat in _RANGE_PATTERNS:
            for m in re.finditer(pat, text, re.IGNORECASE):
                try:
                    low, high = float(m.group(1)), float(m.group(2))
                    if 1.0 < low < 20.0 and 1.0 < high < 20.0:
                        prices.append((low + high) / 2.0)
                except (ValueError, IndexError):
                    pass
            if prices:
                break

        if not prices:
            return None

        # Median of up to 10 first matches to avoid outliers
        sample = sorted(prices[:10])
        return sample[len(sample) // 2]
