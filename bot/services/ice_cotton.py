"""ICE Cotton Futures — async multi-source fetcher.

yfinance.ticker.info removed: it triggers Yahoo's rate-limited quoteSummary
endpoint which returns 429 in Docker/server environments.

Source priority:
1. Yahoo Finance v8 chart API  (async, less rate-limited, no yfinance)
2. Stooq.com JSON quote        (async, free, no auth)
3. yfinance.download()         (sync/thread, different endpoint from ticker.info)
4. Stale cache                 (always available after first success)
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

import aiohttp

from bot.services.cache_manager import cache
from bot.state import Commodity, record_price

logger = logging.getLogger(__name__)

CACHE_KEY = "ice_cotton"
CACHE_TTL = 240          # 4 minutes (market data)
STALE_TTL = 14400        # 4 hours stale cache

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="yf_dl")

# Yahoo Finance v8 chart API — much less rate-limited than quoteSummary
_YF_URL_1 = "https://query1.finance.yahoo.com/v8/finance/chart/CT=F"
_YF_URL_2 = "https://query2.finance.yahoo.com/v8/finance/chart/CT=F"
_YF_PARAMS = {"interval": "5m", "range": "1d", "includePrePost": "false"}

# Stooq — free market data, no auth, JSON
_STOOQ_URL = "https://stooq.com/q/l/?s=ct.f&f=sd2t2ohlcv&h&e=json"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Referer": "https://finance.yahoo.com/",
}

# Consecutive failure tracking for adaptive backoff
_fail_count: int = 0
_last_success_ts: Optional[float] = None


async def _fetch_yahoo_v8(session: aiohttp.ClientSession) -> Optional[dict]:
    """Query Yahoo Finance v8 chart endpoint (async, no yfinance)."""
    for url in (_YF_URL_1, _YF_URL_2):
        try:
            async with session.get(
                url,
                params=_YF_PARAMS,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as resp:
                if resp.status == 429:
                    logger.warning("Yahoo v8 rate-limited (429) on %s", url)
                    continue
                if resp.status != 200:
                    logger.debug("Yahoo v8 returned %d on %s", resp.status, url)
                    continue

                data = await resp.json(content_type=None)
                results = data.get("chart", {}).get("result") or []
                if not results:
                    continue

                meta = results[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                if not price:
                    continue

                price = float(price)
                if not (20.0 < price < 500.0):
                    continue

                prev_close = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
                change = round(price - prev_close, 2)
                change_pct = round((change / prev_close * 100) if prev_close else 0.0, 2)
                volume = int(meta.get("regularMarketVolume") or 0)

                # Day high/low from candle data (meta fields can be stale)
                quotes = results[0].get("indicators", {}).get("quote", [{}])[0]
                highs = [x for x in (quotes.get("high") or []) if x is not None]
                lows  = [x for x in (quotes.get("low")  or []) if x is not None]
                day_high = round(max(highs), 2) if highs else price
                day_low  = round(min(lows),  2) if lows  else price

                opens = [x for x in (quotes.get("open") or []) if x is not None]
                day_open = round(opens[0], 2) if opens else price

                logger.info("ICE cotton [Yahoo v8]: %.2f c/lb (chg %+.2f)", price, change)
                return {
                    "price": price,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": volume,
                    "open": day_open,
                    "high": day_high,
                    "low": day_low,
                    "prev_close": prev_close,
                    "timestamp": datetime.utcnow().isoformat(),
                    "source": "Yahoo Finance (v8 chart API)",
                    "unit": "c/lb",
                    "estimated": False,
                }
        except aiohttp.ClientError as exc:
            logger.debug("Yahoo v8 connection error (%s): %s", url, exc)
        except Exception as exc:
            logger.debug("Yahoo v8 parse error (%s): %s", url, exc)
    return None


async def _fetch_stooq(session: aiohttp.ClientSession) -> Optional[dict]:
    """Query Stooq.com for CT.F quote (previous session OHLCV + close price)."""
    try:
        async with session.get(
            _STOOQ_URL,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                logger.debug("Stooq returned %d", resp.status)
                return None
            data = await resp.json(content_type=None)
            symbols = data.get("symbols") or []
            if not symbols:
                return None

            q = symbols[0]
            price = float(q.get("close") or 0)
            if not (20.0 < price < 500.0):
                return None

            open_  = float(q.get("open")   or price)
            high   = float(q.get("high")   or price)
            low    = float(q.get("low")    or price)
            volume = int(q.get("volume")   or 0)

            logger.info("ICE cotton [Stooq]: %.2f c/lb (prev session)", price)
            return {
                "price": price,
                "change": 0.0,
                "change_pct": 0.0,
                "volume": volume,
                "open": open_,
                "high": high,
                "low": low,
                "prev_close": price,
                "timestamp": datetime.utcnow().isoformat(),
                "source": "Stooq.com (предыдущая сессия)",
                "unit": "c/lb",
                "estimated": False,
                "prev_session": True,
            }
    except Exception as exc:
        logger.debug("Stooq fetch error: %s", exc)
    return None


def _fetch_yf_download_sync() -> Optional[dict]:
    """yfinance.download() fallback — uses /v8/finance/download endpoint,
    NOT the rate-limited quoteSummary used by ticker.info."""
    try:
        import yfinance as yf
        df = yf.download("CT=F", period="2d", interval="5m", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None

        df = df.dropna(subset=["Close"])
        if df.empty:
            return None

        price = float(df["Close"].iloc[-1])
        if not (20.0 < price < 500.0):
            return None

        prev = float(df["Close"].iloc[-2]) if len(df) > 1 else price
        change = round(price - prev, 2)
        change_pct = round((change / prev * 100) if prev else 0.0, 2)

        today = df[df.index.date == df.index[-1].date()]
        high = float(today["High"].max()) if not today.empty else price
        low  = float(today["Low"].min())  if not today.empty else price
        open_ = float(today["Open"].iloc[0]) if not today.empty else price
        vol  = int(today["Volume"].sum())    if not today.empty else 0

        logger.info("ICE cotton [yf.download]: %.2f c/lb", price)
        return {
            "price": price,
            "change": change,
            "change_pct": change_pct,
            "volume": vol,
            "open": open_,
            "high": round(high, 2),
            "low": round(low, 2),
            "prev_close": prev,
            "timestamp": datetime.utcnow().isoformat(),
            "source": "yfinance download (резервный)",
            "unit": "c/lb",
            "estimated": False,
        }
    except Exception as exc:
        logger.debug("yf.download error: %s", exc)
        return None


async def _fetch_from_all() -> Optional[dict]:
    """Try all sources in priority order. Return first success."""
    global _fail_count, _last_success_ts

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
        # 1. Yahoo v8 chart API
        data = await _fetch_yahoo_v8(session)
        if data:
            _fail_count = 0
            _last_success_ts = asyncio.get_event_loop().time()
            return data

        # 2. Stooq
        data = await _fetch_stooq(session)
        if data:
            _fail_count = 0
            _last_success_ts = asyncio.get_event_loop().time()
            return data

    # 3. yfinance.download (thread pool — different API endpoint)
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(_EXECUTOR, _fetch_yf_download_sync)
        if data:
            _fail_count = 0
            _last_success_ts = asyncio.get_event_loop().time()
            return data
    except Exception as exc:
        logger.debug("yf.download executor error: %s", exc)

    _fail_count += 1
    logger.warning("ICE cotton: all sources failed (attempt #%d)", _fail_count)
    return None


async def fetch_ice_cotton(force_refresh: bool = False) -> Optional[dict]:
    """Fetch ICE Cotton data with caching. Returns cached or None."""
    if not force_refresh:
        cached = await cache.get(CACHE_KEY)
        if cached:
            return cached

    data = await _fetch_from_all()

    if data:
        await cache.set(CACHE_KEY, data, ttl=CACHE_TTL)
        await cache.set(CACHE_KEY + "_stale", data, ttl=STALE_TTL)
        record_price(Commodity.ICE_COTTON, data["price"], data["source"])
        return data

    # Return stale data rather than None
    stale = await cache.get(CACHE_KEY + "_stale")
    if stale:
        stale = dict(stale)  # copy to avoid mutating cached object
        stale["stale"] = True
        stale["stale_source"] = stale.get("source", "кэш")
        stale["source"] = "⚠️ Кэш (данные могут быть устаревшими)"
        logger.info("ICE cotton: returning stale cache (price=%.2f)", stale.get("price", 0))
        return stale

    return None


async def get_with_retry(retries: int = 2) -> Optional[dict]:
    """Fetch with up to `retries` attempts. Each attempt already tries 3 sources."""
    for attempt in range(retries):
        result = await fetch_ice_cotton(force_refresh=(attempt > 0))
        if result:
            return result
        if attempt < retries - 1:
            await asyncio.sleep(3)
    return None
