"""Tests for ouroboros.context health invariants."""

from __future__ import annotations

import json

from ouroboros.context import build_health_invariants


class TestCacheHitRateInvariant:
    def _make_env(self, tmp_path, events_lines):
        class FakeEnv:
            def drive_path(self, p):
                return tmp_path / p
            def repo_path(self, p):
                return tmp_path / "repo" / p
            @property
            def repo_dir(self):
                return tmp_path / "repo"
            @property
            def drive_root(self):
                return tmp_path

        (tmp_path / "state").mkdir(parents=True, exist_ok=True)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        (tmp_path / "repo" / "docs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "repo" / "VERSION").write_text("1.2.3", encoding="utf-8")
        (tmp_path / "repo" / "pyproject.toml").write_text('version = "1.2.3"', encoding="utf-8")
        (tmp_path / "repo" / "README.md").write_text('version-1.2.3', encoding="utf-8")
        (tmp_path / "repo" / "docs" / "ARCHITECTURE.md").write_text('# Ouroboros v1.2.3', encoding="utf-8")
        (tmp_path / "repo" / "docs" / "DEVELOPMENT.md").write_text('# Dev', encoding="utf-8")
        (tmp_path / "state" / "state.json").write_text('{"spent_usd": 0, "budget_drift_alert": false}', encoding="utf-8")
        (tmp_path / "memory" / "identity.md").write_text('x' * 300, encoding="utf-8")
        (tmp_path / "memory" / "scratchpad.md").write_text('x' * 300, encoding="utf-8")
        (tmp_path / "logs" / "events.jsonl").write_text("\n".join(events_lines) + "\n", encoding="utf-8")
        return FakeEnv()

    def test_cache_hit_rate_good(self, tmp_path):
        lines = [json.dumps({"type": "llm_round", "prompt_tokens": 1000, "cached_tokens": 600}) for _ in range(15)]
        env = self._make_env(tmp_path, lines)
        result = build_health_invariants(env)
        assert "cache hit rate" in result.lower()
        assert "60%" in result or "60.0%" in result

    def test_cache_hit_rate_warning_below_30(self, tmp_path):
        lines = [json.dumps({"type": "llm_round", "prompt_tokens": 1000, "cached_tokens": 200}) for _ in range(15)]
        env = self._make_env(tmp_path, lines)
        result = build_health_invariants(env)
        assert "LOW CACHE HIT RATE" in result


class TestFileSizeBudgetHealthInvariant:
    def _make_env(self, tmp_path, development_text: str):
        class FakeEnv:
            def drive_path(self, p):
                return tmp_path / p
            def repo_path(self, p):
                return tmp_path / "repo" / p
            @property
            def repo_dir(self):
                return tmp_path / "repo"
            @property
            def drive_root(self):
                return tmp_path

        (tmp_path / "repo" / "docs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "repo" / "docs" / "DEVELOPMENT.md").write_text(development_text, encoding="utf-8")
        (tmp_path / "repo" / "VERSION").write_text("1.2.3", encoding="utf-8")
        (tmp_path / "repo" / "pyproject.toml").write_text('version = "1.2.3"', encoding="utf-8")
        (tmp_path / "repo" / "README.md").write_text('version-1.2.3', encoding="utf-8")
        (tmp_path / "repo" / "docs" / "ARCHITECTURE.md").write_text('# Ouroboros v1.2.3', encoding="utf-8")
        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        (tmp_path / "state").mkdir(parents=True, exist_ok=True)
        (tmp_path / "state" / "state.json").write_text('{"spent_usd": 0, "budget_drift_alert": false}', encoding="utf-8")
        (tmp_path / "memory" / "identity.md").write_text('x' * 300, encoding="utf-8")
        (tmp_path / "memory" / "scratchpad.md").write_text('x' * 300, encoding="utf-8")
        return FakeEnv()

    def test_warns_when_memory_file_nears_budget(self, tmp_path):
        dev = """
### File Size Budgets
| Path | Budget chars |
|------|--------------|
| memory/identity.md | 1000 |
### Next Section
"""
        env = self._make_env(tmp_path, dev)
        (tmp_path / "memory" / "identity.md").write_text("x" * 950, encoding="utf-8")
        result = build_health_invariants(env)
        assert "FILE SIZE NEAR BUDGET" in result
        assert "memory/identity.md" in result

    def test_warns_when_prompt_file_exceeds_budget(self, tmp_path):
        dev = """
### File Size Budgets
| Path | Budget chars |
|------|--------------|
| prompts/SYSTEM.md | 1000 |
### Next Section
"""
        env = self._make_env(tmp_path, dev)
        (tmp_path / "repo" / "prompts").mkdir(parents=True, exist_ok=True)
        (tmp_path / "repo" / "prompts" / "SYSTEM.md").write_text("y" * 1200, encoding="utf-8")
        result = build_health_invariants(env)
        assert "FILE SIZE BUDGET EXCEEDED" in result
        assert "prompts/SYSTEM.md" in result
