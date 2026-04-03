"""Behavioral tests for Phase 7: modern commit pipeline, operational resilience.

Tests:
- repo_write single-file and multi-file modes
- repo_write + repo_commit workflow
- Unified pre-commit review gate (preflight, parse, quorum)
- Blocked review leaves files on disk but unstaged
- review_rebuttal parameter
- configure_remote failure surfacing
- migrate_remote_credentials no-op on clean origin
- Auto-rescue only reports committed when commit actually happened
- repo_write in CORE_TOOL_NAMES
- Review history building
"""
import importlib
import inspect
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


def _get_git_module():
    return importlib.import_module("ouroboros.tools.git")


def _get_review_module():
    return importlib.import_module("ouroboros.tools.review")


def _get_registry_module():
    return importlib.import_module("ouroboros.tools.registry")


def _get_git_ops_module():
    return importlib.import_module("supervisor.git_ops")


def _make_ctx(tmp_path):
    """Create a minimal ToolContext with a temporary git repo."""
    from ouroboros.tools.registry import ToolContext
    repo = tmp_path / "repo"
    repo.mkdir()
    drive = tmp_path / "drive"
    drive.mkdir()
    (drive / "logs").mkdir(parents=True)
    (drive / "locks").mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), capture_output=True)
    (repo / "dummy.txt").write_text("init")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "branch", "-M", "ouroboros"], cwd=str(repo), capture_output=True)
    return ToolContext(repo_dir=repo, drive_root=drive)


# --- repo_write tool registration ---

class TestRepoWriteRegistration:
    def test_repo_write_registered(self):
        git_mod = _get_git_module()
        names = [t.name for t in git_mod.get_tools()]
        assert "repo_write" in names

    def test_repo_write_in_core_tool_names(self):
        registry = _get_registry_module()
        assert "repo_write" in registry.CORE_TOOL_NAMES

    def test_repo_write_commit_still_registered(self):
        git_mod = _get_git_module()
        names = [t.name for t in git_mod.get_tools()]
        assert "repo_write_commit" in names

    def test_repo_write_schema_has_files_param(self):
        git_mod = _get_git_module()
        tools = git_mod.get_tools()
        rw = next(t for t in tools if t.name == "repo_write")
        props = rw.schema["parameters"]["properties"]
        assert "files" in props
        assert props["files"]["type"] == "array"

    def test_repo_commit_has_review_rebuttal(self):
        git_mod = _get_git_module()
        tools = git_mod.get_tools()
        rc = next(t for t in tools if t.name == "repo_commit")
        props = rc.schema["parameters"]["properties"]
        assert "review_rebuttal" in props


# --- repo_write behavioral tests ---

class TestRepoWriteSingleFile:
    def test_single_file_write(self, tmp_path):
        git_mod = _get_git_module()
        ctx = _make_ctx(tmp_path)
        result = git_mod._repo_write(ctx, path="hello.py", content="print('hello')")
        assert "Written 1 file" in result
        assert "NOT committed" in result
        assert (ctx.repo_dir / "hello.py").read_text() == "print('hello')"

    def test_single_file_creates_directories(self, tmp_path):
        git_mod = _get_git_module()
        ctx = _make_ctx(tmp_path)
        result = git_mod._repo_write(ctx, path="deep/nested/file.py", content="x = 1")
        assert "Written 1 file" in result
        assert (ctx.repo_dir / "deep" / "nested" / "file.py").exists()

    def test_rejects_empty_args(self, tmp_path):
        git_mod = _get_git_module()
        ctx = _make_ctx(tmp_path)
        result = git_mod._repo_write(ctx)
        assert "WRITE_ERROR" in result

    def test_rejects_compaction_marker(self, tmp_path):
        git_mod = _get_git_module()
        ctx = _make_ctx(tmp_path)
        result = git_mod._repo_write(ctx, path="x.py", content="<<CONTENT_OMITTED something")
        assert "WRITE_ERROR" in result
        assert "compaction marker" in result


