import unittest
from unittest.mock import patch

from app.services.resource_probe import probe_resource_availability


class MemoryCache:
    value = None

    def __init__(self, namespace):
        self.namespace = namespace

    def get(self, key, ttl_seconds):
        return type(self).value

    def set(self, key, value):
        type(self).value = value


class ResourceProbeCacheTests(unittest.TestCase):
    def setUp(self):
        MemoryCache.value = None

    @patch("app.services.resource_probe.FileCache", MemoryCache)
    @patch("app.services.resource_probe._probe_resource_availability")
    def test_reuses_recent_probe_result(self, probe):
        probe.return_value = {"ok": True, "found": True, "message": "found"}

        first = probe_resource_availability(123, "tv", 2)
        second = probe_resource_availability(123, "tv", 2)

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(1, probe.call_count)

    @patch("app.services.resource_probe.FileCache", MemoryCache)
    @patch("app.services.resource_probe._probe_resource_availability")
    def test_refresh_bypasses_cached_result(self, probe):
        MemoryCache.value = {"ok": True, "found": True, "message": "old"}
        probe.return_value = {"ok": True, "found": False, "message": "fresh"}

        result = probe_resource_availability(123, "tv", 2, refresh=True)

        self.assertFalse(result["cached"])
        self.assertFalse(result["found"])
        self.assertEqual(1, probe.call_count)

    @patch("app.services.resource_probe.FileCache", MemoryCache)
    @patch("app.services.resource_probe._probe_resource_availability")
    def test_slow_negative_probe_cannot_replace_concurrent_positive_result(self, probe):
        def finish_after_positive(*args, **kwargs):
            MemoryCache.value = {"ok": True, "found": True, "message": "verified"}
            return {"ok": True, "found": False, "message": "stale negative"}

        probe.side_effect = finish_after_positive

        result = probe_resource_availability(123, "tv", 1)

        self.assertTrue(result["found"])
        self.assertEqual("verified", result["message"])
        self.assertTrue(MemoryCache.value["found"])


if __name__ == "__main__":
    unittest.main()
