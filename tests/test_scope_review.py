"""Tests for the review stack upgrade: scope review, review_helpers, enriched triad.

Verifies:
- Checklist section loader extracts exact sections
- Goal/scope precedence: goal > scope > commit_message > fallback
- Touched-file pack builds correctly
- Scope review module structure
- Broader repo pack excludes touched files
- Path-aware freshness
- Stale marking lifecycle
- repo_write_commit doesn't bypass the new stack
- review_helpers imports cleanly (no circular deps)
"""

import importlib
import inspect
import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_module(name):
    sys.path.insert(0, REPO)
    return importlib.import_module(name)


# ---------------------------------------------------------------------------
# review_helpers tests
# ---------------------------------------------------------------------------

class TestChecklistSectionLoader:
    def test_loads_repo_commit_section(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        section = mod.load_checklist_section("Repo Commit Checklist")
        assert "## Repo Commit Checklist" in section
        assert "bible_compliance" in section
        # Must NOT contain scope checklist
        assert "Intent / Scope Review Checklist" not in section

    def test_loads_scope_section(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        section = mod.load_checklist_section("Intent / Scope Review Checklist")
        assert "## Intent / Scope Review Checklist" in section
        assert "intent_alignment" in section
        # Must NOT contain repo commit checklist items
        assert "## Repo Commit Checklist" not in section

    def test_raises_on_missing_section(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        with pytest.raises(ValueError):
            mod.load_checklist_section("Nonexistent Section")


class TestGoalScopePrecedence:
    def test_goal_wins(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        text, source = mod.resolve_intent(goal="fix X", scope="scope Y", commit_message="msg Z")
        assert source == "goal"
        assert "fix X" in text

    def test_scope_when_no_goal(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        text, source = mod.resolve_intent(goal="", scope="scope Y", commit_message="msg Z")
        assert source == "scope"
        assert "scope Y" in text

    def test_commit_message_when_no_goal_no_scope(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        text, source = mod.resolve_intent(goal="", scope="", commit_message="msg Z")
        assert source == "commit message"
        assert "msg Z" in text

    def test_fallback_when_all_empty(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        text, source = mod.resolve_intent()
        assert source == "fallback"
        assert "No explicit goal" in text

    def test_no_raw_task_text_in_fallback(self):
        """Fallback must NOT use raw task/chat text."""
        mod = _get_module("ouroboros.tools.review_helpers")
        text, source = mod.resolve_intent()
        assert "task" not in text.lower() or "No explicit" in text


class TestGoalSection:
    def test_goal_section_has_source(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        section = mod.build_goal_section(goal="fix bug", scope="", commit_message="msg")
        assert "Source: goal" in section
        assert "fix bug" in section

    def test_scope_section_empty_when_no_scope(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        section = mod.build_scope_section()
        assert section == ""

    def test_scope_section_present_when_scope(self):
        mod = _get_module("ouroboros.tools.review_helpers")
        section = mod.build_scope_section(scope="only review.py")
        assert "only review.py" in section
        assert "IMPORTANT" in section


class TestTouchedFilePack:
    def test_reads_existing_files(self, tmp_path):
        (tmp_path / "a.py").write_text("print('hello')", encoding="utf-8")
        (tmp_path / "b.md").write_text("# readme", encoding="utf-8")
        mod = _get_module("ouroboros.tools.review_helpers")
        pack, omitted = mod.build_touched_file_pack(tmp_path, ["a.py", "b.md"])
        assert "a.py" in pack
        assert "print('hello')" in pack
        assert "b.md" in pack
        assert omitted == []

    def test_skips_binary_files(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        mod = _get_module("ouroboros.tools.review_helpers")
        pack, omitted = mod.build_touched_file_pack(tmp_path, ["image.png"])
        assert "image.png" in omitted
        assert "```" not in pack or "image.png" not in pack.split("```")[1] if "```" in pack else True

    def test_omits_large_files(self, tmp_path):
        (tmp_path / "huge.py").write_text("x" * 200_000, encoding="utf-8")
        mod = _get_module("ouroboros.tools.review_helpers")
        pack, omitted = mod.build_touched_file_pack(tmp_path, ["huge.py"])
        assert "huge.py" in omitted
        assert "omitted" in pack.lower()


class TestBroaderRepoPack:
    def test_excludes_touched_files(self, tmp_path):
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "a.py").write_text("AAA", encoding="utf-8")
        (tmp_path / "b.py").write_text("BBB", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        mod = _get_module("ouroboros.tools.review_helpers")
        pack = mod.build_broader_repo_pack(tmp_path, exclude_paths={"a.py"})
        assert "BBB" in pack
        assert "AAA" not in pack


# ---------------------------------------------------------------------------
# Scope review module tests
# ---------------------------------------------------------------------------

class TestScopeFailClosed:
    """Runtime tests for fail-closed scope review behavior."""

    def test_build_scope_prompt_blocks_on_empty_touched(self, tmp_path):
        """_build_scope_prompt returns '__empty__' when no touched files are readable."""
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "CHECKLISTS.md").write_text("## Intent / Scope Review Checklist\n\nplaceholder\n")
        (tmp_path / "docs" / "DEVELOPMENT.md").write_text("dev guide\n")
        # Stage a file then delete it so it's in git status but unreadable
        (tmp_path / "gone.py").write_text("x")
        subprocess.run(["git", "add", "gone.py"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "gone.py").unlink()
        subprocess.run(["git", "add", "gone.py"], cwd=str(tmp_path), capture_output=True)

        mod = _get_module("ouroboros.tools.scope_review")
        prompt, omitted = mod._build_scope_prompt(tmp_path, "test msg")
        # With no readable touched files, omitted should signal empty
        assert omitted is not None

    def test_build_scope_prompt_blocks_on_partial_omission(self, tmp_path):
        """_build_scope_prompt returns omitted filenames when some files are binary."""
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "CHECKLISTS.md").write_text("## Intent / Scope Review Checklist\n\nplaceholder\n")
        (tmp_path / "docs" / "DEVELOPMENT.md").write_text("dev guide\n")
        (tmp_path / "good.py").write_text("print('ok')")
        (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n" + b"\x00" * 100)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        # Stage both files
        (tmp_path / "good.py").write_text("print('v2')")
        (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n" + b"\x00" * 200)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)

        mod = _get_module("ouroboros.tools.scope_review")
        prompt, omitted = mod._build_scope_prompt(tmp_path, "test msg")
        assert omitted is not None
        assert "image.png" in omitted

    def test_build_scope_prompt_clean_when_all_readable(self, tmp_path):
        """_build_scope_prompt returns None omitted when all files are readable."""
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "CHECKLISTS.md").write_text("## Intent / Scope Review Checklist\n\nplaceholder\n")
        (tmp_path / "docs" / "DEVELOPMENT.md").write_text("dev guide\n")
        (tmp_path / "a.py").write_text("aaa")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "a.py").write_text("bbb")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)

        mod = _get_module("ouroboros.tools.scope_review")
        prompt, omitted = mod._build_scope_prompt(tmp_path, "test msg")
        assert omitted is None
        assert "bbb" in prompt


class TestRunScopeReviewFailClosed:
    """End-to-end fail-closed tests that execute run_scope_review()."""

    def test_run_scope_review_blocks_on_binary_files(self, tmp_path):
        """run_scope_review() must return SCOPE_REVIEW_BLOCKED for binary touched files."""
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "CHECKLISTS.md").write_text("## Intent / Scope Review Checklist\n\nplaceholder\n")
        (tmp_path / "docs" / "DEVELOPMENT.md").write_text("dev guide\n")
        (tmp_path / "ok.py").write_text("print(1)")
        (tmp_path / "bin.png").write_bytes(b"\x89PNG" + b"\x00" * 200)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "ok.py").write_text("print(2)")
        (tmp_path / "bin.png").write_bytes(b"\x89PNG" + b"\x00" * 300)
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)

        # Create a minimal mock ToolContext
        class MockCtx:
            repo_dir = str(tmp_path)
        ctx = MockCtx()

        mod = _get_module("ouroboros.tools.scope_review")
        result = mod.run_scope_review(
            ctx, "test commit",
            goal="test goal", scope="test scope",
        )
        assert "SCOPE_REVIEW_BLOCKED" in result
        assert "bin.png" in result

    def test_run_scope_review_blocks_on_empty_touched(self, tmp_path):
        """run_scope_review() must block when no touched files are readable."""
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "CHECKLISTS.md").write_text("## Intent / Scope Review Checklist\n\nplaceholder\n")
        (tmp_path / "docs" / "DEVELOPMENT.md").write_text("dev guide\n")
        (tmp_path / "gone.py").write_text("x")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "gone.py").unlink()
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)

        class MockCtx:
            repo_dir = str(tmp_path)
        ctx = MockCtx()

        mod = _get_module("ouroboros.tools.scope_review")
        result = mod.run_scope_review(ctx, "test commit")
        assert "SCOPE_REVIEW_BLOCKED" in result


class TestScopeReviewModule:
    def test_scope_review_imports(self):
        mod = _get_module("ouroboros.tools.scope_review")
        assert hasattr(mod, "run_scope_review")
        assert callable(mod.run_scope_review)

    def test_scope_review_fail_closed_design(self):
        """run_scope_review must be fail-closed: errors return blocking strings."""
        mod = _get_module("ouroboros.tools.scope_review")
        source = inspect.getsource(mod.run_scope_review)
        assert "SCOPE_REVIEW_BLOCKED" in source
        assert "fail" in source.lower() or "block" in source.lower()

    def test_scope_review_uses_opus(self):
        mod = _get_module("ouroboros.tools.scope_review")
        assert "claude-opus-4.6" in mod._SCOPE_MODEL_DEFAULT
        # Also verify the getter works
        assert "claude-opus-4.6" in mod._get_scope_model()

    def test_scope_review_model_configurable_via_env(self):
        """OUROBOROS_SCOPE_REVIEW_MODEL env overrides the default."""
        mod = _get_module("ouroboros.tools.scope_review")
        import os
        old = os.environ.get("OUROBOROS_SCOPE_REVIEW_MODEL")
        try:
            os.environ["OUROBOROS_SCOPE_REVIEW_MODEL"] = "google/gemini-2.5-pro"
            assert mod._get_scope_model() == "google/gemini-2.5-pro"
        finally:
            if old is None:
                os.environ.pop("OUROBOROS_SCOPE_REVIEW_MODEL", None)
            else:
                os.environ["OUROBOROS_SCOPE_REVIEW_MODEL"] = old

    def test_scope_review_effort_configurable(self):
        """OUROBOROS_EFFORT_SCOPE_REVIEW should resolve via resolve_effort."""
        from ouroboros.config import resolve_effort
        import os
        old = os.environ.get("OUROBOROS_EFFORT_SCOPE_REVIEW")
        try:
            os.environ["OUROBOROS_EFFORT_SCOPE_REVIEW"] = "low"
            assert resolve_effort("scope_review") == "low"
            assert resolve_effort("scope-review") == "low"
        finally:
            if old is None:
                os.environ.pop("OUROBOROS_EFFORT_SCOPE_REVIEW", None)
            else:
                os.environ["OUROBOROS_EFFORT_SCOPE_REVIEW"] = old

    def test_scope_prompt_includes_scope_checklist(self):
        """_build_scope_prompt must load the scope checklist, not the repo checklist."""
        mod = _get_module("ouroboros.tools.scope_review")
        source = inspect.getsource(mod._build_scope_prompt)
        assert "Intent / Scope Review Checklist" in source

    def test_scope_prompt_includes_broader_repo_pack(self):
        mod = _get_module("ouroboros.tools.scope_review")
        source = inspect.getsource(mod._build_scope_prompt)
        assert "build_broader_repo_pack" in source


# ---------------------------------------------------------------------------
# review_state path-aware freshness
# ---------------------------------------------------------------------------

class TestPathAwareFreshness:
    def test_snapshot_hash_stable_without_message(self, tmp_path):
        """Snapshot hash should NOT change when only commit_message changes."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        rs = _get_module("ouroboros.review_state")
        h1 = rs.compute_snapshot_hash(tmp_path, "message A")
        h2 = rs.compute_snapshot_hash(tmp_path, "message B")
        # Hash now based on code only — should be SAME for different messages
        assert h1 == h2

    def test_snapshot_hash_changes_with_file_content(self, tmp_path):
        """Snapshot hash must change when file content changes."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "file.py").write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "file.py"], cwd=str(tmp_path), capture_output=True)
        rs = _get_module("ouroboros.review_state")
        h1 = rs.compute_snapshot_hash(tmp_path, "msg")
        # Modify file
        (tmp_path / "file.py").write_text("v2", encoding="utf-8")
        h2 = rs.compute_snapshot_hash(tmp_path, "msg")
        assert h1 != h2

    def test_path_scoped_hash(self, tmp_path):
        """When paths= is provided, only those files affect the hash."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "a.py").write_text("aaa", encoding="utf-8")
        (tmp_path / "b.py").write_text("bbb", encoding="utf-8")
        rs = _get_module("ouroboros.review_state")
        h_a = rs.compute_snapshot_hash(tmp_path, paths=["a.py"])
        h_b = rs.compute_snapshot_hash(tmp_path, paths=["b.py"])
        assert h_a != h_b

    def test_stale_lifecycle(self):
        """add_run marks previous non-matching fresh runs as stale."""
        rs = _get_module("ouroboros.review_state")
        state = rs.AdvisoryReviewState()
        run1 = rs.AdvisoryRunRecord(
            snapshot_hash="hash1", commit_message="m1",
            status="fresh", ts="2026-01-01T00:00:00",
        )
        state.add_run(run1)
        assert state.runs[0].status == "fresh"

        run2 = rs.AdvisoryRunRecord(
            snapshot_hash="hash2", commit_message="m2",
            status="fresh", ts="2026-01-01T01:00:00",
        )
        state.add_run(run2)
        assert state.runs[0].status == "stale"  # hash1 became stale
        assert state.runs[1].status == "fresh"   # hash2 is fresh


# ---------------------------------------------------------------------------
# Triad review enrichment
# ---------------------------------------------------------------------------

class TestTriadReviewEnriched:
    def test_triad_prompt_has_touched_files_placeholder(self):
        """The review prompt template must include current_files_section."""
        mod = _get_module("ouroboros.tools.review")
        assert "{current_files_section}" in mod._REVIEW_PROMPT_TEMPLATE

    def test_triad_prompt_has_goal_section(self):
        """The review prompt template must include goal_section."""
        mod = _get_module("ouroboros.tools.review")
        assert "{goal_section}" in mod._REVIEW_PROMPT_TEMPLATE

    def test_run_unified_review_accepts_goal_scope(self):
        """_run_unified_review must accept goal and scope keyword args."""
        mod = _get_module("ouroboros.tools.review")
        sig = inspect.signature(mod._run_unified_review)
        assert "goal" in sig.parameters
        assert "scope" in sig.parameters


# ---------------------------------------------------------------------------
# git.py wiring
# ---------------------------------------------------------------------------

class TestGitWiring:
    def test_repo_commit_schema_has_goal_scope(self):
        git = _get_module("ouroboros.tools.git")
        tools = git.get_tools()
        commit = next(t for t in tools if t.name == "repo_commit")
        props = commit.schema["parameters"]["properties"]
        assert "goal" in props
        assert "scope" in props

    def test_repo_commit_push_accepts_goal_scope(self):
        git = _get_module("ouroboros.tools.git")
        sig = inspect.signature(git._repo_commit_push)
        assert "goal" in sig.parameters
        assert "scope" in sig.parameters

    def test_scope_review_wired_in_commit(self):
        """_repo_commit_push must call scope review after triad review."""
        git = _get_module("ouroboros.tools.git")
        source = inspect.getsource(git._repo_commit_push)
        assert "run_scope_review" in source
        # Scope review must come after triad review
        triad_pos = source.find("_run_unified_review")
        scope_pos = source.find("run_scope_review")
        assert triad_pos < scope_pos

    def test_repo_write_commit_not_bypass_scope(self):
        """Legacy _repo_write_commit uses advisory gate; scope review is in the unified path."""
        git = _get_module("ouroboros.tools.git")
        source = inspect.getsource(git._repo_write_commit)
        assert "_check_advisory_freshness" in source

    def test_advisory_freshness_path_aware(self):
        """_check_advisory_freshness must accept paths parameter."""
        git = _get_module("ouroboros.tools.git")
        sig = inspect.signature(git._check_advisory_freshness)
        assert "paths" in sig.parameters


# ---------------------------------------------------------------------------
# Advisory schema enrichment
# ---------------------------------------------------------------------------

class TestAdvisorySchemaEnriched:
    def test_advisory_schema_has_goal_scope_paths(self):
        adv = _get_module("ouroboros.tools.claude_advisory_review")
        tools = adv.get_tools()
        adv_tool = next(t for t in tools if t.name == "advisory_pre_review")
        props = adv_tool.schema["parameters"]["properties"]
        assert "goal" in props
        assert "scope" in props
        assert "paths" in props

    def test_advisory_prompt_uses_section_loader(self):
        """Advisory prompt builder must use precise section loader, not full CHECKLISTS.md."""
        adv = _get_module("ouroboros.tools.claude_advisory_review")
        source = inspect.getsource(adv._build_advisory_prompt)
        assert "load_checklist_section" in source

    def test_advisory_no_blind_truncation(self):
        """Advisory must not silently truncate raw_result."""
        adv = _get_module("ouroboros.tools.claude_advisory_review")
        source = inspect.getsource(adv._handle_advisory_pre_review)
        assert "raw_result[:4000]" not in source
