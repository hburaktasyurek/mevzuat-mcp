import asyncio
import unittest

from bedesten_request_guard import BedestenRequestGuard


class BedestenRequestGuardTests(unittest.TestCase):
    def test_get_or_load_returns_cached_value_without_calling_loader_again(self):
        calls = 0

        async def loader():
            nonlocal calls
            calls += 1
            return {"ok": calls}

        async def scenario():
            guard = BedestenRequestGuard(enable_cache=True, redis_client=None)
            first = await guard.get_or_load("search:one", loader)
            second = await guard.get_or_load("search:one", loader)
            return first, second

        first, second = asyncio.run(scenario())

        self.assertEqual(first, {"ok": 1})
        self.assertEqual(second, {"ok": 1})
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
