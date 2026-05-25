"""Yarn price data — model-based with scraping attempts.

Fiber2Fashion and most textile news sites are JS-rendered (require headless browser).
We log the scraping attempts for diagnostics but rely on the cotton-to-yarn model
as the primary source since it's always available and industry-accurate.

Model: yarn_USD/kg = cotton_USD/kg × CONVERSION + spinning_margin[country]
Conversion: 1 kg 30s carded yarn ≈ 1.15 kg raw cotton lint
Spinning margins (USD/kg, typical 2024-2026):
  China:    1.10
  India:    0.95
  Pakistan: 0.90
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.cache_manager import cache
from bot.state import Commodity, record_price
from bot.utils.converters import cents_per_lb_to_usd_per_kg

logger = logging.getLogger(__name__)

CACHE_TTLS = {"china": 1800, "india": 1800, "pakistan": 1800}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_CONVERSION_FACTOR = 1.15  # kg lint per kg 30s yarn
_SPINNING_MARGINS = {"china": 1.10, "india": 0.95, "pakistan": 0.90}
_COMMODITY_KEYS = {
    "china": Commodity.YARN_CHINA,
    "india": Commodity.YARN_INDIA,
    "pakistan": Commodity.YARN_PAKISTAN,
}
_YARN_COUNT = "30s кардная"
_COUNTRY_NAMES_RU = {"china": "Китай", "india": "Индия", "pakistan": "Пакистан"}


def _model_price(cotton_cents_per_lb: float, country: str) -> float:
    """Cotton-to-yarn conversion model. Returns USD/kg."""
    cotton_usd_kg = cents_per_lb_to_usd_per_kg(cotton_cents_per_lb)
    margin = _SPINNING_MARGINS.get(country, 1.00)
    return round(cotton_usd_kg * _CONVERSION_FACTOR + margin, 2)


async def _try_scrape_fiber2fashion(
    session: aiohttp.ClientSession, country: str
) -> Optional[float]:
    """Attempt Fiber2Fashion scraping. Most pages are JS-rendered — logs result."""
    url = f"https://www.fibre2fashion.com/market-intelligence/textile-market-analysis/country/{country}/"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            logger.debug("Fiber2Fashion %s: status %d", country, resp.status)
            if resp.status != 200:
                return None
            html = await resp.text()
            text = re.sub(r"<[^>]+>", " ", html)  # strip tags
            # Match: USD 3.20/kg, 3.20 USD/kg, $3.20/kg
            patterns = [
                r"USD\s+(\d+\.\d{1,2})\s*/\s*kg",
                r"(\d+\.\d{1,2})\s+USD\s*/\s*kg",
                r"\$\s*(\d+\.\d{1,2})\s*/\s*kg",
            ]
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    val = float(m.group(1))
                    if 1.0 < val < 15.0:
                        logger.info("Fiber2Fashion %s yarn: %.2f USD/kg (live)", country, val)
                        return val
            logger.debug("Fiber2Fashion %s: page loaded but no price found (JS-rendered?)", country)
    except Exception as exc:
        logger.debug("Fiber2Fashion %s error: %s", country, exc)
    return None


async def _try_scrape_textile_exchange(
    session: aiohttp.ClientSession, country: str
) -> Optional[float]:
    """Try TextileExchange or similar aggregator."""
    # These are mostly JS-rendered; attempt anyway and log
    sources = {
        "china": "https://www.textiletechnology.net/technology/news/",
        "india": "https://www.indiantextilejournal.com/category/yarn/",
        "pakistan": "https://www.textiletoday.com.bd/category/yarn/",
    }
    url = sources.get(country)
    if not url:
        return None
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()
            text = re.sub(r"<[^>]+>", " ", html)
            m = re.search(r"USD\s+(\d+\.\d{1,2})\s*/\s*kg", text, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                if 1.0 < val < 15.0:
                    logger.info("Textile news %s yarn: %.2f USD/kg", country, val)
                    return val
    except Exception as exc:
        logger.debug("Textile news %s error: %s", country, exc)
    return None


async def fetch_yarn(
    country: str,
    cotton_price_cents: Optional[float] = None,
    force_refresh: bool = False,
) -> Optional[dict]:
    """Fetch yarn price for country. Model-derived when live scraping fails."""
    cache_key = f"yarn_{country}"

    if not force_refresh:
        cached = await cache.get(cache_key)
        if cached:
            return cached

    price: Optional[float] = None
    source = ""
    estimated = True  # default assumption

    # Attempt live scraping (best effort)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
        price = await _try_scrape_fiber2fashion(session, country)
        if price:
            source = "Fiber2Fashion (live)"
            estimated = False
        else:
            price = await _try_scrape_textile_exchange(session, country)
            if price:
                source = "Textile Exchange (live)"
                estimated = False

    # Model fallback — always available when cotton price is known
    if not price and cotton_price_cents is not None:
        price = _model_price(cotton_price_cents, country)
        margin = _SPINNING_MARGINS.get(country, 1.00)
        cotton_usd = cents_per_lb_to_usd_per_kg(cotton_price_cents)
        name_ru = _COUNTRY_NAMES_RU.get(country, country)
        source = (
            f"Модель: хлопок {cotton_usd:.3f} × {_CONVERSION_FACTOR} "
            f"+ прядение {margin:.2f} = {price:.2f} USD/кг ({name_ru})"
        )
        estimated = True
        logger.info("Yarn %s model price: %.2f USD/kg", country, price)

    if not price:
        # Try stale cache
        stale = await cache.get(cache_key + "_stale")
        if stale:
            stale = dict(stale)
            stale["stale"] = True
            return stale
        logger.warning("Yarn %s: no price available (no cotton price for model)", country)
        return None

    prev = await cache.get(cache_key + "_prev")
    change = round(price - prev["price"], 4) if prev else 0.0
    await cache.set(cache_key + "_prev", {"price": price}, ttl=86400)

    data = {
        "price": price,
        "change": change,
        "timestamp": datetime.utcnow().isoformat(),
        "source": source,
        "unit": "USD/кг",
        "count": _YARN_COUNT,
        "estimated": estimated,
    }

    ttl = CACHE_TTLS.get(country, 1800)
    await cache.set(cache_key, data, ttl=ttl)
    await cache.set(cache_key + "_stale", data, ttl=7200)

    commodity_key = _COMMODITY_KEYS.get(country)
    if commodity_key:
        record_price(commodity_key, price, source)

    return data


async def fetch_all_yarn(
    cotton_price_cents: Optional[float] = None,
) -> dict[str, Optional[dict]]:
    tasks = {
        "china": fetch_yarn("china", cotton_price_cents),
        "india": fetch_yarn("india", cotton_price_cents),
        "pakistan": fetch_yarn("pakistan", cotton_price_cents),
    }
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    out = {}
    for country, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            logger.error("fetch_all_yarn %s exception: %s", country, result)
            out[country] = None
        else:
            out[country] = result
    return out
