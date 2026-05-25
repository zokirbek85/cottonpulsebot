"""Made-in-China.com — cotton yarn price ranges from Chinese supplier listings."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

_SEARCH_URL = "https://www.made-in-china.com/products-search/hot-china-products/Cotton_Yarn_30s.html"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_RANGE_PATTERNS = [
    r"USD\s+(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*/\s*(?:kg|KG|Kilogram)",
    r"\$\s*(\d+\.?\d*)\s*[-–]\s*\$?\s*(\d+\.?\d*)\s*/\s*(?:kg|KG|Kilogram)",
    r"(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s+USD\s*/\s*(?:kg|KG|Kilogram)",
]
_SINGLE_PATTERNS = [
    r"USD\s+(\d+\.?\d*)\s*/\s*(?:kg|KG|Kilogram)",
    r"\$(\d+\.?\d*)\s*/\s*(?:kg|KG|Kilogram)",
]


class MadeInChinaYarnFetcher(BaseFetcher):
    """Made-in-China.com cotton yarn 30s price (midpoint of listing ranges)."""

    def __init__(self) -> None:
        super().__init__(
            name="Made-in-China.com",
            priority=5,
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
                    self.logger.debug("Made-in-China: HTTP %d", resp.status)
                    if resp.status != 200:
                        self.record_failure()
                        return FetchResult(success=False, error=f"HTTP {resp.status}")

                    html = await resp.text(errors="replace")
                    text = re.sub(r"<[^>]+>", " ", html)
                    price = self._extract_price(text)

                    if price is None:
                        self.record_failure()
                        return FetchResult(
                            success=False, error="Made-in-China: цена не найдена"
                        )

                    data = PriceData(
                        price=price,
                        source=self.name,
                        timestamp=datetime.utcnow(),
                        unit="USD/kg",
                        is_estimated=True,
                        metadata={"note": "listing midpoint"},
                    )
                    data.confidence = self.calculate_confidence(data) * 0.65

                    ms = (datetime.utcnow() - start).total_seconds() * 1000
                    self.record_success()
                    self.logger.info("Made-in-China: %.2f USD/kg (%.0fms)", price, ms)
                    return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except aiohttp.ClientError as exc:
            self.record_failure()
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            self.record_failure()
            self.logger.error("Made-in-China ошибка: %s", exc)
            return FetchResult(success=False, error=str(exc))

    def _extract_price(self, text: str) -> Optional[float]:
        prices: list[float] = []

        # Try range patterns first
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

        # Fall back to single prices
        if not prices:
            for pat in _SINGLE_PATTERNS:
                for m in re.finditer(pat, text, re.IGNORECASE):
                    try:
                        val = float(m.group(1))
                        if 1.0 < val < 20.0:
                            prices.append(val)
                    except (ValueError, IndexError):
                        pass
                if prices:
                    break

        if not prices:
            return None

        sample = sorted(prices[:10])
        return sample[len(sample) // 2]
