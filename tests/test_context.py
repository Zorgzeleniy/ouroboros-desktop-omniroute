"""Tests for ouroboros.context health invariants."""

from __future__ import annotations

import json
import pathlib
import tempfile

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


class TestAdvisoryReviewStatusInContext:
    """Tests that advisory review status appears in LLM context when runs exist."""

    def _make_env(self, tmp_path):
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
        return FakeEnv()

    def test_advisory_status_in_build_llm_messages(self, tmp_path):
        """format_status_section returns non-empty string when runs exist."""
        from ouroboros.review_state import (
            AdvisoryReviewState, AdvisoryRunRecord, save_state, format_status_section
        )
        state = AdvisoryReviewState()
        state.add_run(AdvisoryRunRecord(
            snapshot_hash="abc123",
            commit_message="test commit",
            status="fresh",
            ts="2026-01-01T00:00:00",
            items=[{"item": "bible_compliance", "verdict": "PASS", "severity": "critical", "reason": "ok"}],
        ))
        save_state(tmp_path, state)

        loaded = __import__("ouroboros.review_state", fromlist=["load_state"]).load_state(tmp_path)
        section = format_status_section(loaded)
        assert "Advisory Pre-Review Status" in section
        assert "FRESH" in section
        assert "abc123" in section

    def test_advisory_status_empty_when_no_runs(self, tmp_path):
        """format_status_section returns 'No advisory runs' when state is empty."""
        from ouroboros.review_state import AdvisoryReviewState, format_status_section
        state = AdvisoryReviewState()
        section = format_status_section(state)
        assert "No advisory runs" in section


class TestRuntimeEnvSection:
    """build_runtime_section includes runtime_env with platform and is_desktop."""

    def _make_env(self, tmp_path):
        class FakeEnv:
            repo_dir = tmp_path / "repo"
            drive_root = tmp_path

            def drive_path(self, p):
                return tmp_path / p

        (tmp_path / "state").mkdir(parents=True, exist_ok=True)
        (tmp_path / "state" / "state.json").write_text(
            '{"spent_usd": 0}', encoding="utf-8"
        )
        return FakeEnv()

    def test_runtime_env_present(self, tmp_path, monkeypatch):
        from ouroboros.context import build_runtime_section

        monkeypatch.delenv("OUROBOROS_DESKTOP_MODE", raising=False)
        env = self._make_env(tmp_path)
        section = build_runtime_section(env, {"id": "t1", "type": "task"})
        data = json.loads(section.split("## Runtime context\n\n", 1)[1])
        assert "runtime_env" in data
        assert "platform" in data["runtime_env"]
        assert isinstance(data["runtime_env"]["platform"], str)
        assert data["runtime_env"]["is_desktop"] is False

    def test_runtime_env_desktop_flag(self, tmp_path, monkeypatch):
        from ouroboros.context import build_runtime_section

        monkeypatch.setenv("OUROBOROS_DESKTOP_MODE", "1")
        env = self._make_env(tmp_path)
        section = build_runtime_section(env, {"id": "t2", "type": "task"})
        data = json.loads(section.split("## Runtime context\n\n", 1)[1])
        assert data["runtime_env"]["is_desktop"] is True
