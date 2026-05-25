"""FRED (Federal Reserve Economic Data) — monthly cotton price index."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

# PCOTTINDUSDM = Cotton, No. 1 Ordinary, Memphis, monthly, USD/lb
_SERIES_ID = "PCOTTINDUSDM"
_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


def _get_api_key() -> Optional[str]:
    try:
        from bot.config import settings
        return settings.FRED_API_KEY  # type: ignore[attr-defined]
    except Exception:
        return None


class FREDCottonFetcher(BaseFetcher):
    """Monthly cotton price index from St. Louis Federal Reserve FRED API."""

    def __init__(self) -> None:
        api_key = _get_api_key()
        super().__init__(
            name="FRED (St. Louis Fed)",
            priority=5,
            cache_ttl=86400,
            timeout=10,
            enabled=bool(api_key),
        )

    async def fetch(self) -> FetchResult:
        api_key = _get_api_key()
        if not api_key:
            return FetchResult(success=False, error="FRED_API_KEY не настроен")

        start = datetime.utcnow()
        try:
            params = {
                "series_id": _SERIES_ID,
                "api_key": api_key,
                "file_type": "json",
                "limit": 3,
                "sort_order": "desc",
            }
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
                    observations = raw.get("observations", [])

                    # Find most recent non-"." value
                    price: Optional[float] = None
                    date_str = ""
                    for obs in observations:
                        val = obs.get("value", ".")
                        if val == ".":
                            continue
                        try:
                            price_usd_lb = float(val)
                            # FRED series is in USD/lb; convert to cents/lb
                            price = round(price_usd_lb * 100.0, 2)
                            date_str = obs.get("date", "")
                            break
                        except ValueError:
                            continue

                    if price is None:
                        self.record_failure()
                        return FetchResult(success=False, error="Нет данных в FRED")

                    if not (20.0 < price < 500.0):
                        self.record_failure()
                        return FetchResult(success=False, error=f"Цена вне диапазона: {price}")

                    try:
                        ts = datetime.strptime(date_str, "%Y-%m-%d")
                    except Exception:
                        ts = datetime.utcnow()

                    data = PriceData(
                        price=price,
                        source=self.name,
                        timestamp=ts,
                        unit="c/lb",
                        metadata={"series_id": _SERIES_ID, "period": date_str},
                    )
                    data.confidence = self.calculate_confidence(data)

                    ms = (datetime.utcnow() - start).total_seconds() * 1000
                    self.record_success()
                    self.logger.info(
                        "FRED: %.2f c/lb (период=%s, %.0fms)", price, date_str, ms
                    )
                    return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except aiohttp.ClientError as exc:
            self.record_failure()
            self.logger.warning("FRED connection error: %s", exc)
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            self.record_failure()
            self.logger.error("FRED ошибка: %s", exc, exc_info=True)
            return FetchResult(success=False, error=str(exc))
