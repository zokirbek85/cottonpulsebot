"""USDA NASS — official weekly cotton price received by US producers."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

_BASE_URL = "https://quickstats.nass.usda.gov/api/api_GET/"


def _get_api_key() -> Optional[str]:
    try:
        from bot.config import settings
        return settings.USDA_API_KEY  # type: ignore[attr-defined]
    except Exception:
        return None


class USDACottonFetcher(BaseFetcher):
    """USDA NASS weekly average price received by US cotton farmers."""

    def __init__(self) -> None:
        api_key = _get_api_key()
        super().__init__(
            name="USDA NASS",
            priority=3,
            cache_ttl=86400,
            timeout=15,
            enabled=bool(api_key),
        )

    async def fetch(self) -> FetchResult:
        api_key = _get_api_key()
        if not api_key:
            return FetchResult(success=False, error="USDA_API_KEY не настроен")

        start = datetime.utcnow()
        try:
            params = {
                "key": api_key,
                "commodity_desc": "COTTON",
                "statisticcat_desc": "PRICE RECEIVED",
                "agg_level_desc": "NATIONAL",
                "freq_desc": "WEEKLY",
                "format": "JSON",
                "year__GE": str(datetime.utcnow().year - 1),
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
                    records = raw.get("data", [])

                    if not records:
                        self.record_failure()
                        return FetchResult(success=False, error="Нет записей от USDA")

                    # Most recent record first
                    latest = records[0]
                    price_str = str(latest.get("Value", "")).replace(",", "").strip()

                    try:
                        price = float(price_str)
                    except ValueError:
                        self.record_failure()
                        return FetchResult(success=False, error=f"Некорректная цена: {price_str}")

                    if not (20.0 < price < 500.0):
                        self.record_failure()
                        return FetchResult(success=False, error=f"Цена вне диапазона: {price}")

                    date_str = latest.get("week_ending", "")
                    try:
                        ts = datetime.strptime(date_str, "%Y-%m-%d")
                    except Exception:
                        ts = datetime.utcnow()

                    data = PriceData(
                        price=price,
                        source=self.name,
                        timestamp=ts,
                        unit="c/lb",
                        metadata={
                            "period": latest.get("reference_period_desc", ""),
                            "week_ending": date_str,
                        },
                    )
                    data.confidence = self.calculate_confidence(data)

                    ms = (datetime.utcnow() - start).total_seconds() * 1000
                    self.record_success()
                    self.logger.info(
                        "USDA NASS: %.2f c/lb (неделя=%s, %.0fms)", price, date_str, ms
                    )
                    return FetchResult(success=True, data=data, fetch_time_ms=ms)

        except aiohttp.ClientError as exc:
            self.record_failure()
            self.logger.warning("USDA connection error: %s", exc)
            return FetchResult(success=False, error=str(exc))
        except Exception as exc:
            self.record_failure()
            self.logger.error("USDA ошибка: %s", exc, exc_info=True)
            return FetchResult(success=False, error=str(exc))
