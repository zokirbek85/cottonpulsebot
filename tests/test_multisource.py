"""Unit and integration tests for the multi-source price aggregation system."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

from bot.services.multisource.base import BaseFetcher, FetchResult, PriceData
from bot.services.multisource.aggregator import PriceAggregator, ConsensusResult


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_price(price: float, source: str = "Test", confidence: float = 1.0) -> PriceData:
    return PriceData(
        price=price,
        source=source,
        timestamp=datetime.utcnow(),
        unit="c/lb",
        confidence=confidence,
    )


class MockFetcher(BaseFetcher):
    """Deterministic fetcher for tests."""

    def __init__(
        self,
        name: str,
        price: Optional[float],
        priority: int = 1,
        delay: float = 0.0,
    ) -> None:
        super().__init__(name=name, priority=priority, enabled=True)
        self._price = price
        self._delay = delay

    async def fetch(self) -> FetchResult:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._price is None:
            return FetchResult(success=False, error="Simulated failure")
        data = make_price(self._price, self.name)
        return FetchResult(success=True, data=data, fetch_time_ms=self._delay * 1000)


# ── PriceData tests ────────────────────────────────────────────────────────────

class TestPriceData:
    def test_age_minutes_recent(self):
        pd = make_price(75.0)
        assert pd.age_minutes() < 0.1

    def test_age_minutes_old(self):
        pd = PriceData(
            price=75.0,
            source="X",
            timestamp=datetime.utcnow() - timedelta(hours=2),
            unit="c/lb",
        )
        assert 119 < pd.age_minutes() < 121

    def test_is_fresh_defaults_true(self):
        pd = make_price(75.0)
        assert pd.is_fresh(max_age_minutes=60) is True

    def test_is_fresh_old_data(self):
        pd = PriceData(
            price=75.0,
            source="X",
            timestamp=datetime.utcnow() - timedelta(hours=2),
            unit="c/lb",
        )
        assert pd.is_fresh(max_age_minutes=60) is False

    def test_defaults(self):
        pd = make_price(80.0)
        assert pd.confidence == 1.0
        assert pd.is_estimated is False
        assert pd.is_stale is False
        assert pd.metadata == {}


# ── BaseFetcher tests ──────────────────────────────────────────────────────────

class TestBaseFetcher:
    def test_stats_empty(self):
        f = MockFetcher("A", 75.0)
        stats = f.get_stats()
        assert stats["success_count"] == 0
        assert stats["failure_count"] == 0
        assert stats["success_rate"] == 0.0

    def test_record_success_updates_stats(self):
        f = MockFetcher("A", 75.0)
        f.record_success()
        f.record_success()
        f.record_failure()
        stats = f.get_stats()
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 1
        assert abs(stats["success_rate"] - 2 / 3) < 0.001

    def test_calculate_confidence_recent(self):
        f = MockFetcher("A", 75.0)
        pd = make_price(75.0)
        # No history → confidence not reduced by reliability
        conf = f.calculate_confidence(pd)
        assert conf == 1.0

    def test_calculate_confidence_old_data(self):
        f = MockFetcher("A", 75.0)
        pd = PriceData(
            price=75.0,
            source="A",
            timestamp=datetime.utcnow() - timedelta(hours=2),
            unit="c/lb",
        )
        conf = f.calculate_confidence(pd)
        assert conf < 1.0

    def test_calculate_confidence_after_failures(self):
        f = MockFetcher("A", 75.0)
        f.record_success()
        f.record_failure()
        f.record_failure()
        f.record_failure()
        pd = make_price(75.0)
        conf = f.calculate_confidence(pd)
        assert conf < 1.0


# ── PriceAggregator unit tests ─────────────────────────────────────────────────

class TestAggregatorConsensus:
    def _agg(self) -> PriceAggregator:
        return PriceAggregator([])

    def test_weighted_average_equal_confidence(self):
        agg = self._agg()
        prices = [make_price(74.0), make_price(76.0), make_price(75.0)]
        result = agg._calculate_consensus(prices)
        assert abs(result["price"] - 75.0) < 0.01

    def test_weighted_average_higher_confidence_wins(self):
        agg = self._agg()
        prices = [
            make_price(74.0, confidence=1.0),
            make_price(80.0, confidence=0.1),  # outlier with low confidence
        ]
        result = agg._calculate_consensus(prices)
        # Should be closer to 74 than 80
        assert result["price"] < 76.0

    def test_single_source(self):
        agg = self._agg()
        result = agg._calculate_consensus([make_price(77.5)])
        assert result["price"] == 77.5

    def test_empty_raises(self):
        agg = self._agg()
        with pytest.raises(ValueError):
            agg._calculate_consensus([])

    def test_high_deviation_penalises_confidence(self):
        agg = self._agg()
        prices = [make_price(60.0), make_price(90.0)]  # 40% spread
        result = agg._calculate_consensus(prices)
        assert result["confidence"] < 1.0


class TestAggregatorOutlierRemoval:
    def _agg(self) -> PriceAggregator:
        return PriceAggregator([])

    def test_removes_high_outlier(self):
        agg = self._agg()
        prices = [
            make_price(75.0, "S1"),
            make_price(76.0, "S2"),
            make_price(75.5, "S3"),
            make_price(120.0, "Outlier"),
        ]
        filtered = agg._remove_outliers(prices)
        sources = [pd.source for pd in filtered]
        assert "Outlier" not in sources
        assert len(filtered) == 3

    def test_removes_low_outlier(self):
        agg = self._agg()
        prices = [
            make_price(75.0, "S1"),
            make_price(76.0, "S2"),
            make_price(75.5, "S3"),
            make_price(30.0, "Outlier"),
        ]
        filtered = agg._remove_outliers(prices)
        sources = [pd.source for pd in filtered]
        assert "Outlier" not in sources

    def test_no_outliers_unchanged(self):
        agg = self._agg()
        prices = [make_price(74.0), make_price(75.0), make_price(76.0)]
        filtered = agg._remove_outliers(prices)
        assert len(filtered) == 3

    def test_too_few_sources_returns_original(self):
        agg = self._agg()
        prices = [make_price(74.0, "A"), make_price(74.0, "B")]
        filtered = agg._remove_outliers(prices)
        assert filtered == prices

    def test_all_outliers_returns_original(self):
        """When IQR filtering would empty the list, original is returned."""
        agg = self._agg()
        prices = [make_price(74.0, "A"), make_price(120.0, "B"), make_price(30.0, "C")]
        filtered = agg._remove_outliers(prices)
        assert len(filtered) >= 2


# ── PriceAggregator async integration tests ────────────────────────────────────

class TestAggregatorFetchAll:
    @pytest.mark.asyncio
    async def test_all_succeed(self):
        fetchers = [
            MockFetcher("S1", 75.0, priority=1),
            MockFetcher("S2", 76.0, priority=2),
            MockFetcher("S3", 75.5, priority=3),
        ]
        agg = PriceAggregator(fetchers)
        result = await agg.fetch_all(timeout=5.0)

        assert isinstance(result, ConsensusResult)
        assert result.sources_used == 3
        assert result.total_sources == 3
        assert 74.5 < result.consensus_price < 76.5
        assert result.failed_sources == []

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        fetchers = [
            MockFetcher("Good1", 75.0, priority=1),
            MockFetcher("Bad", None, priority=2),
            MockFetcher("Good2", 76.0, priority=3),
        ]
        agg = PriceAggregator(fetchers)
        result = await agg.fetch_all(timeout=5.0)

        assert result.sources_used == 2
        assert result.total_sources == 3
        assert len(result.failed_sources) == 1
        assert "Bad" in result.failed_sources[0]

    @pytest.mark.asyncio
    async def test_all_fail_raises(self):
        fetchers = [
            MockFetcher("Bad1", None, priority=1),
            MockFetcher("Bad2", None, priority=2),
        ]
        agg = PriceAggregator(fetchers)
        with pytest.raises(ValueError, match="источников"):
            await agg.fetch_all(timeout=5.0)

    @pytest.mark.asyncio
    async def test_disabled_fetchers_skipped(self):
        fetchers = [
            MockFetcher("Active", 75.0, priority=1),
            MockFetcher("Disabled", 999.0, priority=2),
        ]
        fetchers[1].enabled = False

        agg = PriceAggregator(fetchers)
        result = await agg.fetch_all(timeout=5.0)

        assert result.sources_used == 1
        assert result.total_sources == 1
        assert result.consensus_price == 75.0

    @pytest.mark.asyncio
    async def test_no_enabled_fetchers_raises(self):
        fetchers = [MockFetcher("A", 75.0)]
        fetchers[0].enabled = False

        agg = PriceAggregator(fetchers)
        with pytest.raises(ValueError, match="активных"):
            await agg.fetch_all(timeout=5.0)

    @pytest.mark.asyncio
    async def test_consensus_result_fields(self):
        fetchers = [MockFetcher("S1", 75.0), MockFetcher("S2", 76.0)]
        agg = PriceAggregator(fetchers)
        result = await agg.fetch_all(timeout=5.0)

        assert 0 < result.confidence <= 1.0
        assert len(result.price_data_list) == 2
        assert isinstance(result.timestamp, datetime)
        assert result.success_rate() == 1.0


# ── Individual fetcher smoke tests (no network) ────────────────────────────────

class TestCottonFetchersNoKey:
    """Fetchers that require API keys should fail gracefully when no key is set."""

    @pytest.mark.asyncio
    async def test_quandl_no_key(self):
        with patch("bot.services.multisource.cotton.quandl._get_api_key", return_value=None):
            from bot.services.multisource.cotton.quandl import QuandlCottonFetcher
            f = QuandlCottonFetcher()
            f.enabled = True  # force-enable despite missing key
            result = await f.fetch()
        assert result.success is False
        assert "QUANDL_API_KEY" in (result.error or "")

    @pytest.mark.asyncio
    async def test_usda_no_key(self):
        with patch("bot.services.multisource.cotton.usda._get_api_key", return_value=None):
            from bot.services.multisource.cotton.usda import USDACottonFetcher
            f = USDACottonFetcher()
            f.enabled = True
            result = await f.fetch()
        assert result.success is False
        assert "USDA_API_KEY" in (result.error or "")

    @pytest.mark.asyncio
    async def test_fred_no_key(self):
        with patch("bot.services.multisource.cotton.fred._get_api_key", return_value=None):
            from bot.services.multisource.cotton.fred import FREDCottonFetcher
            f = FREDCottonFetcher()
            f.enabled = True
            result = await f.fetch()
        assert result.success is False
        assert "FRED_API_KEY" in (result.error or "")


# ── Converter sanity checks ────────────────────────────────────────────────────

class TestConverters:
    def test_cents_lb_to_usd_kg(self):
        from bot.utils.converters import cents_per_lb_to_usd_per_kg
        # 100 c/lb = 1 USD/lb = 2.20462 USD/kg
        result = cents_per_lb_to_usd_per_kg(100.0)
        assert abs(result - 2.20462) < 0.001

    def test_cents_lb_to_usd_kg_typical(self):
        from bot.utils.converters import cents_per_lb_to_usd_per_kg
        # 77 c/lb ≈ 1.698 USD/kg
        result = cents_per_lb_to_usd_per_kg(77.0)
        assert 1.69 < result < 1.71
