"""Price aggregator — parallel fetch + weighted consensus with outlier removal."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData

logger = logging.getLogger(__name__)


@dataclass
class ConsensusResult:
    """Consensus price calculated from multiple sources."""

    consensus_price: float
    confidence: float
    sources_used: int
    total_sources: int
    price_data_list: List[PriceData]
    failed_sources: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def success_rate(self) -> float:
        if self.total_sources == 0:
            return 0.0
        return self.sources_used / self.total_sources


class PriceAggregator:
    """Fetch from all enabled sources in parallel, then compute consensus."""

    def __init__(self, fetchers: List[BaseFetcher]) -> None:
        self.fetchers = sorted(fetchers, key=lambda f: f.priority)

    async def fetch_all(self, timeout: float = 25.0) -> ConsensusResult:
        """Run all enabled fetchers concurrently and return consensus."""
        enabled = [f for f in self.fetchers if f.enabled]

        if not enabled:
            raise ValueError("Нет активных источников данных")

        logger.info(
            "Параллельная загрузка из %d источников (timeout=%.0fs)...",
            len(enabled),
            timeout,
        )

        tasks = [f.fetch() for f in enabled]
        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Общий timeout (%.0fs) истёк — используем частичные результаты", timeout)
            raw_results = []

        successful: List[PriceData] = []
        failed: List[str] = []

        for fetcher, result in zip(enabled, raw_results):
            if isinstance(result, Exception):
                failed.append(f"{fetcher.name} (исключение: {result})")
                logger.error(
                    "Fetcher %s выбросил исключение: %s", fetcher.name, result
                )
            elif isinstance(result, FetchResult):
                if result.success and result.data:
                    successful.append(result.data)
                    logger.info(
                        "✅ %s: %.2f %s (%.0fms)",
                        fetcher.name,
                        result.data.price,
                        result.data.unit,
                        result.fetch_time_ms,
                    )
                else:
                    failed.append(f"{fetcher.name} ({result.error or 'неизвестная ошибка'})")
                    logger.warning("❌ %s: %s", fetcher.name, result.error)
            else:
                failed.append(f"{fetcher.name} (нет ответа)")

        if not successful:
            raise ValueError(
                f"Все {len(enabled)} источников не ответили: {', '.join(failed[:3])}"
            )

        consensus = self._calculate_consensus(successful)

        logger.info(
            "Консенсус: %.2f (ishonch=%.0f%%, источников=%d/%d)",
            consensus["price"],
            consensus["confidence"] * 100,
            len(successful),
            len(enabled),
        )

        return ConsensusResult(
            consensus_price=consensus["price"],
            confidence=consensus["confidence"],
            sources_used=len(successful),
            total_sources=len(enabled),
            price_data_list=successful,
            failed_sources=failed,
        )

    def _calculate_consensus(self, price_data_list: List[PriceData]) -> dict:
        """Weighted average by confidence score, with optional outlier removal."""
        if not price_data_list:
            raise ValueError("Пустой список цен для консенсуса")

        # Remove outliers when we have ≥3 sources
        working_list = price_data_list
        if len(price_data_list) >= 3:
            filtered = self._remove_outliers(price_data_list)
            if len(filtered) >= 2:
                working_list = filtered

        total_weight = sum(pd.confidence for pd in working_list)
        if total_weight == 0:
            # Equal weight fallback
            consensus_price = sum(pd.price for pd in working_list) / len(working_list)
            return {"price": round(consensus_price, 2), "confidence": 0.5}

        weighted_price = (
            sum(pd.price * pd.confidence for pd in working_list) / total_weight
        )

        # Penalise high spread
        prices = [pd.price for pd in working_list]
        avg = sum(prices) / len(prices)
        max_deviation_pct = max(abs(p - avg) / avg * 100 for p in prices)

        avg_confidence = sum(pd.confidence for pd in working_list) / len(working_list)
        if max_deviation_pct > 5.0:
            logger.warning(
                "Высокая девиация цен: %.1f%% — снижаем уверенность", max_deviation_pct
            )
            avg_confidence *= 0.7

        return {
            "price": round(weighted_price, 2),
            "confidence": min(avg_confidence, 1.0),
            "deviation_pct": round(max_deviation_pct, 2),
        }

    @staticmethod
    def _remove_outliers(price_data_list: List[PriceData]) -> List[PriceData]:
        """IQR-based outlier removal."""
        prices = sorted(pd.price for pd in price_data_list)
        n = len(prices)

        q1 = prices[n // 4]
        q3 = prices[(3 * n) // 4]
        iqr = q3 - q1

        if iqr == 0:
            return price_data_list

        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        filtered = [pd for pd in price_data_list if lower <= pd.price <= upper]

        removed = [pd.source for pd in price_data_list if pd not in filtered]
        if removed:
            logger.info("Удалены выбросы: %s", removed)

        return filtered if len(filtered) >= 2 else price_data_list
