import asyncio
import os
import sys
import time
import types
import unittest


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class FakeAsyncClient:
    post_calls = 0
    delay_seconds = 0
    active_posts = 0
    max_active_posts = 0
    post_start_times = []
    response_body = {
        "metadata": {"FMTY": "SUCCESS"},
        "data": {
            "total": 1,
            "start": 0,
            "mevzuatList": [
                {
                    "mevzuatId": "1",
                    "mevzuatNo": "100",
                    "mevzuatAdi": "TEST YONETMELIGI",
                    "mevzuatTur": {"name": "KKY", "description": "Kurum ve Kuruluş Yönetmelikleri"},
                }
            ],
        },
    }

    def __init__(self, *args, **kwargs):
        pass

    async def post(self, path, json):
        self.__class__.post_calls += 1
        self.__class__.post_start_times.append(time.monotonic())
        self.__class__.active_posts += 1
        self.__class__.max_active_posts = max(self.__class__.max_active_posts, self.__class__.active_posts)
        try:
            if self.__class__.delay_seconds:
                await asyncio.sleep(self.__class__.delay_seconds)
            return FakeResponse(self.__class__.response_body)
        finally:
            self.__class__.active_posts -= 1

    async def aclose(self):
        pass


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        return True


class FakeRedisFactory:
    shared = FakeRedis()

    @classmethod
    def from_url(cls, url, decode_responses=False):
        return cls.shared


fake_httpx = types.ModuleType("httpx")
fake_httpx.AsyncClient = FakeAsyncClient
sys.modules.setdefault("httpx", fake_httpx)

fake_redis = types.ModuleType("redis")
fake_redis_asyncio = types.ModuleType("redis.asyncio")
fake_redis_asyncio.from_url = FakeRedisFactory.from_url
fake_redis.asyncio = fake_redis_asyncio
sys.modules.setdefault("redis", fake_redis)
sys.modules.setdefault("redis.asyncio", fake_redis_asyncio)

from bedesten_client import BedestenClient


