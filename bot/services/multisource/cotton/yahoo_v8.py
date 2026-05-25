"""Yahoo Finance v8 chart API — real-time ICE Cotton futures."""
from __future__ import annotations

from datetime import datetime

import aiohttp

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

_URL_1 = "https://query1.finance.yahoo.com/v8/finance/chart/CT=F"
_URL_2 = "https://query2.finance.yahoo.com/v8/finance/chart/CT=F"
_PARAMS = {"interval": "5m", "range": "1d", "includePrePost": "false"}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Referer": "https://finance.yahoo.com/",
}


class YahooV8CottonFetcher(BaseFetcher):
    """ICE Cotton CT=F via Yahoo Finance v8 chart API (no yfinance, less rate-limited)."""

    def __init__(self) -> None:
        super().__init__(
            name="Yahoo Finance v8",
            priority=1,
            cache_ttl=240,
            timeout=12,
            enabled=True,
        )

    async def fetch(self) -> FetchResult:
        start = datetime.utcnow()
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            async with aiohttp.ClientSession(headers=_HEADERS, connector=connector) as session:
                for url in (_URL_1, _URL_2):
                    try:
                        async with session.get(
                            url,
                            params=_PARAMS,
                            timeout=aiohttp.ClientTimeout(total=self.timeout),
                        ) as resp:
                            if resp.status == 429:
                                self.logger.warning("Yahoo v8 rate-limited (429) на %s", url)
                                continue
                            if resp.status != 200:
                                continue

                            raw = await resp.json(content_type=None)
                            results = raw.get("chart", {}).get("result") or []
                            if not results:
                                continue

                            meta = results[0].get("meta", {})
                            price = meta.get("regularMarketPrice")
                            if not price:
                                continue

                            price = float(price)
                            if not (20.0 < price < 500.0):
                                continue

                            prev_close = float(
                                meta.get("chartPreviousClose")
                                or meta.get("previousClose")
                                or price
                            )
                            change = round(price - prev_close, 2)
                            change_pct = round(
                                (change / prev_close * 100) if prev_close else 0.0, 2
                            )
                            volume = int(meta.get("regularMarketVolume") or 0)

                            quotes = results[0].get("indicators", {}).get("quote", [{}])[0]
                            highs = [x for x in (quotes.get("high") or []) if x is not None]
                            lows = [x for x in (quotes.get("low") or []) if x is not None]
                            opens = [x for x in (quotes.get("open") or []) if x is not None]

                            data = PriceData(
                                price=price,
                                source=self.name,
                                timestamp=datetime.utcnow(),
                                unit="c/lb",
                                change=change,
                                change_pct=change_pct,
                                volume=volume,
                                open=round(opens[0], 2) if opens else price,
                                high=round(max(highs), 2) if highs else price,
                                low=round(min(lows), 2) if lows else price,
                                close=price,
                                metadata={"prev_close": prev_close},
                            )
                            data.confidence = self.calculate_confidence(data)

                            ms = (datetime.utcnow() - start).total_seconds() * 1000
                            self.record_success()
                            self.logger.info(
                                "Yahoo v8: %.2f c/lb (chg %+.2f, %.0fms)", price, change, ms
                            )
                            return FetchResult(success=True, data=data, fetch_time_ms=ms)

                    except aiohttp.ClientError as exc:
                        self.logger.debug("Yahoo v8 connection error (%s): %s", url, exc)

        except Exception as exc:
            self.logger.error("Yahoo v8 неожиданная ошибка: %s", exc, exc_info=True)

        self.record_failure()
        return FetchResult(success=False, error="Yahoo v8: все попытки не удались")
