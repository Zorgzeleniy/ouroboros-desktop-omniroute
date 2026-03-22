"""Tests for supervisor/events.py _handle_llm_usage event persistence."""

import json


def test_llm_usage_writes_cached_tokens_and_cache_write_tokens(tmp_path):
    from supervisor import events as ev_module

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    class FakeCtx:
        DRIVE_ROOT = tmp_path
        def update_budget_from_usage(self, usage):
            self.last_usage = usage

    evt = {
        "type": "llm_usage",
        "model": "anthropic/claude-sonnet-4.6",
        "usage": {
            "prompt_tokens": 2000,
            "completion_tokens": 300,
            "cost": 0.01,
            "cached_tokens": 1200,
            "cache_write_tokens": 400,
        },
        "category": "compaction",
        "provider": "openrouter",
        "source": "loop",
        "model_category": "light",
        "api_key_type": "openrouter",
        "cost_estimated": False,
    }
    ctx = FakeCtx()
    ev_module._handle_llm_usage(evt, ctx)

    events_file = tmp_path / "logs" / "events.jsonl"
    written = json.loads(events_file.read_text(encoding="utf-8").strip())
    assert written.get("cached_tokens") == 1200
    assert written.get("cache_write_tokens") == 400
    assert written.get("category") == "compaction"
    assert written.get("provider") == "openrouter"
    assert written.get("source") == "loop"
    assert written.get("model_category") == "light"
    assert written.get("api_key_type") == "openrouter"
    assert written.get("cost_estimated") is False
    assert ctx.last_usage["cached_tokens"] == 1200
