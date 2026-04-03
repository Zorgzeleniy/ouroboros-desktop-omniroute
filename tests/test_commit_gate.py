"""Tests for git safety tools, commit gate hardening, and operational polish.

Verifies (Phase 4):
- New tools registered: pull_from_remote, restore_to_head, revert_commit
- SAFETY_CRITICAL_PATHS blocks dangerous operations
- Confirm gates prevent accidental destructive actions
- also_stage parameter in repo_write_commit
- Auto-tagging on version bump
- Credential helper in git_ops (no token in remote URL)
- New tools in CORE_TOOL_NAMES

Verifies (Phase 5):
- Auto-push wired into commit functions
- migrate_remote_credentials exists and is safe
- ARCHITECTURE.md version sync in startup checks
"""
import importlib
import inspect
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_git_module():
    sys.path.insert(0, REPO)
    return importlib.import_module("ouroboros.tools.git")


def _get_registry_module():
    sys.path.insert(0, REPO)
    return importlib.import_module("ouroboros.tools.registry")


def _get_git_ops_module():
    sys.path.insert(0, REPO)
    return importlib.import_module("supervisor.git_ops")


# --- Tool registration tests ---

def test_pull_from_remote_registered():
    git_mod = _get_git_module()
    names = [t.name for t in git_mod.get_tools()]
    assert "pull_from_remote" in names


def test_restore_to_head_registered():
    git_mod = _get_git_module()
    names = [t.name for t in git_mod.get_tools()]
    assert "restore_to_head" in names


def test_revert_commit_registered():
    git_mod = _get_git_module()
    names = [t.name for t in git_mod.get_tools()]
    assert "revert_commit" in names


# --- SAFETY_CRITICAL_PATHS checks ---

def test_restore_to_head_blocks_safety_critical():
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._restore_to_head)
    assert "SAFETY_CRITICAL_PATHS" in source
    assert "RESTORE_BLOCKED" in source


def test_revert_commit_blocks_safety_critical():
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._revert_commit)
    assert "SAFETY_CRITICAL_PATHS" in source
    assert "REVERT_BLOCKED" in source


# --- Confirm gates ---

def test_revert_commit_has_confirm_gate():
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._revert_commit)
    assert "confirm" in source
    assert "Call again with confirm=true" in source


def test_restore_to_head_has_confirm_gate():
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._restore_to_head)
    assert "confirm" in source
    assert "Call again with confirm=true" in source


# --- also_stage ---

def test_also_stage_in_repo_write_commit():
    git_mod = _get_git_module()
    sig = inspect.signature(git_mod._repo_write_commit)
    assert "also_stage" in sig.parameters


def test_also_stage_in_schema():
    git_mod = _get_git_module()
    tools = git_mod.get_tools()
    rwc = next(t for t in tools if t.name == "repo_write_commit")
    props = rwc.schema["parameters"]["properties"]
    assert "also_stage" in props
    assert props["also_stage"]["type"] == "array"


# --- Auto-tagging ---

def test_auto_tag_function_exists():
    git_mod = _get_git_module()
    assert hasattr(git_mod, "_auto_tag_on_version_bump")
    assert callable(git_mod._auto_tag_on_version_bump)


def test_auto_tag_called_in_commit_functions():
    git_mod = _get_git_module()
    for fn_name in ("_repo_write_commit", "_repo_commit_push"):
        source = inspect.getsource(getattr(git_mod, fn_name))
        assert "_auto_tag_on_version_bump" in source, (
            f"{fn_name} must call _auto_tag_on_version_bump"
        )


# --- Credential helper ---

def test_credential_helper_exists():
    git_ops = _get_git_ops_module()
    assert hasattr(git_ops, "_configure_credential_helper")
    assert callable(git_ops._configure_credential_helper)


def test_configure_remote_uses_clean_url():
    """configure_remote must not embed token in the remote URL."""
    git_ops = _get_git_ops_module()
    source = inspect.getsource(git_ops.configure_remote)
    assert "x-access-token" not in source, (
        "configure_remote must use credential helper, not embed token in URL"
    )
    assert "_configure_credential_helper" in source


# --- CORE_TOOL_NAMES ---

def test_new_tools_in_core_tool_names():
    registry = _get_registry_module()
    for name in ("pull_from_remote", "restore_to_head", "revert_commit"):
        assert name in registry.CORE_TOOL_NAMES, (
            f"{name} must be in CORE_TOOL_NAMES"
        )


