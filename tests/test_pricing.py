from datetime import UTC, datetime
import importlib
from types import SimpleNamespace
import unittest

from test_plugin import package

pricing = importlib.import_module(package + ".pricing")
USAGE = {"input_other": 1000, "input_cached": 100, "output": 50}
PEAK = datetime(2026, 11, 19, 1, tzinfo=UTC)


class PricingTests(unittest.TestCase):
    def test_exact_provider_and_model_and_override(self):
        result = pricing.estimate("https://api.openai.com/v1", "gpt-5.4-mini", USAGE, PEAK)
        self.assertEqual(result["amount"], "0.0009825")
        self.assertIsNone(pricing.estimate("https://proxy.example", "gpt-5.4-mini", USAGE, PEAK))
        override = {"input": "1.5", "cached_input": "0.1", "output": "2", "currency": "CNY"}
        result = pricing.estimate("https://proxy.example", "custom", USAGE, PEAK, override)
        self.assertEqual((result["amount"], result["currency"]), ("0.00161", "CNY"))

    def test_deepseek_schedule_and_holidays(self):
        dates = [
            (2026, 11, 19, 1, "peak"),
            (2026, 11, 19, 4, "off-peak"),
            (2026, 11, 21, 1, "off-peak"),
            (2026, 10, 1, 1, "off-peak"),
            (2027, 2, 5, 1, "off-peak"),
        ]
        for year, month, day, hour, tier in dates:
            with self.subTest(tier=tier, day=day):
                result = pricing.estimate("deepseek", "deepseek-flash", USAGE,
                                          datetime(year, month, day, hour, tzinfo=UTC))
                self.assertEqual(result["tier"], tier)

    def test_cache_write_replaces_input_rate(self):
        usage = dict(USAGE, cache_write_5m=400, cache_write_1h=200)
        result = pricing.estimate("anthropic", "claude-haiku-5-5", usage, PEAK)
        self.assertEqual(result["amount"], "0.000156")
        self.assertIsNone(pricing.estimate("anthropic", "claude-haiku-5-5",
                                           dict(USAGE, cache_write_unknown=600), PEAK))

    def test_long_context_boundary(self):
        for size, tier in ((199999, "standard"), (200000, "long-context")):
            usage = dict(USAGE, input_other=size - USAGE["input_cached"])
            self.assertEqual(pricing.estimate("xai", "grok-4.7", usage, PEAK)["tier"], tier)

    def test_extracts_deepseek_cache_breakdown(self):
        raw = SimpleNamespace(usage=SimpleNamespace(
            prompt_cache_miss_tokens=1000, prompt_cache_hit_tokens=100, completion_tokens=50))
        response = SimpleNamespace(usage=None, raw_completion=raw)
        self.assertEqual(pricing.extract_usage(response, "deepseek"), USAGE)

    def test_google_output_includes_billed_thinking_tokens(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(**USAGE),
            raw_completion=SimpleNamespace(usage_metadata=SimpleNamespace(thoughts_token_count=43)),
        )
        self.assertEqual(pricing.extract_usage(response, "google")["output"], 93)

    def test_missing_usage_stays_unknown(self):
        response = SimpleNamespace(usage=SimpleNamespace(input_other=0, input_cached=0, output=0))
        self.assertIsNone(pricing.extract_usage(response, "openai"))
