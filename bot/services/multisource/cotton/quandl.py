"""Quandl / Nasdaq Data Link — ICE Cotton CT1 continuous futures (1-day delay)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

_BASE_URL = "https://data.nasdaq.com/api/v3/datasets/CHRIS/ICE_CT1.json"


def _get_api_key() -> Optional[str]:
    try:
        from bot.config import settings
        return settings.QUANDL_API_KEY  # type: ignore[attr-defined]
    except Exception:
        return None


class QuandlCottonFetcher(BaseFetcher):
    """ICE Cotton front-month settle price from Quandl (free tier, 1-day lag)."""

    def __init__(self) -> None:
        api_key = _get_api_key()
        super().__init__(
            name="Quandl (Nasdaq DL)",
            priority=2,
            cache_ttl=3600,
            timeout=10,
            enabled=bool(api_key),
        )

    async def fetch(self) -> FetchResult:
        api_key = _get_api_key()
        if not api_key:
            return FetchResult(success=False, error="QUANDL_API_KEY не настроен")

        start = datetime.utcnow()
        try:
            params = {"api_key": api_key, "limit": 1, "order": "desc"}
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    _BASE_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        self.record_failure()
                        return FetchResult(success=False, error=f"HTTP {resp.status}")

                    raw = await resp.json(content_type=None)
                    dataset = raw.get("dataset", {})
                    rows = dataset.get("data", [])

                    if not rows:
                        self.record_failure()
                        return FetchResult(success=False, error="Нет данных в ответе")

                    # columns: [Date, Open, High, Low, Settle, Volume, Prev Day OI]
                    row = rows[0]
                    date_str = row[0]
                    open_price = float(row[1]) if row[1] is not None else None
                    high = float(row[2]) if row[2] is not None else None
                    low = float(row[3]) if row[3] is not None else None
                    settle = float(row[4])
                    volume = int(row[5]) if len(row) > 5 and row[5] else None

                    if not (20.0 < settle < 500.0):
                        self.record_failure()
                        return FetchResult(success=False, error=f"Цена вне диапазона: {settle}")

                    try:
                        ts = datetime.fromisoformat(date_str)
                    except ValueError:
                        ts = datetime.utcnow()

                    data = PriceData(
                        price=settle,
                        source=self.name,
                        timestamp=ts,
                        unit="c/lb",
                        open=open_price,
                        high=high,
                        low=low,
                        close=settle,
                        volume=volume,
                        metadata={"settle_date": date_str},
                    )
                    data.confidence = self.calculate_confidence(data)

                    ms = (datetime.utcnow() - start).total_seconds() * 1000
                    self.record_success()
                    self.logger.info(
                        "Quandl: %.2f c/lb (дата=%s, %.0fms)", settle, date_str, ms
                    )
                    return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except aiohttp.ClientError as exc:
            self.record_failure()
            self.logger.warning("Quandl connection error: %s", exc)
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            self.record_failure()
            self.logger.error("Quandl ошибка: %s", exc, exc_info=True)
            return FetchResult(success=False, error=str(exc))
