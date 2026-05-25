"""Fiber2Fashion — yarn price scraping (best-effort; most pages are JS-rendered)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

_BASE_URL = "https://www.fibre2fashion.com/market-intelligence/textile-market-analysis/country/{country}/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}

_PRICE_PATTERNS = [
    r"USD\s+(\d+\.\d{1,2})\s*/\s*kg",
    r"(\d+\.\d{1,2})\s+USD\s*/\s*kg",
    r"\$\s*(\d+\.\d{1,2})\s*/\s*kg",
    r"(\d+\.\d{1,2})\s*(?:US\s*)?(?:dollars?|USD)\s+per\s+kg",
]


class Fiber2FashionYarnFetcher(BaseFetcher):
    """Fiber2Fashion yarn price for a specific country."""

    def __init__(self, country: str) -> None:
        self.country = country
        super().__init__(
            name=f"Fiber2Fashion ({country})",
            priority=1,
            cache_ttl=3600,
            timeout=15,
            enabled=True,
        )

    async def fetch(self) -> FetchResult:
        start = datetime.utcnow()
        url = _BASE_URL.format(country=self.country.lower())
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    self.logger.debug(
                        "Fiber2Fashion %s: HTTP %d", self.country, resp.status
                    )
                    if resp.status != 200:
                        self.record_failure()
                        return FetchResult(
                            success=False, error=f"HTTP {resp.status}"
                        )

                    html = await resp.text(errors="replace")
                    text = re.sub(r"<[^>]+>", " ", html)
                    price = self._extract_price(text)

                    if price is None:
                        self.record_failure()
                        self.logger.debug(
                            "Fiber2Fashion %s: страница загружена, цена не найдена (JS?)",
                            self.country,
                        )
                        return FetchResult(
                            success=False,
                            error="Цена не найдена (JS-рендеринг?)",
                        )

                    data = PriceData(
                        price=price,
                        source=self.name,
                        timestamp=datetime.utcnow(),
                        unit="USD/kg",
                    )
                    data.confidence = self.calculate_confidence(data)

                    ms = (datetime.utcnow() - start).total_seconds() * 1000
                    self.record_success()
                    self.logger.info(
                        "Fiber2Fashion %s: %.2f USD/kg (%.0fms)", self.country, price, ms
                    )
                    return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except aiohttp.ClientError as exc:
            self.record_failure()
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            self.record_failure()
            self.logger.error("Fiber2Fashion %s ошибка: %s", self.country, exc)
            return FetchResult(success=False, error=str(exc))

    def _extract_price(self, text: str) -> Optional[float]:
        for pat in _PRICE_PATTERNS:
            for m in re.finditer(pat, text, re.IGNORECASE):
                try:
                    val = float(m.group(1))
                    if 1.0 < val < 20.0:
                        return val
                except (ValueError, IndexError):
                    pass
        return None
