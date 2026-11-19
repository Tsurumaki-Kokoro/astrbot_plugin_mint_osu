import importlib
import unittest
from unittest.mock import patch

from test_plugin import package


class UsageStatsTests(unittest.TestCase):
    def test_expired_answers_leave_only_aggregates(self):
        module = importlib.import_module(package + ".usage_stats")
        with patch.object(module, "time", return_value=2_000_000_000):
            stats = module.UsageStats(":memory:")
            stats.command(2_000_000_000, "qq", "group", "bp", "technical", 125)
            stats.judgment(2_000_000_000, "qq", "group", "official", "model", "guess", "title", "same", True, 50, None, None)
            self.assertEqual(stats.judgments(7)["items"][0]["answer"], "guess")
            self.assertEqual(stats.summary(7)["commands"][0]["errors"], 1)
        with patch.object(module, "time", return_value=2_000_000_000 + 7 * 86400):
            stats.prune()
            self.assertEqual(stats.judgments(7)["total"], 0)
            self.assertEqual(stats.summary(30)["models"][0]["settled"], 1)
        stats.close()

    def test_group_and_hour_filters_preserve_group_share_denominator(self):
        module = importlib.import_module(package + ".usage_stats")
        timestamp = 2_000_000_000
        with patch.object(module, "time", return_value=timestamp):
            stats = module.UsageStats(":memory:")
            self.addCleanup(stats.close)
            for group in ("one", "two", ""):
                stats.command(timestamp, "qq", group, "bp", "ok", 20)
            self.assertEqual(stats.summary(7, group="__private__")["private_count"], 1)
            moment = module.datetime.fromtimestamp(timestamp, module.LOCAL)
            result = stats.summary(7, "qq", "one", hour=moment.hour, weekday=moment.weekday())
            self.assertEqual(result["groups"][0]["count"], 1)
            self.assertEqual(result["group_total"], 2)
