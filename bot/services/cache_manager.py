"""Async TTL cache — no external dependencies."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine, Optional


class TTLCache:
    """Thread-safe (asyncio) TTL cache with per-key expiry."""

    def __init__(self, default_ttl: int = 300) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        async with self._lock:
            expire = time.monotonic() + (ttl if ttl is not None else self.default_ttl)
            self._store[key] = (value, expire)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Coroutine[Any, Any, Optional[Any]]],
        ttl: Optional[int] = None,
    ) -> Optional[Any]:
        cached = await self.get(key)
        if cached is not None:
            return cached
        result = await fetcher()
        if result is not None:
            await self.set(key, result, ttl=ttl)
        return result

    async def invalidate_all(self) -> None:
        async with self._lock:
            self._store.clear()

    async def size(self) -> int:
        async with self._lock:
            now = time.monotonic()
            live = [(k, v) for k, v in self._store.items() if v[1] > now]
            self._store = dict(live)
            return len(self._store)


# Shared global cache instance
cache = TTLCache(default_ttl=300)
