"""Base classes for all multi-source price fetchers."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PriceData:
    """Standardized price data returned by any fetcher."""

    price: float
    source: str
    timestamp: datetime
    unit: str
    confidence: float = 1.0    # 0.0–1.0
    is_estimated: bool = False
    is_stale: bool = False

    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[int] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None

    metadata: dict = field(default_factory=dict)

    def age_minutes(self) -> float:
        return (datetime.utcnow() - self.timestamp).total_seconds() / 60

    def is_fresh(self, max_age_minutes: int = 60) -> bool:
        return self.age_minutes() < max_age_minutes


@dataclass
class FetchResult:
    """Outcome of a single fetch attempt."""

    success: bool
    data: Optional[PriceData] = None
    error: Optional[str] = None
    fetch_time_ms: float = 0.0


class BaseFetcher(ABC):
    """Abstract base for all data source fetchers."""

    def __init__(
        self,
        name: str,
        priority: int,
        cache_ttl: int = 300,
        timeout: int = 10,
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.priority = priority
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.enabled = enabled
        self.logger = logging.getLogger(f"multisource.{name}")

        self.success_count: int = 0
        self.failure_count: int = 0
        self.last_success: Optional[datetime] = None
        self.last_failure: Optional[datetime] = None

    @abstractmethod
    async def fetch(self) -> FetchResult:
        """Fetch data from this source."""

    def calculate_confidence(self, data: PriceData) -> float:
        """Weighted confidence: decays with data age and historical failure rate."""
        base = 1.0

        age = data.age_minutes()
        if age > 1440:
            base *= 0.5
        elif age > 60:
            base *= 0.8

        total = self.success_count + self.failure_count
        if total > 0:
            base *= self.success_count / total

        return min(base, 1.0)

    def record_success(self) -> None:
        self.success_count += 1
        self.last_success = datetime.utcnow()

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure = datetime.utcnow()

    def get_stats(self) -> dict:
        total = self.success_count + self.failure_count
        return {
            "name": self.name,
            "priority": self.priority,
            "enabled": self.enabled,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_count / total if total > 0 else 0.0,
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
        }
