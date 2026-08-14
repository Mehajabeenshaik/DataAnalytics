"""
TTL-based response cache for the governed agent.

Caches (question, filters) -> response pairs so that repeated questions
skip the LLM entirely. The cache key is a normalized hash of the question
text and filters, so "Total revenue?" and "total revenue" hit the same entry.

No_match responses are NOT cached — they're cheap to recompute and caching
them could hide a legitimately new metric added later.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from cachetools import TTLCache

from config import CACHE_TTL_SECONDS

_CACHE_MAX_SIZE = 500

_cache: TTLCache = TTLCache(maxsize=_CACHE_MAX_SIZE, ttl=CACHE_TTL_SECONDS)


def _normalize_question(question: str) -> str:
    """Normalize a question for cache keying."""
    normalized = re.sub(r"\s+", " ", question.lower().strip())
    normalized = re.sub(r"[?!.,]+$", "", normalized).strip()
    return normalized


def _make_cache_key(
    question: str,
    filters: dict | None,
    dataset_id: str | None = None,
    tenant_id: str | None = None,
) -> str:
    """Create a deterministic cache key from tenant + dataset + question + filters.

    tenant_id is MANDATORY for isolation — two tenants asking the same
    normalized question text must NEVER collide on the same cache entry.
    dataset_id additionally scopes per-DataSource within a tenant.
    """
    normalized = _normalize_question(question)
    filters_str = json.dumps(filters or {}, sort_keys=True)
    raw = f"{tenant_id or ''}|{dataset_id or ''}|{normalized}|{filters_str}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cached_response(
    question: str,
    filters: dict | None = None,
    dataset_id: str | None = None,
    tenant_id: str | None = None,
) -> dict | None:
    """Return a cached response for (tenant, dataset, question, filters), or None."""
    key = _make_cache_key(question, filters, dataset_id, tenant_id)
    cached = _cache.get(key)
    if cached is not None:
        cached = dict(cached)
        cached["cached"] = True
    return cached


def set_cached_response(
    question: str,
    filters: dict | None,
    response: dict,
    dataset_id: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """Store a response in the cache. Skips no_match and already-cached responses."""
    plan_type = response.get("plan", {}).get("plan_type", "")
    if plan_type == "no_match":
        return
    if response.get("cached"):
        return
    key = _make_cache_key(question, filters, dataset_id, tenant_id)
    to_store = {k: v for k, v in response.items() if k != "cached"}
    _cache[key] = to_store


def clear_cache() -> None:
    """Clear all cached responses."""
    _cache.clear()


def cache_info() -> dict:
    """Return cache stats."""
    return {"size": len(_cache), "maxsize": _cache.maxsize, "ttl": _cache.ttl}