class BedestenClientCacheTests(unittest.TestCase):
    def setUp(self):
        FakeAsyncClient.post_calls = 0
        FakeAsyncClient.delay_seconds = 0
        FakeAsyncClient.active_posts = 0
        FakeAsyncClient.max_active_posts = 0
        FakeAsyncClient.post_start_times = []
        FakeRedisFactory.shared = FakeRedis()
        os.environ.pop("BEDESTEN_REDIS_URL", None)
        os.environ.pop("REDIS_URL", None)

    def test_search_documents_caches_repeated_identical_query(self):
        async def scenario():
            client = BedestenClient(cache_ttl=3600, enable_cache=True, min_request_interval=0)
            first = await client.search_documents(mevzuat_adi="sivil havacilik")
            second = await client.search_documents(mevzuat_adi="sivil havacilik")
            return first, second

        first, second = asyncio.run(scenario())

        self.assertEqual(FakeAsyncClient.post_calls, 1)
        self.assertEqual(first.total_results, 1)
        self.assertEqual(second.total_results, 1)

    def test_search_documents_uses_redis_url_from_environment(self):
        async def scenario():
            os.environ["BEDESTEN_REDIS_URL"] = "redis://localhost:6379/0"
            first_client = BedestenClient(cache_ttl=3600, enable_cache=True, min_request_interval=0)
            second_client = BedestenClient(cache_ttl=3600, enable_cache=True, min_request_interval=0)
            first = await first_client.search_documents(mevzuat_adi="sivil havacilik")
            second = await second_client.search_documents(mevzuat_adi="sivil havacilik")
            return first, second

        first, second = asyncio.run(scenario())

        self.assertEqual(FakeAsyncClient.post_calls, 1)
        self.assertEqual(first.total_results, 1)
        self.assertEqual(second.total_results, 1)

    def test_search_documents_limits_concurrent_distinct_queries(self):
        async def scenario():
            FakeAsyncClient.delay_seconds = 0.01
            client = BedestenClient(cache_ttl=3600, enable_cache=True, max_concurrency=1, min_request_interval=0)
            first, second = await asyncio.gather(
                client.search_documents(mevzuat_adi="sivil havacilik"),
                client.search_documents(mevzuat_adi="ticaret"),
            )
            return first, second

        first, second = asyncio.run(scenario())

        self.assertEqual(FakeAsyncClient.post_calls, 2)
        self.assertEqual(FakeAsyncClient.max_active_posts, 1)
        self.assertEqual(first.total_results, 1)
        self.assertEqual(second.total_results, 1)

    def test_search_documents_respects_min_request_interval_for_distinct_queries(self):
        async def scenario():
            client = BedestenClient(
                cache_ttl=3600,
                enable_cache=True,
                max_concurrency=1,
                min_request_interval=0.02,
            )
            await asyncio.gather(
                client.search_documents(mevzuat_adi="sivil havacilik"),
                client.search_documents(mevzuat_adi="ticaret"),
            )

        asyncio.run(scenario())

        self.assertEqual(FakeAsyncClient.post_calls, 2)
        self.assertGreaterEqual(FakeAsyncClient.post_start_times[1] - FakeAsyncClient.post_start_times[0], 0.018)

    def test_search_documents_can_share_cache_through_redis_client(self):
        async def scenario():
            redis = FakeRedis()
            first_client = BedestenClient(cache_ttl=3600, enable_cache=True, redis_client=redis, min_request_interval=0)
            second_client = BedestenClient(cache_ttl=3600, enable_cache=True, redis_client=redis, min_request_interval=0)
            first = await first_client.search_documents(mevzuat_adi="sivil havacilik")
            second = await second_client.search_documents(mevzuat_adi="sivil havacilik")
            return first, second

        first, second = asyncio.run(scenario())

        self.assertEqual(FakeAsyncClient.post_calls, 1)
        self.assertEqual(first.total_results, 1)
        self.assertEqual(second.total_results, 1)
        self.assertEqual(second.documents[0].mevzuat_adi, "TEST YONETMELIGI")

    def test_search_documents_deduplicates_concurrent_identical_query(self):
        async def scenario():
            FakeAsyncClient.delay_seconds = 0.01
            client = BedestenClient(cache_ttl=3600, enable_cache=True, min_request_interval=0)
            first, second = await asyncio.gather(
                client.search_documents(mevzuat_adi="sivil havacilik"),
                client.search_documents(mevzuat_adi="sivil havacilik"),
            )
            return first, second

        first, second = asyncio.run(scenario())

        self.assertEqual(FakeAsyncClient.post_calls, 1)
        self.assertEqual(first.total_results, 1)
        self.assertEqual(second.total_results, 1)

    def test_search_documents_does_not_cache_upstream_errors(self):
        async def scenario():
            FakeAsyncClient.response_body = {
                "metadata": {"FMTY": "ERROR", "FMTE": "rate limited"},
                "data": {},
            }
            client = BedestenClient(cache_ttl=3600, enable_cache=True, min_request_interval=0)
            first = await client.search_documents(mevzuat_adi="sivil havacilik")
            second = await client.search_documents(mevzuat_adi="sivil havacilik")
            return first, second

        try:
            first, second = asyncio.run(scenario())
        finally:
            FakeAsyncClient.response_body = {
                "metadata": {"FMTY": "SUCCESS"},
                "data": {
                    "total": 1,
                    "start": 0,
                    "mevzuatList": [
                        {
                            "mevzuatId": "1",
                            "mevzuatNo": "100",
                            "mevzuatAdi": "TEST YONETMELIGI",
                            "mevzuatTur": {"name": "KKY", "description": "Kurum ve Kuruluş Yönetmelikleri"},
                        }
                    ],
                },
            }

        self.assertEqual(FakeAsyncClient.post_calls, 2)
        self.assertEqual(first.error_message, "rate limited")
        self.assertEqual(second.error_message, "rate limited")


if __name__ == "__main__":
    unittest.main()