class TestRepoWriteMultiFile:
    def test_multi_file_write(self, tmp_path):
        git_mod = _get_git_module()
        ctx = _make_ctx(tmp_path)
        result = git_mod._repo_write(ctx, files=[
            {"path": "a.py", "content": "# a"},
            {"path": "b.py", "content": "# b"},
        ])
        assert "Written 2 file" in result
        assert (ctx.repo_dir / "a.py").read_text() == "# a"
        assert (ctx.repo_dir / "b.py").read_text() == "# b"

    def test_multi_file_rejects_empty_path(self, tmp_path):
        git_mod = _get_git_module()
        ctx = _make_ctx(tmp_path)
        result = git_mod._repo_write(ctx, files=[{"path": "", "content": "x"}])
        assert "WRITE_ERROR" in result

    def test_multi_file_blocks_safety_critical(self, tmp_path):
        git_mod = _get_git_module()
        ctx = _make_ctx(tmp_path)
        result = git_mod._repo_write(ctx, files=[
            {"path": "ok.py", "content": "x"},
            {"path": "BIBLE.md", "content": "hacked"},
        ])
        assert "SAFETY_VIOLATION" in result

    def test_files_param_takes_priority(self, tmp_path):
        git_mod = _get_git_module()
        ctx = _make_ctx(tmp_path)
        result = git_mod._repo_write(
            ctx, path="ignored.py", content="ignored",
            files=[{"path": "used.py", "content": "used"}],
        )
        assert "Written 1 file" in result
        assert (ctx.repo_dir / "used.py").exists()
        assert not (ctx.repo_dir / "ignored.py").exists()


# --- Unified review gate ---

class TestPreflightCheck:
    def test_missing_version(self):
        review = _get_review_module()
        result = review._preflight_check(
            "v3.24.0: big change",
            "ouroboros/tools/git.py\nREADME.md",
            "/tmp",
        )
        assert result is not None
        assert "PREFLIGHT_BLOCKED" in result
        assert "VERSION" in result

    def test_missing_readme(self):
        review = _get_review_module()
        result = review._preflight_check(
            "some change",
            "VERSION\nouroboros/tools/git.py",
            "/tmp",
        )
        assert result is not None
        assert "README.md" in result

    def test_all_present_passes(self):
        review = _get_review_module()
        result = review._preflight_check(
            "v3.24.0: change",
            "VERSION\nREADME.md\nouroboros/tools/git.py",
            "/tmp",
        )
        assert result is None

    def test_no_version_ref_passes(self):
        review = _get_review_module()
        result = review._preflight_check(
            "fix typo in docs",
            "docs/ARCHITECTURE.md",
            "/tmp",
        )
        assert result is None


class TestParseReviewJson:
    def test_plain_json(self):
        review = _get_review_module()
        data = '[{"item":"x","verdict":"PASS","severity":"critical","reason":"ok"}]'
        result = review._parse_review_json(data)
        assert result is not None
        assert len(result) == 1

    def test_markdown_fenced(self):
        review = _get_review_module()
        data = '```json\n[{"item":"x","verdict":"FAIL","severity":"advisory","reason":"bad"}]\n```'
        result = review._parse_review_json(data)
        assert result is not None
        assert result[0]["verdict"] == "FAIL"

    def test_text_around_json(self):
        review = _get_review_module()
        data = 'Here is my review:\n[{"item":"x","verdict":"PASS","severity":"critical","reason":"ok"}]\nDone.'
        result = review._parse_review_json(data)
        assert result is not None

    def test_invalid_json(self):
        review = _get_review_module()
        result = review._parse_review_json("not json at all")
        assert result is None


class TestReviewHistoryBuilding:
    def test_empty_history(self):
        review = _get_review_module()
        result = review._build_review_history_section([])
        assert result == ""

    def test_history_with_entries(self):
        review = _get_review_module()
        history = [{
            "attempt": 1,
            "commit_message": "test commit",
            "critical": ["[model] item: reason"],
            "advisory": [],
        }]
        result = review._build_review_history_section(history)
        assert "Round 1" in result
        assert "test commit" in result
        assert "CRITICAL" in result


class TestReviewQuorumLogic:
    def test_review_models_configured(self):
        from ouroboros.config import get_review_models
        models = get_review_models()
        assert len(models) >= 2  # config.py is single source of truth

    def test_checklist_path_exists(self):
        review = _get_review_module()
        assert review._CHECKLISTS_PATH.exists()

    def test_load_checklist_succeeds(self):
        review = _get_review_module()
        section = review._load_checklist_section()
        assert "bible_compliance" in section
        assert "code_quality" in section


