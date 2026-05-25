"""FX rate service — USD/UZS.

Primary:    Central Bank of Uzbekistan public JSON API (cbu.uz)
Secondary:  open.er-api.com (free, no key)
Tertiary:   exchangerate.host (free, no key)
Hardcoded:  Last known rate stored in module variable as absolute last resort
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.cache_manager import cache
from bot.state import Commodity, record_price

logger = logging.getLogger(__name__)

CACHE_KEY = "usd_uzs"
CACHE_TTL = 600         # 10 minutes (CBU updates once daily anyway)
STALE_TTL = 86400       # 24 hours stale

# CBU Uzbekistan official JSON API
_CBU_URL = "https://cbu.uz/en/arkhiv-kursov-valyut/json/"
# Free exchange rate APIs (no key required)
_ER_API_URL = "https://open.er-api.com/v6/latest/USD"
_EXCHANGERATE_HOST_URL = "https://api.exchangerate.host/latest?base=USD&symbols=UZS"

# Module-level last known rate (absolute fallback, persists in process memory)
_last_known_rate: float = 12500.0

_HEADERS = {
    "User-Agent": "CottonPulseBot/1.0 (Uzbekistan market data aggregator)",
    "Accept": "application/json",
}


async def _try_cbu(session: aiohttp.ClientSession) -> Optional[float]:
    try:
        async with session.get(_CBU_URL, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status != 200:
                logger.debug("CBU API returned %d", resp.status)
                return None
            data = await resp.json(content_type=None)
            if isinstance(data, list):
                for item in data:
                    if item.get("Ccy") == "USD":
                        rate = float(item["Rate"])
                        logger.info("USD/UZS [CBU]: %.2f", rate)
                        return rate
    except Exception as exc:
        logger.warning("CBU API error: %s", exc)
    return None


async def _try_er_api(session: aiohttp.ClientSession) -> Optional[float]:
    try:
        async with session.get(_ER_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            if data.get("result") == "success":
                rate = float(data["rates"]["UZS"])
                logger.info("USD/UZS [er-api.com]: %.2f", rate)
                return rate
    except Exception as exc:
        logger.debug("er-api.com error: %s", exc)
    return None


async def _try_exchangerate_host(session: aiohttp.ClientSession) -> Optional[float]:
    try:
        async with session.get(_EXCHANGERATE_HOST_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            if data.get("success"):
                rate = float(data["rates"]["UZS"])
                logger.info("USD/UZS [exchangerate.host]: %.2f", rate)
                return rate
    except Exception as exc:
        logger.debug("exchangerate.host error: %s", exc)
    return None


async def fetch_usd_uzs(force_refresh: bool = False) -> Optional[dict]:
    global _last_known_rate

    if not force_refresh:
        cached = await cache.get(CACHE_KEY)
        if cached:
            return cached

    rate: Optional[float] = None
    source = ""

    # Try all sources with separate SSL handling
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
        rate = await _try_cbu(session)
        if rate:
            source = "ЦБ Узбекистана (cbu.uz)"

        if not rate:
            rate = await _try_er_api(session)
            if rate:
                source = "open.er-api.com"

        if not rate:
            rate = await _try_exchangerate_host(session)
            if rate:
                source = "exchangerate.host"

    if rate and rate > 1000:  # UZS is always >1000 per USD
        _last_known_rate = rate  # update module-level fallback
        prev = await cache.get(CACHE_KEY + "_prev")
        change = round(rate - prev["rate"], 2) if prev else 0.0
        change_pct = round((change / prev["rate"] * 100), 4) if prev and prev["rate"] else 0.0
        await cache.set(CACHE_KEY + "_prev", {"rate": rate}, ttl=86400)

        data = {
            "rate": round(rate, 2),
            "change": change,
            "change_pct": change_pct,
            "timestamp": datetime.utcnow().isoformat(),
            "source": source,
            "unit": "сум",
            "estimated": False,
        }
        await cache.set(CACHE_KEY, data, ttl=CACHE_TTL)
        await cache.set(CACHE_KEY + "_stale", data, ttl=STALE_TTL)
        record_price(Commodity.USD_UZS, rate, source)
        return data

    # Stale cache
    stale = await cache.get(CACHE_KEY + "_stale")
    if stale:
        stale = dict(stale)
        stale["stale"] = True
        logger.warning("USD/UZS: all sources failed, using stale cache (%.2f)", stale.get("rate", 0))
        return stale

    # Absolute fallback: last known rate in memory
    logger.error("USD/UZS: all sources failed. Using last known rate: %.2f", _last_known_rate)
    fallback = {
        "rate": _last_known_rate,
        "change": 0.0,
        "change_pct": 0.0,
        "timestamp": datetime.utcnow().isoformat(),
        "source": "⚠️ Последний известный курс (все источники недоступны)",
        "unit": "сум",
        "estimated": True,
        "stale": True,
    }
    return fallback


async def get_uzs_rate() -> float:
    """Return numeric rate. Never returns None — always has a fallback."""
    data = await fetch_usd_uzs()
    if data:
        return data["rate"]
    return _last_known_rate
