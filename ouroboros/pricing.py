"""
Ouroboros — LLM pricing and cost estimation.

Provides model pricing lookup (static + live OpenRouter sync),
cost estimation from token counts, and usage event emission.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any, Dict, Optional, Tuple

import logging

from ouroboros.utils import utc_now_iso

log = logging.getLogger(__name__)

# Pricing from OpenRouter API (2026-02-17). Update periodically via /api/v1/models.
MODEL_PRICING_STATIC = {
    "anthropic/claude-opus-4.6": (5.0, 0.5, 25.0),
    "anthropic/claude-opus-4": (15.0, 1.5, 75.0),
    "anthropic/claude-sonnet-4": (3.0, 0.30, 15.0),
    "anthropic/claude-sonnet-4.6": (3.0, 0.30, 15.0),
    "anthropic/claude-sonnet-4.5": (3.0, 0.30, 15.0),
    "openai/o3": (2.0, 0.50, 8.0),
    "openai/o3-pro": (20.0, 1.0, 80.0),
    "openai/o4-mini": (1.10, 0.275, 4.40),
    "openai/gpt-4.1": (2.0, 0.50, 8.0),
    "openai/gpt-5.2": (1.75, 0.175, 14.0),
    "openai/gpt-5.2-codex": (1.75, 0.175, 14.0),
    "openai/gpt-5.3-codex": (1.75, 0.175, 14.0),
    "google/gemini-2.5-pro-preview": (1.25, 0.125, 10.0),
    "google/gemini-3.1-pro-preview": (2.0, 0.20, 12.0),
    "google/gemini-3-pro-preview": (2.0, 0.20, 12.0),
    "google/gemini-3-flash-preview": (0.15, 0.015, 0.60),
    "x-ai/grok-3-mini": (0.30, 0.03, 0.50),
    "qwen/qwen3.5-plus-02-15": (0.40, 0.04, 2.40),
}

_pricing_fetched = False
_cached_pricing = None
_pricing_lock = threading.Lock()


def get_pricing() -> Dict[str, Tuple[float, float, float]]:
    """
    Lazy-load pricing. On first call, attempts to fetch from OpenRouter API.
    Falls back to static pricing if fetch fails.
    Thread-safe via module-level lock.
    """
    global _pricing_fetched, _cached_pricing

    # Single locked path: avoids races between flag/cache updates.
    with _pricing_lock:
        if _cached_pricing is None:
            _cached_pricing = dict(MODEL_PRICING_STATIC)
        if _pricing_fetched:
            return _cached_pricing

        try:
            from ouroboros.llm import fetch_openrouter_pricing
            _live = fetch_openrouter_pricing()
            if _live and len(_live) > 5:
                _cached_pricing.update(_live)
            _pricing_fetched = True
        except Exception as e:
            import logging as _log
            _log.getLogger(__name__).warning("Failed to sync pricing from OpenRouter: %s", e)
            # Keep flag false so we retry on next call.
            _pricing_fetched = False

        return _cached_pricing


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int,
                  cached_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    """Estimate cost from token counts using known pricing. Returns 0 if model unknown."""
    model_pricing = get_pricing()
    # Try exact match first
    pricing = model_pricing.get(model)
    if not pricing:
        # Try longest prefix match
        best_match = None
        best_length = 0
        for key, val in model_pricing.items():
            if model and model.startswith(key):
                if len(key) > best_length:
                    best_match = val
                    best_length = len(key)
        pricing = best_match
    if not pricing:
        return 0.0
    input_price, cached_price, output_price = pricing
    # Non-cached input tokens = prompt_tokens - cached_tokens
    regular_input = max(0, prompt_tokens - cached_tokens)
    cost = (
        regular_input * input_price / 1_000_000
        + cached_tokens * cached_price / 1_000_000
        + completion_tokens * output_price / 1_000_000
    )
    return round(cost, 6)


def _normalize_model_name(model: str) -> str:
    text = str(model or "").strip()
    if text.endswith(" (local)"):
        return text[:-8]
    return text


def infer_api_key_type(model: str) -> str:
    """Infer which API key is used based on model name."""
    normalized = _normalize_model_name(model)
    if str(model or "").endswith(" (local)"):
        return "local"
    if normalized.startswith(("anthropic/", "google/", "openai/", "x-ai/", "qwen/")):
        return "openrouter"
    if "claude" in normalized.lower():
        return "anthropic"
    return "openrouter"


def infer_model_category(model: str) -> str:
    """Infer model category by comparing against configured model env vars."""
    normalized = _normalize_model_name(model)
    configured = {
        "main": os.environ.get("OUROBOROS_MODEL", ""),
        "code": os.environ.get("OUROBOROS_MODEL_CODE", ""),
        "light": os.environ.get("OUROBOROS_MODEL_LIGHT", ""),
        "fallback": os.environ.get("OUROBOROS_MODEL_FALLBACK", ""),
    }
    for cat, val in configured.items():
        if val and normalized == val:
            return cat
    return "other"


def emit_llm_usage_event(
    event_queue: Optional[queue.Queue],
    task_id: str,
    model: str,
    usage: Dict[str, Any],
    cost: float,
    category: str = "task",
    provider: Optional[str] = None,
    source: str = "loop",
) -> None:
    """
    Emit llm_usage event to the event queue.

    Args:
        event_queue: Queue to emit events to (may be None)
        task_id: Task ID for the event
        model: Model name used for the LLM call
        usage: Usage dict from LLM response
        cost: Calculated cost for this call
        category: Budget category (task, evolution, consciousness, review, summarize, other)
    """
    if not event_queue:
        return
    try:
        resolved_provider = provider or ("local" if str(model or "").endswith(" (local)") else "openrouter")
        event_queue.put_nowait({
            "type": "llm_usage",
            "ts": utc_now_iso(),
            "task_id": task_id,
            "model": model,
            "api_key_type": infer_api_key_type(model),
            "model_category": infer_model_category(model),
            "provider": resolved_provider,
            "source": source,
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "cached_tokens": int(usage.get("cached_tokens") or 0),
            "cache_write_tokens": int(usage.get("cache_write_tokens") or 0),
            "cost": cost,
            "cost_estimated": not bool(usage.get("cost")),
            "usage": usage,
            "category": category,
        })
    except Exception:
        log.debug("Failed to put llm_usage event to queue", exc_info=True)
