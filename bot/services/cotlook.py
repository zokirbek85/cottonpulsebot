"""Cotlook A Index — multi-source with graceful fallback.

IndexMundi uses FusionCharts JS rendering: HTML has no price data.
Alternative sources attempted. Final fallback: ICE + A-Index premium.

Source priority:
1. World Bank Pink Sheet JSON API  (monthly update, official)
2. IMF Primary Commodity Prices API (monthly)
3. Derived estimate: ICE + A_INDEX_PREMIUM_CENTS  (labeled ⚠️расч.)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.cache_manager import cache
from bot.state import Commodity, record_price

logger = logging.getLogger(__name__)

CACHE_KEY = "cotlook"
CACHE_TTL = 3600        # 1 hour (Cotlook publishes once/day)
STALE_TTL = 86400       # 24 hours stale

# Cotlook A historically ~3–6 c/lb above ICE CT=F nearest month
A_INDEX_PREMIUM_CENTS = 4.5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html;q=0.9",
}

# World Bank Commodity Price API — Cotton A Index = "PCOTTINDEXT"
_WB_URL = (
    "https://api.worldbank.org/v2/en/indicator/PCOTTINDEXT"
    "?downloadformat=json&mrv=3&per_page=3&format=json"
)

# IMF Primary Commodity Prices
_IMF_URL = (
    "https://www.imf.org/-/media/Files/Research/CommodityPrices/"
    "Monthly/external-data.ashx"
)


async def _fetch_worldbank(session: aiohttp.ClientSession) -> Optional[float]:
    """Try World Bank Cotton A Index API (monthly, official)."""
    try:
        async with session.get(_WB_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.debug("WorldBank cotlook: status %d", resp.status)
                return None
            raw = await resp.json(content_type=None)
            # Response: [metadata_dict, [data_points]]
            if not isinstance(raw, list) or len(raw) < 2:
                return None
            points = raw[1]
            if not points:
                return None
            # Find most recent non-null value
            for pt in points:
                val = pt.get("value")
                if val is not None:
                    price = float(val)
                    if 20.0 < price < 300.0:
                        logger.info("Cotlook A [WorldBank]: %.2f c/lb", price)
                        return price
    except Exception as exc:
        logger.debug("WorldBank cotlook error: %s", exc)
    return None


async def _fetch_nasdaq_data(session: aiohttp.ClientSession) -> Optional[float]:
    """Try Nasdaq Data Link (formerly Quandl) public cotton dataset."""
    # CFTC public cotton data — no auth required for recent public datasets
    url = "https://data.nasdaq.com/api/v3/datasets/ODA/PCOTTINDEXT.json?rows=2"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status not in (200, 403):
                return None
            if resp.status == 403:
                logger.debug("Nasdaq data: requires API key")
                return None
            data = await resp.json(content_type=None)
            rows = (data.get("dataset") or {}).get("data") or []
            for row in rows:
                if row and len(row) >= 2 and row[1] is not None:
                    price = float(row[1])
                    if 20.0 < price < 300.0:
                        logger.info("Cotlook A [Nasdaq]: %.2f c/lb", price)
                        return price
    except Exception as exc:
        logger.debug("Nasdaq data error: %s", exc)
    return None


async def _derive_from_ice(ice_price: float) -> dict:
    """Standard industry estimate: Cotlook A ≈ ICE nearest month + premium."""
    price = round(ice_price + A_INDEX_PREMIUM_CENTS, 2)
    return {
        "price": price,
        "change": 0.0,
        "timestamp": datetime.utcnow().isoformat(),
        "source": f"Расчёт: ICE CT=F + {A_INDEX_PREMIUM_CENTS:.1f} ц/фунт надбавка",
        "unit": "c/lb",
        "estimated": True,
    }


async def fetch_cotlook(
    ice_price: Optional[float] = None,
    force_refresh: bool = False,
) -> Optional[dict]:
    if not force_refresh:
        cached = await cache.get(CACHE_KEY)
        if cached:
            return cached

    price: Optional[float] = None
    source = ""

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
        price = await _fetch_worldbank(session)
        if price:
            source = "World Bank Commodity API"
        else:
            price = await _fetch_nasdaq_data(session)
            if price:
                source = "Nasdaq Data Link"

    if price and 20.0 < price < 300.0:
        prev = await cache.get(CACHE_KEY + "_prev")
        change = round(price - prev["price"], 2) if prev else 0.0
        await cache.set(CACHE_KEY + "_prev", {"price": price}, ttl=86400)

        data = {
            "price": price,
            "change": change,
            "timestamp": datetime.utcnow().isoformat(),
            "source": source,
            "unit": "c/lb",
            "estimated": False,
        }
        await cache.set(CACHE_KEY, data, ttl=CACHE_TTL)
        await cache.set(CACHE_KEY + "_stale", data, ttl=STALE_TTL)
        record_price(Commodity.COTLOOK, price, source)
        logger.info("Cotlook A fetched: %.2f c/lb from %s", price, source)
        return data

    # Stale cache
    stale = await cache.get(CACHE_KEY + "_stale")
    if stale:
        stale = dict(stale)
        stale["stale"] = True
        logger.info("Cotlook A: returning stale cache (%.2f)", stale.get("price", 0))
        return stale

    # Derived estimate as last resort
    if ice_price is not None:
        data = await _derive_from_ice(ice_price)
        await cache.set(CACHE_KEY, data, ttl=CACHE_TTL)
        logger.info("Cotlook A derived: %.2f c/lb (estimated)", data["price"])
        return data

    return None


async def get_with_retry(
    ice_price: Optional[float] = None, retries: int = 2
) -> Optional[dict]:
    for attempt in range(retries):
        result = await fetch_cotlook(ice_price=ice_price, force_refresh=(attempt > 0))
        if result:
            await cache.set(CACHE_KEY + "_stale", result, ttl=STALE_TTL)
            return result
        if attempt < retries - 1:
            await asyncio.sleep(2)
    return None