class TestReviewEnforcementModes:
    @staticmethod
    def _fake_result(*review_texts):
        return json.dumps({
            "results": [
                {
                    "model": f"model-{idx}",
                    "verdict": "PASS",
                    "text": text,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "cost_estimate": 0.0,
                }
                for idx, text in enumerate(review_texts, start=1)
            ]
        })

    @staticmethod
    def _mock_staged(monkeypatch, review_mod, changed_files="x.py", diff_text="diff --cached"):
        def _fake_run_cmd(cmd, cwd=None):
            cmd = list(cmd)
            if cmd[:4] == ["git", "diff", "--cached", "--name-only"]:
                return changed_files
            if cmd[:3] == ["git", "diff", "--cached"]:
                return diff_text
            return ""
        monkeypatch.setattr(review_mod, "run_cmd", _fake_run_cmd)

    def test_blocking_mode_blocks_critical_findings(self, tmp_path, monkeypatch):
        review = _get_review_module()
        ctx = _make_ctx(tmp_path)
        self._mock_staged(monkeypatch, review, changed_files="x.py")
        monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "blocking")
        monkeypatch.setattr(
            review,
            "_handle_multi_model_review",
            lambda *args, **kwargs: self._fake_result(
                '[{"item":"code_quality","verdict":"FAIL","severity":"critical","reason":"broken"}]',
                '[{"item":"code_quality","verdict":"PASS","severity":"critical","reason":"ok"}]',
            ),
        )
        result = review._run_unified_review(ctx, "test commit", repo_dir=ctx.repo_dir)
        assert result is not None
        assert "REVIEW_BLOCKED" in result

    def test_advisory_mode_downgrades_critical_findings(self, tmp_path, monkeypatch):
        review = _get_review_module()
        ctx = _make_ctx(tmp_path)
        self._mock_staged(monkeypatch, review, changed_files="x.py")
        monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "advisory")
        monkeypatch.setattr(
            review,
            "_handle_multi_model_review",
            lambda *args, **kwargs: self._fake_result(
                '[{"item":"code_quality","verdict":"FAIL","severity":"critical","reason":"broken"}]',
                '[{"item":"code_quality","verdict":"PASS","severity":"critical","reason":"ok"}]',
            ),
        )
        result = review._run_unified_review(ctx, "test commit", repo_dir=ctx.repo_dir)
        assert result is None
        assert any("critical review findings did not block commit" in w.lower() for w in ctx._review_advisory)
        assert any("broken" in w for w in ctx._review_advisory)
        assert ctx._review_iteration_count == 0

    def test_advisory_mode_downgrades_quorum_failure(self, tmp_path, monkeypatch):
        review = _get_review_module()
        ctx = _make_ctx(tmp_path)
        self._mock_staged(monkeypatch, review, changed_files="x.py")
        monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "advisory")
        monkeypatch.setattr(
            review,
            "_handle_multi_model_review",
            lambda *args, **kwargs: self._fake_result(
                "Error: timeout",
                '[{"item":"code_quality","verdict":"PASS","severity":"critical","reason":"ok"}]',
            ),
        )
        result = review._run_unified_review(ctx, "test commit", repo_dir=ctx.repo_dir)
        assert result is None
        assert any(
            "only 1 of 2 review models responded successfully" in w.lower()
            or "review enforcement=advisory" in w.lower()
            for w in ctx._review_advisory
        )

    def test_advisory_mode_keeps_preflight_as_warning(self, tmp_path, monkeypatch):
        review = _get_review_module()
        ctx = _make_ctx(tmp_path)
        self._mock_staged(monkeypatch, review, changed_files="VERSION")
        monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "advisory")
        monkeypatch.setattr(
            review,
            "_handle_multi_model_review",
            lambda *args, **kwargs: self._fake_result(
                '[{"item":"version_bump","verdict":"PASS","severity":"critical","reason":"ok"}]',
                '[{"item":"readme_changelog","verdict":"PASS","severity":"critical","reason":"ok"}]',
            ),
        )
        result = review._run_unified_review(ctx, "version update", repo_dir=ctx.repo_dir)
        assert result is None
        assert any("preflight warning did not block commit" in w.lower() for w in ctx._review_advisory)


# --- Unified review wired into commit functions ---

class TestReviewInCommitPipeline:
    def test_repo_commit_calls_unified_review(self):
        git_mod = _get_git_module()
        source = inspect.getsource(git_mod._repo_commit_push)
        assert "_run_unified_review" in source

    def test_repo_write_commit_calls_unified_review(self):
        git_mod = _get_git_module()
        source = inspect.getsource(git_mod._repo_write_commit)
        assert "_run_unified_review" in source

    def test_blocked_review_unstages(self):
        """When review blocks, git reset HEAD must be called."""
        git_mod = _get_git_module()
        source = inspect.getsource(git_mod._repo_commit_push)
        assert 'git", "reset", "HEAD"' in source

    def test_review_rebuttal_forwarded(self):
        git_mod = _get_git_module()
        source = inspect.getsource(git_mod._repo_commit_push)
        assert "review_rebuttal" in source