# --- Pull tool specifics ---

def test_pull_uses_ff_only():
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._ff_pull)
    assert "--ff-only" in source, "Pull must use --ff-only for safety"


def test_pull_fetches_before_merge():
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._ff_pull)
    fetch_pos = source.find("git fetch")
    merge_pos = source.find("git merge")
    assert fetch_pos != -1, "Must call git fetch"
    assert merge_pos != -1, "Must call git merge"
    assert fetch_pos < merge_pos, "Fetch must come before merge"


# --- Revert tool specifics ---

def test_revert_uses_git_lock():
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._revert_commit)
    assert "_acquire_git_lock" in source
    assert "_release_git_lock" in source


def test_revert_aborts_on_failure():
    """On revert failure, git revert --abort must be called."""
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._revert_commit)
    assert '"--abort"' in source and '"revert"' in source


def test_revert_commit_blocks_merge_commits():
    """revert_commit must reject merge commits upfront."""
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._revert_commit)
    assert "merge commit" in source.lower()
    assert "rev-list" in source or "parents" in source


def test_restore_to_head_blocks_safety_critical_full_restore():
    """Full restore (no paths) must check dirty files against SAFETY_CRITICAL_PATHS."""
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._restore_to_head)
    assert "affected_critical" in source or "dirty_files" in source, (
        "Full restore must parse dirty files and check against SAFETY_CRITICAL_PATHS"
    )


def test_also_stage_blocks_safety_critical():
    """also_stage must not stage safety-critical files."""
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._repo_write_commit)
    assert "SAFETY_CRITICAL_PATHS" in source, (
        "repo_write_commit must check also_stage paths against SAFETY_CRITICAL_PATHS"
    )


# --- Auto-push (Phase 5) ---

def test_auto_push_function_exists():
    git_mod = _get_git_module()
    assert hasattr(git_mod, "_auto_push")
    assert callable(git_mod._auto_push)


def test_auto_push_called_in_commit_functions():
    git_mod = _get_git_module()
    for fn_name in ("_repo_write_commit", "_repo_commit_push"):
        source = inspect.getsource(getattr(git_mod, fn_name))
        assert "_auto_push" in source, (
            f"{fn_name} must call _auto_push after successful commit"
        )


def test_auto_push_not_in_rollback_tools():
    """Auto-push must NOT be wired into restore_to_head or revert_commit."""
    git_mod = _get_git_module()
    for fn_name in ("_restore_to_head", "_revert_commit", "_ff_pull"):
        source = inspect.getsource(getattr(git_mod, fn_name))
        assert "_auto_push" not in source, (
            f"{fn_name} must NOT call _auto_push"
        )


def test_auto_push_is_best_effort():
    """_auto_push must catch all exceptions and return a string (never raise)."""
    git_mod = _get_git_module()
    source = inspect.getsource(git_mod._auto_push)
    assert "except Exception" in source
    assert "non-fatal" in source.lower() or "non_fatal" in source.lower()


def test_auto_push_outside_git_lock():
    """Auto-push call must happen AFTER _release_git_lock, not inside the try/finally."""
    git_mod = _get_git_module()
    for fn_name in ("_repo_write_commit", "_repo_commit_push"):
        source = inspect.getsource(getattr(git_mod, fn_name))
        lock_release_pos = source.rfind("_release_git_lock")
        push_pos = source.rfind("_auto_push")
        assert lock_release_pos < push_pos, (
            f"{fn_name}: _auto_push must come after _release_git_lock"
        )


# --- Credential migration (Phase 5) ---

def test_migrate_remote_credentials_exists():
    git_ops = _get_git_ops_module()
    assert hasattr(git_ops, "migrate_remote_credentials")
    assert callable(git_ops.migrate_remote_credentials)


def test_migrate_remote_credentials_uses_configure_remote():
    git_ops = _get_git_ops_module()
    source = inspect.getsource(git_ops.migrate_remote_credentials)
    assert "configure_remote" in source


# --- ARCHITECTURE version sync (Phase 5) ---

def test_version_sync_checks_architecture_md():
    """_check_version_sync must compare VERSION with ARCHITECTURE.md header."""
    sys.path.insert(0, REPO)
    agent_mod = importlib.import_module("ouroboros.agent")
    source = inspect.getsource(agent_mod.OuroborosAgent._check_version_sync)
    assert "ARCHITECTURE" in source
    assert "architecture_version" in source
