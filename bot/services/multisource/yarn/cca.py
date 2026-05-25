"""China Cotton Association (CCA) — cotton and yarn market data."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

# CCA publishes price bulletins; try their market data section
_URLS = [
    "http://www.china-cotton.org/en/market/",
    "http://www.china-cotton.org/en/price/",
]
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}

_PRICE_PATTERNS = [
    r"yarn[^<]*?(\d+\.\d{1,2})\s*(?:USD|US\$)\s*/\s*kg",
    r"(\d+\.\d{1,2})\s*(?:USD|US\$)\s*/\s*(?:kg|KG)",
    r"(?:price|quotation)[^<]*?(\d+\.\d{1,2})",
]


class CCAYarnFetcher(BaseFetcher):
    """China Cotton Association yarn/cotton price data."""

    def __init__(self) -> None:
        super().__init__(
            name="China Cotton Assoc.",
            priority=2,
            cache_ttl=7200,
            timeout=15,
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
                        )
                        data.confidence = self.calculate_confidence(data)

                        ms = (datetime.utcnow() - start).total_seconds() * 1000
                        self.record_success()
                        self.logger.info("CCA: %.2f USD/kg (%.0fms)", price, ms)
                        return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except Exception as exc:
            self.logger.debug("CCA неожиданная ошибка: %s", exc)

        self.record_failure()
        return FetchResult(success=False, error="CCA: цена не найдена")

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
                for pat in _PRICE_PATTERNS:
                    for m in re.finditer(pat, text, re.IGNORECASE):
                        try:
                            val = float(m.group(1))
                            if 1.0 < val < 20.0:
                                return val
                        except (ValueError, IndexError):
                            pass
        except Exception as exc:
            self.logger.debug("CCA error (%s): %s", url, exc)
        return None
