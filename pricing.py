"""Versioned public text inference rates for song-guess judging."""
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

VERSION = "2026-11-19"
SOURCES = {
    "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
    "openai": "https://developers.openai.com/api/docs/pricing",
    "google": "https://aistudio.google.com/docs/pricing",
    "xai": "https://docs.x.ai/developers/pricing",
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing/",
}
HOSTS = {
    "api.anthropic.com": "anthropic",
    "api.openai.com": "openai",
    "generativelanguage.googleapis.com": "google",
    "api.x.ai": "xai",
    "us.api.x.ai": "xai",
    "api.deepseek.com": "deepseek",
}
ALIASES = {
    "openai": {"gpt-5.4-mini-2026-03-17": "gpt-5.4-mini"},
    "anthropic": {"claude-haiku-4-5-20251001": "claude-haiku-4-5"},
    "deepseek": {
        "deepseek-v4-flash": "deepseek-flash",
        "deepseek-v4-flash-vision-exp": "deepseek-flash",
        "deepseek-v4.1-flash-1017": "deepseek-flash",
        "deepseek-v4-pro-0813": "deepseek-v4-pro",
    },
}
TOKEN_FIELDS = ("input_other", "input_cached", "output")
CACHE_FIELDS = ("cache_write_5m", "cache_write_1h", "cache_write_30m", "cache_write_12h")
RATE_FIELDS = ("input", "cached_input", "output")
# Tuple order matches RATE_FIELDS, followed by CACHE_FIELDS if applicable.
CATALOG = {
    "anthropic": {
        "claude-haiku-5-5": (".10", ".01", ".50", ".125", ".20"),
        "claude-haiku-4-5": ("1", ".10", "5", "1.25", "2"),
        "claude-sonnet-5-5": ("2", ".10", "10", "2.50", "4"),
        "claude-sonnet-4-6": ("3", ".30", "15", "3.75", "6"),
        "claude-opus-5-5": ("4", ".20", "20", "5", "8"),
    },
    "openai": {
        "gpt-5.4-mini": (".75", ".075", "4.50"),
        "gpt-6.2-sol": ("2", ".10", "10", None, None, "2.50", "5"),
        "gpt-6.2-astra": ("8", ".40", "40", None, None, "10", "20"),
    },
    "google": {
        "gemini-3.5-flash-lite": (".30", ".03", "2.50"),
        "gemini-3.1-pro-preview": ("2", ".20", "12"),
    },
    "xai": {
        "grok-4.7": ("2", ".50", "6"),
        "grok-4.6": ("2", ".50", "6"),
        "grok-4.5": ("2", ".30", "6"),
    },
    "deepseek": {
        "deepseek-flash": (".30", ".006", "1.20"),
        "deepseek-v4-pro": ("1.32", ".044", "3.96"),
    },
}
LONG_CONTEXT = {
    "claude-haiku-5-5": (100001, ("0.50", ".05", "2.50", ".625", "1")),
    "gpt-6.2-sol": (272001, ("4", ".20", "15", None, None, "5", "10")),
    "gpt-6.2-astra": (272001, ("16", ".80", "60", None, None, "20", "40")),
    "gemini-3.1-pro-preview": (200001, ("4", ".40", "18")),
    "grok-4.7": (200000, ("4", "1", "12")),
    "grok-4.6": (200000, ("4", "1", "12")),
    "grok-4.5": (200000, ("4", ".60", "12")),
}
# State Council General Office holiday schedules: 国办发明电〔2025〕7号 and
# 国办发明电〔2026〕10号. DeepSeek defines weekends as off-peak, including make-up workdays.
CHINA_HOLIDAYS = {
    2026: ((101, 103), (215, 223), (404, 406), (501, 505),
           (619, 621), (925, 927), (1001, 1007)),
    2027: ((101, 103), (205, 213), (403, 405), (501, 505),
           (609, 609), (915, 915), (1001, 1007)),
}
CHINA_TIME = timezone(timedelta(hours=8))


def _host(provider):
    if not isinstance(provider, str) or not provider:
        return ""
    try:
        return (urlsplit(provider if "://" in provider else f"//{provider}").hostname or "").lower()
    except ValueError:
        return ""


def vendor_for(provider):
    host = _host(provider)
    return host if host in SOURCES else HOSTS.get(host)


def _field(obj, name):
    return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)


def _valid_tokens(value):
    return type(value) is int and value >= 0