# --- Auto-push and last_push_succeeded ---

class TestAutoPushBehavior:
    def test_auto_push_exists(self):
        git_mod = _get_git_module()
        assert hasattr(git_mod, "_auto_push")
        assert callable(git_mod._auto_push)

    def test_auto_push_is_best_effort(self):
        git_mod = _get_git_module()
        source = inspect.getsource(git_mod._auto_push)
        assert "except Exception" in source
        assert "non-fatal" in source.lower() or "non_fatal" in source.lower()


# --- configure_remote failure surfacing ---

class TestRemoteConfigSurfacing:
    def test_server_logs_remote_failure(self):
        """server.py must check the (ok, msg) return from configure_remote."""
        server_path = pathlib.Path(REPO) / "server.py"
        source = server_path.read_text()
        assert "remote_ok, remote_msg = configure_remote" in source
        assert "Remote configuration failed" in source

    def test_settings_save_returns_warnings(self):
        """api_settings_post must surface remote config failures."""
        server_path = pathlib.Path(REPO) / "server.py"
        source = server_path.read_text()
        assert '"warnings"' in source

    def test_migrate_credentials_wired_at_startup(self):
        """migrate_remote_credentials called at startup after configure_remote."""
        server_path = pathlib.Path(REPO) / "server.py"
        source = server_path.read_text()
        assert "migrate_remote_credentials" in source


# --- migrate_remote_credentials safety ---

class TestMigrateRemoteCredentials:
    def test_exists(self):
        git_ops = _get_git_ops_module()
        assert hasattr(git_ops, "migrate_remote_credentials")
        assert callable(git_ops.migrate_remote_credentials)

    def test_uses_configure_remote(self):
        git_ops = _get_git_ops_module()
        source = inspect.getsource(git_ops.migrate_remote_credentials)
        assert "configure_remote" in source

    def test_noop_on_clean_origin(self):
        """Clean origin URL (no embedded token) returns True with 'already clean'."""
        git_ops = _get_git_ops_module()
        source = inspect.getsource(git_ops.migrate_remote_credentials)
        assert "already clean" in source.lower() or "Already clean" in source


# --- Startup auto-rescue semantics ---

class TestAutoRescueSemantics:
    def test_auto_rescue_checks_commit_result(self):
        """Auto-rescue must verify git commit actually created a commit."""
        agent_mod = importlib.import_module("ouroboros.agent")
        source = inspect.getsource(agent_mod.OuroborosAgent._check_uncommitted_changes)
        assert "nothing to commit" in source
        assert "capture_output=True" in source

    def test_auto_rescue_does_not_claim_committed_on_noop(self):
        """When git commit produces no new commit, auto_committed must be False."""
        agent_mod = importlib.import_module("ouroboros.agent")
        source = inspect.getsource(agent_mod.OuroborosAgent._check_uncommitted_changes)
        assert "returncode == 0" in source
        assert "auto_committed = True" in source
        idx_committed = source.index("auto_committed = True")
        idx_check = source.index("nothing to commit")
        assert idx_check < idx_committed


# --- ToolContext review state ---

class TestToolContextReviewState:
    def test_review_fields_exist(self):
        from ouroboros.tools.registry import ToolContext
        ctx = ToolContext(
            repo_dir=pathlib.Path("/tmp"),
            drive_root=pathlib.Path("/tmp"),
        )
        assert hasattr(ctx, "_review_advisory")
        assert hasattr(ctx, "_review_iteration_count")
        assert hasattr(ctx, "_review_history")
        assert ctx._review_advisory == []
        assert ctx._review_iteration_count == 0
        assert ctx._review_history == []


# --- Registry sandbox covers repo_write ---

class TestSandboxCoversRepoWrite:
    def test_sandbox_mentions_repo_write(self):
        registry = _get_registry_module()
        source = inspect.getsource(registry.ToolRegistry.execute)
        assert "repo_write" in source

    def test_sandbox_checks_files_param(self):
        """Sandbox must check files array for safety-critical paths."""
        registry = _get_registry_module()
        source = inspect.getsource(registry.ToolRegistry.execute)
        assert "files" in source


# --- index-full instruction fix ---

class TestIndexFullInstruction:
    def test_system_md_warns_against_index_full(self):
        system_md = pathlib.Path(REPO) / "prompts" / "SYSTEM.md"
        content = system_md.read_text()
        assert "Do NOT call" in content or "reserved internal name" in content
        assert "knowledge_list" in content
