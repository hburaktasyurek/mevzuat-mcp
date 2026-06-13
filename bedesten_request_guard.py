"""
Request guard for Bedesten API calls.

Keeps cache/throttle behavior outside BedestenClient so the client methods can
stay focused on API payloads and response parsing.
"""
import asyncio
import json
import logging
import pickle
import time
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


def make_cache_key(namespace: str, payload: dict[str, Any]) -> str:
    """Build a stable cache key for equivalent Bedesten request payloads."""
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{namespace}:{encoded}"


class BedestenRequestGuard:
    """Small async cache facade; Redis/throttle support can be layered onto this."""

    def __init__(
        self,
        *,
        enable_cache: bool = True,
        cache_ttl: int = 3600,
        redis_client: Optional[Any] = None,
        max_concurrency: int = 2,
        min_request_interval: float = 0.0,
    ):
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        self.redis_client = redis_client
        self._memory_cache: dict[str, tuple[float, Any]] = {}
        self._inflight: dict[str, asyncio.Task] = {}
        self._inflight_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._min_request_interval = max(0.0, min_request_interval)
        self._last_request_started_at = 0.0

    def _get_memory(self, key: str) -> Optional[Any]:
        if not self.enable_cache:
            return None
        cached = self._memory_cache.get(key)
        if not cached:
            return None
        ts, value = cached
        if time.time() - ts >= self.cache_ttl:
            del self._memory_cache[key]
            return None
        return value

    def _put_memory(self, key: str, value: Any) -> None:
        if self.enable_cache:
            self._memory_cache[key] = (time.time(), value)

    async def _get_cached(self, key: str) -> Optional[Any]:
        cached = self._get_memory(key)
        if cached is not None:
            return cached
        if not self.enable_cache or self.redis_client is None:
            return None
        try:
            raw = await self.redis_client.get(key)
            if raw is None:
                return None
            value = pickle.loads(raw)
            self._put_memory(key, value)
            return value
        except Exception:
            logger.warning("Bedesten Redis cache get failed", exc_info=True)
            return None

    async def _put_cached(self, key: str, value: Any) -> None:
        self._put_memory(key, value)
        if not self.enable_cache or self.redis_client is None:
            return
        try:
            await self.redis_client.set(key, pickle.dumps(value), ex=self.cache_ttl)
        except Exception:
            logger.warning("Bedesten Redis cache set failed", exc_info=True)

    async def get_or_load(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        should_cache: Optional[Callable[[Any], bool]] = None,
    ) -> Any:
        cached = await self._get_cached(key)
        if cached is not None:
            return cached

        async with self._inflight_lock:
            task = self._inflight.get(key)
            is_owner = False
            if task is None:
                task = asyncio.create_task(self._run_limited(loader))
                self._inflight[key] = task
                is_owner = True

        try:
            value = await task
            cache_allowed = should_cache(value) if should_cache else True
            if is_owner and cache_allowed:
                await self._put_cached(key, value)
            return value
        finally:
            if is_owner:
                async with self._inflight_lock:
                    if self._inflight.get(key) is task:
                        del self._inflight[key]

    async def _run_limited(self, loader: Callable[[], Awaitable[Any]]) -> Any:
        async with self._semaphore:
            if self._min_request_interval:
                now = time.monotonic()
                wait_for = self._min_request_interval - (now - self._last_request_started_at)
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
            self._last_request_started_at = time.monotonic()
            return await loader()