def extract_usage(response, provider):
    """Read billable token buckets and retain only counters."""
    normalized = _field(response, "usage")
    completion = _field(response, "raw_completion")
    raw = _field(completion, "usage")
    vendor = vendor_for(provider)
    if vendor == "deepseek":
        hit = _field(raw, "prompt_cache_hit_tokens")
        miss = _field(raw, "prompt_cache_miss_tokens")
        output = _field(raw, "completion_tokens")
        if all(_valid_tokens(value) for value in (hit, miss, output)):
            return dict(zip(TOKEN_FIELDS, (miss, hit, output), strict=True))
    values = {name: _field(normalized, name) for name in TOKEN_FIELDS}
    if not all(_valid_tokens(value) for value in values.values()):
        return None
    if not any(values.values()) and raw is None:
        return None
    if vendor == "google":
        thoughts = _field(_field(completion, "usage_metadata"), "thoughts_token_count")
        if _valid_tokens(thoughts):
            values["output"] += thoughts
    if vendor == "anthropic":
        writes = _field(raw, "cache_creation_input_tokens")
        creation = _field(raw, "cache_creation")
        if _valid_tokens(writes) and writes:
            short = _field(creation, "ephemeral_5m_input_tokens") or 0
            long = _field(creation, "ephemeral_1h_input_tokens") or 0
            if all(_valid_tokens(value) for value in (short, long)) and short + long == writes:
                values.update(cache_write_5m=short, cache_write_1h=long)
            else:
                values["cache_write_unknown"] = writes
        elif raw is None and sum(values[key] for key in TOKEN_FIELDS[:2]) >= 512:
            # AstrBot 4.28's native adapter folds cache writes into ordinary input.
            values["cache_breakdown_unknown"] = True
    elif vendor == "openai":
        details = _field(raw, "prompt_tokens_details") or _field(raw, "input_tokens_details")
        writes = _field(details, "cache_write_tokens")
        if _valid_tokens(writes) and writes:
            values["cache_write_unknown"] = writes
    elif vendor == "xai" and _field(completion, "service_tier") == "priority":
        values["priority"] = True
    elif vendor == "deepseek" and not _valid_tokens(_field(raw, "cache_read_input_tokens")):
        # OpenAI-format responses require DeepSeek's vendor-specific cache fields.
        values["cache_breakdown_unknown"] = True
    return values


def _deepseek_tier(timestamp):
    utc = timestamp.astimezone(UTC)
    if utc.weekday() >= 5 or utc.hour not in (1, 2, 3, 6, 7, 8, 9):
        return "off-peak"
    local = utc.astimezone(CHINA_TIME)
    holidays = CHINA_HOLIDAYS.get(local.year)
    if holidays is None:
        return None
    date_code = 100 * local.month + local.day
    return "off-peak" if any(start <= date_code <= end for start, end in holidays) else "peak"


def _standard_rates(provider, vendor, model, total_input, timestamp, usage):
    entry = CATALOG.get(vendor, {}).get(model)
    if entry is None:
        return None, None
    tier = "standard"
    threshold, long_rates = LONG_CONTEXT.get(model, (None, None))
    if threshold is not None and total_input >= threshold:
        entry, tier = long_rates, "long-context"
    factor = Decimal(1)
    if vendor == "deepseek":
        tier = _deepseek_tier(timestamp)
        if tier is None:
            return None, None
        factor = Decimal(".5") if tier == "off-peak" else factor
    if vendor == "xai":
        if _host(provider) == "us.api.x.ai":
            factor *= Decimal("1.1")
            tier += " us"
        if usage.get("priority"):
            factor *= 2
            tier += " priority"
    return {key: Decimal(rate) * factor for key, rate in zip(RATE_FIELDS + CACHE_FIELDS, entry)
            if rate is not None}, tier


def estimate(provider, model, usage, timestamp, overrides=None):
    """Estimate a call using public Standard rates or a supplied instance override."""
    if not isinstance(usage, Mapping) or not all(_valid_tokens(usage.get(k)) for k in TOKEN_FIELDS):
        return None
    if (not isinstance(model, str) or not model or usage.get("cache_write_unknown")
            or usage.get("cache_breakdown_unknown")):
        return None
    cache_writes = {name: usage.get(name, 0) for name in CACHE_FIELDS}
    if not all(_valid_tokens(value) for value in cache_writes.values()):
        return None
    ordinary_input = usage["input_other"] - sum(cache_writes.values())
    if ordinary_input < 0:
        return None
    vendor = vendor_for(provider)
    canonical = model.lower().strip().removeprefix("models/")
    canonical = ALIASES.get(vendor, {}).get(canonical, canonical)
    if overrides is not None:
        if not isinstance(overrides, Mapping):
            return None
        try:
            rates = {key: Decimal(str(overrides[key])) for key in RATE_FIELDS + CACHE_FIELDS
                     if key in overrides}
        except (InvalidOperation, ValueError):
            return None
        currency = str(overrides.get("currency", "USD")).upper()
        if not (currency.isascii() and currency.isalpha() and len(currency) == 3
                and all(key in rates for key in RATE_FIELDS)
                and all(rate.is_finite() and rate >= 0 for rate in rates.values())):
            return None
        tier, source, version = "custom", "custom", "custom"
    else:
        if not isinstance(timestamp, datetime):
            try:
                timestamp = datetime.fromtimestamp(timestamp, UTC)
            except (OSError, OverflowError, TypeError, ValueError):
                return None
        if timestamp.tzinfo is None:
            return None
        rates, tier = _standard_rates(provider, vendor, canonical,
                                      usage["input_other"] + usage["input_cached"], timestamp, usage)
        if rates is None:
            return None
        currency, source, version = "USD", SOURCES[vendor], VERSION
    counts = {"input": ordinary_input, "cached_input": usage["input_cached"],
              "output": usage["output"], **cache_writes}
    if any(count and key not in rates for key, count in counts.items()):
        return None
    amount = sum(counts[key] * rate for key, rate in rates.items()) / Decimal(1_000_000)
    return {
        "amount": format(amount.normalize(), "f"),
        "currency": currency,
        "version": version,
        "source": source,
        "model": canonical,
        "tier": tier,
        "rates": {key: format(rate.normalize(), "f") for key, rate in rates.items()},
    }
