"""Stooq.com — previous session ICE Cotton CT.F OHLCV."""
from __future__ import annotations

from datetime import datetime

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

_URL = "https://stooq.com/q/l/?s=ct.f&f=sd2t2ohlcv&h&e=json"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


class StooqCottonFetcher(BaseFetcher):
    """Stooq.com free JSON quote for CT.F (previous session close)."""

    def __init__(self) -> None:
        super().__init__(
            name="Stooq.com",
            priority=6,
            cache_ttl=3600,
            timeout=10,
            enabled=True,
        )

    async def fetch(self) -> FetchResult:
        start = datetime.utcnow()
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
                async with session.get(
                    _URL,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        self.record_failure()
                        return FetchResult(success=False, error=f"HTTP {resp.status}")

                    raw = await resp.json(content_type=None)
                    symbols = raw.get("symbols") or []

                    if not symbols:
                        self.record_failure()
                        return FetchResult(success=False, error="Нет symbols в ответе Stooq")

                    q = symbols[0]
                    price = float(q.get("close") or 0)

                    if not (20.0 < price < 500.0):
                        self.record_failure()
                        return FetchResult(success=False, error=f"Цена вне диапазона: {price}")

                    data = PriceData(
                        price=price,
                        source=self.name,
                        timestamp=datetime.utcnow(),
                        unit="c/lb",
                        open=float(q.get("open") or price),
                        high=float(q.get("high") or price),
                        low=float(q.get("low") or price),
                        close=price,
                        volume=int(q.get("volume") or 0),
                        metadata={"prev_session": True},
                    )
                    data.confidence = self.calculate_confidence(data)

                    ms = (datetime.utcnow() - start).total_seconds() * 1000
                    self.record_success()
                    self.logger.info("Stooq: %.2f c/lb (пред. сессия, %.0fms)", price, ms)
                    return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except aiohttp.ClientError as exc:
            self.record_failure()
            self.logger.warning("Stooq connection error: %s", exc)
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            self.record_failure()
            self.logger.error("Stooq ошибка: %s", exc, exc_info=True)
            return FetchResult(success=False, error=str(exc))
