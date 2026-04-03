"""Git tools: repo_write, repo_write_commit, repo_commit, git_status, git_diff,
pull_from_remote, restore_to_head, revert_commit.

Includes unified pre-commit review per Bible P8: three models review the staged
diff in parallel using a structured JSON checklist. Review always runs before
commit; enforcement is configurable between blocking and advisory.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry, SAFETY_CRITICAL_PATHS
from ouroboros.utils import utc_now_iso, write_text, safe_relpath, run_cmd

_CONTENT_OMITTED_PREFIX = "<<CONTENT_OMITTED"

log = logging.getLogger(__name__)


def _sanitize_git_error(msg: str) -> str:
    return re.sub(r"(https?://)([^@\s]+@)", r"\1<redacted>@", msg)


def _auto_tag_on_version_bump(repo_dir: pathlib.Path, commit_message: str) -> str:
    try:
        changed = run_cmd(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=repo_dir,
        ).strip().splitlines()
        if "VERSION" not in changed:
            return ""
        version = (repo_dir / "VERSION").read_text(encoding="utf-8").strip()
        if not version:
            return ""
        tag_name = f"v{version}"
        tag_msg = f"v{version}: {commit_message}"
        try:
            run_cmd(["git", "tag", "-a", tag_name, "-m", tag_msg], cwd=repo_dir)
            return f" [tagged: {tag_name}]"
        except Exception as e:
            if "already exists" in str(e):
                return f" [tag {tag_name} already exists]"
            log.warning("Auto-tag failed: %s", e)
            return f" [tag failed: {e}]"
    except Exception as e:
        log.warning("Auto-tag check failed: %s", e)
        return ""


def _auto_push(repo_dir: pathlib.Path) -> str:
    try:
        from supervisor.git_ops import push_to_remote
        ok, msg = push_to_remote()
        if ok:
            return f" [pushed: {msg}]"
        return f" [push skipped: {msg}]"
    except Exception as e:
        log.debug("Auto-push failed (non-fatal): %s", e)
        return " [push failed — will retry later]"


_BINARY_EXTENSIONS = frozenset({
    ".so", ".dylib", ".dll", ".a", ".lib", ".o", ".obj",
    ".pyc", ".pyo", ".whl", ".egg",
})


def _ensure_gitignore(repo_dir) -> None:
    gi = pathlib.Path(repo_dir) / ".gitignore"
    if gi.exists():
        return
    gi.write_text(
        "__pycache__/\n*.pyc\n*.pyo\n*.so\n*.dylib\n*.dll\n"
        "*.dist-info/\nbase_library.zip\n.DS_Store\n",
        encoding="utf-8",
    )


def _unstage_binaries(repo_dir) -> List[str]:
    try:
        staged = run_cmd(["git", "diff", "--cached", "--name-only"], cwd=repo_dir)
    except Exception:
        return []
    removed = []
    for f in staged.strip().splitlines():
        f = f.strip()
        if f and pathlib.Path(f).suffix.lower() in _BINARY_EXTENSIONS:
            try:
                run_cmd(["git", "reset", "HEAD", "--", f], cwd=repo_dir)
                removed.append(f)
            except Exception:
                pass
    return removed


# --- Git lock ---

def _acquire_git_lock(ctx: ToolContext, timeout_sec: int = 120) -> pathlib.Path:
    lock_dir = ctx.drive_path("locks")
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "git.lock"
    stale_sec = 600
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if lock_path.exists():
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > stale_sec:
                    lock_path.unlink()
                    continue
            except (FileNotFoundError, OSError):
                pass
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            try:
                os.write(fd, f"locked_at={utc_now_iso()}\n".encode("utf-8"))
            finally:
                os.close(fd)
            return lock_path
        except FileExistsError:
            time.sleep(0.5)
    raise TimeoutError(f"Git lock not acquired within {timeout_sec}s: {lock_path}")


def _release_git_lock(lock_path: pathlib.Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


# --- Pre-push test gate ---

MAX_TEST_OUTPUT = 8000
_consecutive_test_failures: int = 0


def _log_test_failure(ctx: ToolContext, commit_message: str, test_output: str) -> None:
    from ouroboros.utils import append_jsonl, utc_now_iso
    try:
        append_jsonl(ctx.drive_path("logs") / "events.jsonl", {
            "ts": utc_now_iso(), "type": "commit_test_failure",
            "commit_message": commit_message[:200],
            "test_output": test_output[:2000],
            "consecutive_failures": _consecutive_test_failures,
        })
    except Exception:
        pass


def _run_pre_push_tests(ctx: ToolContext) -> Optional[str]:
    if ctx is None:
        log.warning("_run_pre_push_tests called with ctx=None, skipping tests")
        return None
    if os.environ.get("OUROBOROS_PRE_PUSH_TESTS", "1") != "1":
        return None
    tests_dir = pathlib.Path(ctx.repo_dir) / "tests"
    if not tests_dir.exists():
        return None
    try:
        result = subprocess.run(
            ["pytest", "tests/", "-q", "--tb=line", "--no-header"],
            cwd=ctx.repo_dir, capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return None
        output = result.stdout + result.stderr
        if len(output) > MAX_TEST_OUTPUT:
            output = output[:MAX_TEST_OUTPUT] + "\n...(truncated)..."
        return output
    except subprocess.TimeoutExpired:
        return "⚠️ PRE_PUSH_TEST_ERROR: pytest timed out after 30 seconds"
    except FileNotFoundError:
        return "⚠️ PRE_PUSH_TEST_ERROR: pytest not installed or not found in PATH"
    except Exception as e:
        log.warning(f"Pre-push tests failed with exception: {e}", exc_info=True)
        return f"⚠️ PRE_PUSH_TEST_ERROR: Unexpected error running tests: {e}"


def _git_commit_with_tests(ctx: ToolContext) -> Optional[str]:
    test_error = _run_pre_push_tests(ctx)
    if test_error:
        log.error("Tests failed, blocking commit")
        ctx.last_push_succeeded = False
        return f"⚠️ TESTS_FAILED: Tests failed, commit blocked.\n{test_error}\nFix tests and commit manually."
    return None


# Unified pre-commit review lives in review.py.
from ouroboros.tools.review import (  # noqa: F401
    _run_unified_review,
    _load_checklist_section,
    _CHECKLISTS_PATH,
    _parse_review_json,
)


# --- Post-commit helpers ---

def _post_commit_result(ctx, commit_message, skip_tests, tw_ref):
    global _consecutive_test_failures
    if skip_tests:
        return
    push_error = _git_commit_with_tests(ctx)
    if push_error:
        _consecutive_test_failures += 1
        _log_test_failure(ctx, commit_message, push_error)
        tw_ref[0] = (f"\n\n⚠️ TESTS_FAILED (commit preserved, "
                     f"consecutive failures: {_consecutive_test_failures}):\n{push_error}")
    else:
        _consecutive_test_failures = 0


def _format_commit_result(ctx, commit_message, push_status, test_warning):
    result = f"OK: committed to {ctx.branch_dev}: {commit_message}{push_status}"
    if test_warning:
        result += test_warning
    if ctx._review_advisory:
        result += "\n\n⚠️ Advisory warnings:\n" + "\n".join(f"  - {w}" for w in ctx._review_advisory)
    return result


# --- Tool implementations ---

def _check_shrink_guard(ctx: ToolContext, file_path: str, new_content: str, force: bool = False) -> Optional[str]:
    """Return a warning string if writing new_content would shrink a tracked file by >30%. None if OK."""
    if force:
        return None
    try:
        target = ctx.repo_path(file_path)
        if not target.exists():
            return None
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", safe_relpath(file_path)],
            cwd=str(ctx.repo_dir), capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None
        old_content = target.read_text(encoding="utf-8")
        old_len = len(old_content)
        new_len = len(new_content)
        if old_len > 0 and new_len < old_len * 0.7:
            pct = round(new_len / old_len * 100)
            return (
                f"⚠️ WRITE_BLOCKED: new content for '{file_path}' is {pct}% of original "
                f"({old_len} -> {new_len} chars). This looks like accidental truncation. "
                f"Use str_replace_editor for surgical edits, or pass force=true to confirm "
                f"intentional rewrite."
            )
    except Exception:
        pass
    return None


def _repo_write(ctx: ToolContext, path: str = "", content: str = "",
                files: Optional[List[Dict[str, str]]] = None,
                force: bool = False) -> str:
    """Write file(s) to the repo working directory without committing.

    Use repo_commit afterwards to stage, review, and commit all changes together.
    """
    write_list: List[Dict[str, str]] = []
    if files:
        for entry in files:
            if not isinstance(entry, dict):
                return "⚠️ WRITE_ERROR: each item in files must be {path, content}."
            p = entry.get("path", "").strip()
            c = entry.get("content", "")
            if not p:
                return "⚠️ WRITE_ERROR: every file entry must have a non-empty 'path'."
            write_list.append({"path": p, "content": c})
    elif path and content is not None:
        write_list.append({"path": path.strip(), "content": content})
    else:
        return "⚠️ WRITE_ERROR: provide either (path + content) or files array."

    if not write_list:
        return "⚠️ WRITE_ERROR: nothing to write."

    for e in write_list:
        norm = os.path.normpath(e["path"].strip().lstrip("./"))
        if norm in SAFETY_CRITICAL_PATHS:
            return (
                f"⚠️ SAFETY_VIOLATION: Cannot write safety-critical file: {norm}. "
                f"Protected: {', '.join(sorted(SAFETY_CRITICAL_PATHS))}"
            )
        if isinstance(e["content"], str) and e["content"].strip().startswith(_CONTENT_OMITTED_PREFIX):
            return (
                f"⚠️ WRITE_ERROR: content for '{e['path']}' looks like a compaction marker. "
                "Re-read the file and provide the actual content."
            )

    written = []
    for e in write_list:
        shrink_warning = _check_shrink_guard(ctx, e["path"], e["content"], force=force)
        if shrink_warning:
            return shrink_warning
        try:
            target = ctx.repo_path(e["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text(target, e["content"])
            written.append(f"{e['path']} ({len(e['content'])} chars)")
        except Exception as exc:
            already = ", ".join(written) if written else "(none)"
            return (
                f"⚠️ FILE_WRITE_ERROR on '{e['path']}': {exc}\n"
                f"Successfully written before error: {already}"
            )

    summary = ", ".join(written)
    return (
        f"✅ Written {len(written)} file(s): {summary}\n"
        "Files are on disk but NOT committed. Run repo_commit when ready."
    )


def _str_replace_editor(ctx: ToolContext, path: str, old_str: str, new_str: str) -> str:
    """Replace exactly one occurrence of old_str with new_str in a file.

    Safer than repo_write for existing files: reads the file, verifies old_str
    appears exactly once, performs the replacement, and writes back.
    """
    if not path or not path.strip():
        return "⚠️ STR_REPLACE_ERROR: path is required."
    if not old_str:
        return "⚠️ STR_REPLACE_ERROR: old_str is required (cannot be empty)."

    norm = os.path.normpath(path.strip().lstrip("./"))
    if norm in SAFETY_CRITICAL_PATHS:
        return (
            f"⚠️ SAFETY_VIOLATION: Cannot edit safety-critical file: {norm}. "
            f"Protected: {', '.join(sorted(SAFETY_CRITICAL_PATHS))}"
        )

    try:
        target = ctx.repo_path(path)
    except ValueError as e:
        return f"⚠️ PATH_ERROR: {e}"

    if not target.exists():
        return f"⚠️ STR_REPLACE_ERROR: file not found: {path}"

    try:
        content = target.read_text(encoding="utf-8")
    except Exception as e:
        return f"⚠️ STR_REPLACE_ERROR: cannot read {path}: {e}"

    count = content.count(old_str)
    if count == 0:
        preview = content[:2000]
        return (
            f"⚠️ STR_REPLACE_ERROR: old_str not found in {path}.\n"
            f"File preview (first 2000 chars):\n{preview}"
        )
    if count > 1:
        positions = []
        start = 0
        for i in range(min(count, 5)):
            idx = content.index(old_str, start)
            line_num = content[:idx].count('\n') + 1
            positions.append(f"line {line_num}")
            start = idx + 1
        return (
            f"⚠️ STR_REPLACE_ERROR: old_str found {count} times in {path} "
            f"(must be unique). Occurrences at: {', '.join(positions)}. "
            f"Include more surrounding context in old_str to make it unique."
        )

    new_content = content.replace(old_str, new_str, 1)
    try:
        write_text(target, new_content)
    except Exception as e:
        return f"⚠️ STR_REPLACE_ERROR: write failed for {path}: {e}"

    replacement_line = new_content[:new_content.index(new_str)].count('\n') + 1
    context_start = max(0, replacement_line - 3)
    context_lines = new_content.splitlines()[context_start:replacement_line + len(new_str.splitlines()) + 2]
    context_preview = "\n".join(
        f"{context_start + i + 1:>4}| {line}" for i, line in enumerate(context_lines)
    )

    return (
        f"✅ Replaced in {path} (line {replacement_line}).\n"
        f"Context:\n{context_preview}\n\n"
        "File is on disk but NOT committed. Run repo_commit when ready."
    )


def _repo_write_commit(ctx: ToolContext, path: str, content: str,
                        commit_message: str, skip_tests: bool = False,
                        also_stage: Optional[List[str]] = None) -> str:
    """Legacy compatibility: write one file + commit. Prefer repo_write + repo_commit."""
    global _consecutive_test_failures
    ctx.last_push_succeeded = False
    ctx._review_advisory = []
    if not commit_message.strip():
        return "⚠️ ERROR: commit_message must be non-empty."
    if isinstance(content, str) and content.strip().startswith(_CONTENT_OMITTED_PREFIX):
        return (
            "⚠️ ERROR: content looks like a compaction marker, not real file content. "
            "Re-read the file and provide the actual content."
        )
    shrink_warning = _check_shrink_guard(ctx, path, content)
    if shrink_warning:
        return shrink_warning
    lock = _acquire_git_lock(ctx)
    test_warning_ref = [""]
    try:
        try:
            run_cmd(["git", "checkout", ctx.branch_dev], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (checkout): {_sanitize_git_error(str(e))}"
        try:
            write_text(ctx.repo_path(path), content)
        except Exception as e:
            return f"⚠️ FILE_WRITE_ERROR: {e}"
        try:
            run_cmd(["git", "add", safe_relpath(path)], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (add): {_sanitize_git_error(str(e))}"
        if also_stage:
            for extra in also_stage:
                extra = extra.strip()
                if not extra:
                    continue
                if os.path.normpath(extra.lstrip("./")) in SAFETY_CRITICAL_PATHS:
                    continue
                try:
                    run_cmd(["git", "add", safe_relpath(extra)], cwd=ctx.repo_dir)
                except Exception:
                    pass

        review_err = _run_unified_review(ctx, commit_message)
        if review_err:
            run_cmd(["git", "reset", "HEAD"], cwd=ctx.repo_dir)
            return review_err

        try:
            run_cmd(["git", "commit", "-m", commit_message], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (commit): {_sanitize_git_error(str(e))}"

        _post_commit_result(ctx, commit_message, skip_tests, test_warning_ref)
        tag_info = _auto_tag_on_version_bump(ctx.repo_dir, commit_message) if not test_warning_ref[0] else ""
    finally:
        _release_git_lock(lock)
    push_status = _auto_push(ctx.repo_dir)
    ctx.last_push_succeeded = "[pushed:" in push_status
    return _format_commit_result(ctx, commit_message, push_status + tag_info, test_warning_ref[0])


def _repo_commit_push(ctx: ToolContext, commit_message: str,
                       paths: Optional[List[str]] = None,
                       skip_tests: bool = False,
                       review_rebuttal: str = "") -> str:
    """Stage, review, and commit files with unified pre-commit review."""
    ctx.last_push_succeeded = False
    ctx._review_advisory = []
    if not commit_message.strip():
        return "⚠️ ERROR: commit_message must be non-empty."
    lock = _acquire_git_lock(ctx)
    test_warning_ref = [""]
    try:
        try:
            run_cmd(["git", "checkout", ctx.branch_dev], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (checkout): {_sanitize_git_error(str(e))}"
        if paths:
            try:
                safe_paths = [safe_relpath(p) for p in paths if str(p).strip()]
            except ValueError as e:
                return f"⚠️ PATH_ERROR: {e}"
            add_cmd = ["git", "add"] + safe_paths
        else:
            _ensure_gitignore(ctx.repo_dir)
            add_cmd = ["git", "add", "-A"]
        try:
            run_cmd(add_cmd, cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (add): {_sanitize_git_error(str(e))}"
        if not paths:
            removed = _unstage_binaries(ctx.repo_dir)
            if removed:
                log.warning("Unstaged %d binary files: %s", len(removed), removed)
        try:
            status = run_cmd(["git", "status", "--porcelain"], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (status): {_sanitize_git_error(str(e))}"
        if not status.strip():
            return "⚠️ GIT_NO_CHANGES: nothing to commit."

        review_err = _run_unified_review(ctx, commit_message, review_rebuttal=review_rebuttal)
        if review_err:
            run_cmd(["git", "reset", "HEAD"], cwd=ctx.repo_dir)
            return review_err

        try:
            run_cmd(["git", "commit", "-m", commit_message], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (commit): {_sanitize_git_error(str(e))}"

        _post_commit_result(ctx, commit_message, skip_tests, test_warning_ref)
        tag_info = _auto_tag_on_version_bump(ctx.repo_dir, commit_message) if not test_warning_ref[0] else ""
    finally:
        _release_git_lock(lock)
    push_status = _auto_push(ctx.repo_dir)
    ctx.last_push_succeeded = "[pushed:" in push_status
    result = _format_commit_result(ctx, commit_message, push_status + tag_info, test_warning_ref[0])
    if paths is not None:
        try:
            untracked = run_cmd(["git", "ls-files", "--others", "--exclude-standard"], cwd=ctx.repo_dir)
            if untracked.strip():
                files = ", ".join(untracked.strip().split("\n"))
                result += f"\n⚠️ WARNING: untracked files remain: {files}"
        except Exception:
            pass
    return result


def _git_status(ctx: ToolContext) -> str:
    try:
        return run_cmd(["git", "status", "--porcelain"], cwd=ctx.repo_dir)
    except Exception as e:
        return f"⚠️ GIT_ERROR: {_sanitize_git_error(str(e))}"


def _git_diff(ctx: ToolContext, staged: bool = False) -> str:
    try:
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        return run_cmd(cmd, cwd=ctx.repo_dir)
    except Exception as e:
        return f"⚠️ GIT_ERROR: {_sanitize_git_error(str(e))}"


# ---------------------------------------------------------------------------
# pull_from_remote — FF-only pull (fetch + merge)
# ---------------------------------------------------------------------------

def _ff_pull(repo_dir: pathlib.Path) -> str:
    try:
        branch = run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir,
        ).strip()
    except Exception as e:
        return f"⚠️ PULL_ERROR: Could not determine current branch: {e}"
    if not branch or branch == "HEAD":
        return "⚠️ PULL_ERROR: Not on a named branch (detached HEAD). Cannot pull."
    try:
        run_cmd(["git", "fetch", "origin"], cwd=repo_dir)
    except Exception as e:
        return f"⚠️ PULL_ERROR: git fetch failed: {_sanitize_git_error(str(e))}"
    try:
        before_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_dir).strip()
        remote_sha = run_cmd(
            ["git", "rev-parse", f"origin/{branch}"], cwd=repo_dir,
        ).strip()
    except Exception as e:
        return f"⚠️ PULL_ERROR: Could not resolve SHAs: {e}"
    if before_sha == remote_sha:
        return f"Already up to date. HEAD={before_sha[:8]} matches origin/{branch}."
    try:
        new_commits = run_cmd(
            ["git", "log", "--oneline", f"HEAD..origin/{branch}"], cwd=repo_dir,
        ).strip()
    except Exception:
        new_commits = "(could not list commits)"
    try:
        run_cmd(["git", "merge", "--ff-only", f"origin/{branch}"], cwd=repo_dir)
    except Exception as e:
        err = str(e).strip()
        if "Not possible to fast-forward" in err or "diverged" in err.lower():
            return (
                f"⚠️ PULL_ERROR: Branches have diverged — cannot fast-forward.\n"
                f"Local HEAD: {before_sha[:8]}, origin/{branch}: {remote_sha[:8]}\n"
                "Manual resolution needed."
            )
        return f"⚠️ PULL_ERROR: git merge --ff-only failed: {_sanitize_git_error(err)}"
    try:
        after_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_dir).strip()
    except Exception:
        after_sha = remote_sha
    lines = [
        f"Pulled origin/{branch}: {before_sha[:8]} → {after_sha[:8]}",
        "", "New commits:",
    ]
    for line in (new_commits or "(none)").splitlines():
        lines.append(f"  {line}")
    return "\n".join(lines)


def _pull_from_remote(ctx: ToolContext) -> str:
    return _ff_pull(pathlib.Path(ctx.repo_dir))


# ---------------------------------------------------------------------------
# restore_to_head — discard uncommitted changes (safe: returns to HEAD)
# ---------------------------------------------------------------------------

def _restore_to_head(ctx: ToolContext, confirm: bool = False,
                     paths: Optional[List[str]] = None) -> str:
    repo_dir = pathlib.Path(ctx.repo_dir)
    try:
        status = run_cmd(["git", "status", "--porcelain"], cwd=repo_dir).strip()
    except Exception as e:
        return f"⚠️ RESTORE_ERROR: git status failed: {e}"
    if not status:
        return "Nothing to restore — working directory is already clean."
    dirty_files = [line[3:].strip().split(" -> ")[-1]
                   for line in status.splitlines() if line.strip()]
    affected_critical = [
        os.path.normpath(f) for f in dirty_files
        if os.path.normpath(f) in SAFETY_CRITICAL_PATHS
    ]
    if paths:
        for p in paths:
            norm = os.path.normpath(p.strip().lstrip("./"))
            if norm in SAFETY_CRITICAL_PATHS:
                return (
                    f"⚠️ RESTORE_BLOCKED: Cannot restore safety-critical file: {norm}. "
                    f"Protected: {', '.join(sorted(SAFETY_CRITICAL_PATHS))}"
                )
    elif affected_critical:
        return (
            f"⚠️ RESTORE_BLOCKED: Uncommitted changes touch safety-critical file(s): "
            f"{', '.join(affected_critical)}. "
            f"Use paths= to restore specific non-critical files, or resolve manually."
        )
    if not confirm:
        try:
            diff_stat = run_cmd(["git", "diff", "--stat"], cwd=repo_dir).strip()
        except Exception:
            diff_stat = "(could not generate diff)"
        try:
            untracked = run_cmd(
                ["git", "ls-files", "--others", "--exclude-standard"], cwd=repo_dir,
            ).strip()
        except Exception:
            untracked = ""
        preview = ["Uncommitted changes that will be lost:", "", diff_stat]
        if untracked:
            preview.append("")
            preview.append("Untracked files that will be removed:")
            for f in untracked.splitlines()[:15]:
                preview.append(f"  {f}")
        preview.append("")
        preview.append("Call again with confirm=true to proceed.")
        return "\n".join(preview)
    if paths:
        safe_paths = [os.path.normpath(p.strip().lstrip("./")) for p in paths if p.strip()]
        if not safe_paths:
            return "⚠️ RESTORE_ERROR: No valid paths provided."
        try:
            run_cmd(["git", "checkout", "HEAD", "--"] + safe_paths, cwd=repo_dir)
        except Exception as e:
            return f"⚠️ RESTORE_ERROR: git checkout failed: {e}"
        try:
            run_cmd(["git", "clean", "-fd", "--"] + safe_paths, cwd=repo_dir)
        except Exception:
            pass
        return f"Restored {len(safe_paths)} path(s) to HEAD."
    else:
        try:
            run_cmd(["git", "checkout", "HEAD", "--", "."], cwd=repo_dir)
        except Exception as e:
            return f"⚠️ RESTORE_ERROR: git checkout failed: {e}"
        try:
            run_cmd(["git", "clean", "-fd"], cwd=repo_dir)
        except Exception:
            pass
        return "All uncommitted changes discarded. Working directory matches HEAD."


# ---------------------------------------------------------------------------
# revert_commit — create a new commit undoing a previous one (no history rewrite)
# ---------------------------------------------------------------------------

def _revert_commit(ctx: ToolContext, sha: str, confirm: bool = False) -> str:
    repo_dir = pathlib.Path(ctx.repo_dir)
    sha = sha.strip()
    if not sha:
        return "⚠️ REVERT_ERROR: sha parameter is required."
    try:
        full_sha = run_cmd(
            ["git", "rev-parse", "--verify", sha], cwd=repo_dir,
        ).strip()
    except Exception:
        return f"⚠️ REVERT_ERROR: Commit '{sha}' not found."
    try:
        parents = run_cmd(
            ["git", "rev-list", "--parents", "-1", full_sha], cwd=repo_dir,
        ).strip().split()
    except Exception:
        parents = [full_sha]
    if len(parents) > 2:
        return (
            f"⚠️ REVERT_ERROR: Commit {sha[:8]} is a merge commit ({len(parents)-1} parents). "
            "git revert on merge commits requires specifying a parent."
        )
    try:
        changed_files = run_cmd(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", full_sha],
            cwd=repo_dir,
        ).strip().splitlines()
    except Exception:
        changed_files = []
    for f in changed_files:
        norm = os.path.normpath(f.strip())
        if norm in SAFETY_CRITICAL_PATHS:
            return (
                f"⚠️ REVERT_BLOCKED: Commit {sha[:8]} touches safety-critical file: {norm}. "
                "Reverting it could modify protected files."
            )
    try:
        commit_msg = run_cmd(
            ["git", "log", "-1", "--format=%s", full_sha], cwd=repo_dir,
        ).strip()
    except Exception:
        commit_msg = "(unknown)"
    if not confirm:
        try:
            diff_stat = run_cmd(
                ["git", "diff", f"{full_sha}^..{full_sha}", "--stat"], cwd=repo_dir,
            ).strip()
        except Exception:
            diff_stat = "(could not generate diff)"
        return (
            f"This will revert commit {full_sha[:8]}:\n"
            f"  Message: {commit_msg}\n"
            f"  Files changed:\n{diff_stat}\n\n"
            "A new commit will be created that undoes these changes.\n"
            "Call again with confirm=true to proceed."
        )
    try:
        status = run_cmd(["git", "status", "--porcelain"], cwd=repo_dir).strip()
    except Exception:
        status = ""
    if status:
        return (
            "⚠️ REVERT_ERROR: Working directory is not clean.\n"
            "Commit or discard changes first (use restore_to_head), then retry."
        )
    lock = _acquire_git_lock(ctx)
    try:
        try:
            run_cmd(["git", "revert", "--no-edit", full_sha], cwd=repo_dir)
        except Exception as e:
            try:
                run_cmd(["git", "revert", "--abort"], cwd=repo_dir)
            except Exception:
                pass
            return f"⚠️ REVERT_ERROR: git revert failed: {e}"
    finally:
        _release_git_lock(lock)
    return f"Reverted commit {full_sha[:8]}: {commit_msg}\nNew revert commit created."


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("repo_write", {
            "name": "repo_write",
            "description": (
                "Write file(s) to repo working directory WITHOUT committing. "
                "Use for all code edits — single-file or multi-file. "
                "After writing all files, call repo_commit to stage, review, and commit. "
                "Supports: (1) single file via path+content, "
                "(2) multi-file via files array [{path, content}, ...]."
            ),
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "File path (single-file mode). Ignored if 'files' is provided."},
                "content": {"type": "string", "description": "File content (single-file mode). Ignored if 'files' is provided."},
                "files": {"type": "array", "items": {"type": "object", "properties": {
                    "path": {"type": "string"}, "content": {"type": "string"},
                }, "required": ["path", "content"]},
                    "description": "Array of {path, content} pairs (multi-file mode)."},
                "force": {"type": "boolean", "default": False, "description": "Bypass shrink guard for intentional full rewrites."},
            }, "required": []},
        }, _repo_write, is_code_tool=True),
        ToolEntry("str_replace_editor", {
            "name": "str_replace_editor",
            "description": (
                "Surgical edit: replace exactly one occurrence of old_str with new_str in a file. "
                "Safer than repo_write for existing files — reads the file, verifies the match is unique, "
                "performs the replacement, and shows context. Use for all edits to existing tracked files. "
                "For new files or intentional full rewrites, use repo_write instead."
            ),
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "File path relative to repo root"},
                "old_str": {"type": "string", "description": "Exact string to find (must appear exactly once)"},
                "new_str": {"type": "string", "description": "Replacement string"},
            }, "required": ["path", "old_str", "new_str"]},
        }, _str_replace_editor, is_code_tool=True),
        ToolEntry("repo_write_commit", {
            "name": "repo_write_commit",
            "description": (
                "Write one file + commit to ouroboros branch. "
                "Legacy compatibility — prefer repo_write + repo_commit for multi-file changes."
            ),
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "commit_message": {"type": "string"},
                "skip_tests": {"type": "boolean", "default": False, "description": "Skip pre-commit tests."},
                "also_stage": {"type": "array", "items": {"type": "string"}, "description": "Additional files to stage"},
            }, "required": ["path", "content", "commit_message"]},
        }, _repo_write_commit, is_code_tool=True),
        ToolEntry("repo_commit", {
            "name": "repo_commit",
            "description": (
                "Commit already-changed files. Includes unified pre-commit multi-model review "
                "before commit, with configurable Advisory/Blocking enforcement."
            ),
            "parameters": {"type": "object", "properties": {
                "commit_message": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Files to add (empty = git add -A)"},
                "skip_tests": {"type": "boolean", "default": False, "description": "Skip pre-commit tests."},
                "review_rebuttal": {"type": "string", "default": "",
                    "description": "If previous commit was blocked by reviewers and you disagree, include counter-argument."},
            }, "required": ["commit_message"]},
        }, _repo_commit_push, is_code_tool=True),
        ToolEntry("git_status", {
            "name": "git_status",
            "description": "git status --porcelain",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _git_status, is_code_tool=True),
        ToolEntry("git_diff", {
            "name": "git_diff",
            "description": "git diff (use staged=true to see staged changes after git add)",
            "parameters": {"type": "object", "properties": {
                "staged": {"type": "boolean", "default": False, "description": "If true, show staged changes (--staged)"},
            }, "required": []},
        }, _git_diff, is_code_tool=True),
        ToolEntry("pull_from_remote", {
            "name": "pull_from_remote",
            "description": "Fetch from origin and fast-forward merge. Safe: never rewrites history.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _pull_from_remote, is_code_tool=True),
        ToolEntry("restore_to_head", {
            "name": "restore_to_head",
            "description": "Discard uncommitted changes, restoring to last committed state (HEAD).",
            "parameters": {"type": "object", "properties": {
                "confirm": {"type": "boolean", "description": "Must be true to execute."},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Specific files to restore"},
            }, "required": ["confirm"]},
        }, _restore_to_head, is_code_tool=True),
        ToolEntry("revert_commit", {
            "name": "revert_commit",
            "description": "Revert a specific commit by creating a new undo commit. Safe: no history rewrite.",
            "parameters": {"type": "object", "properties": {
                "sha": {"type": "string", "description": "Commit SHA to revert"},
                "confirm": {"type": "boolean", "description": "Must be true to execute."},
            }, "required": ["sha", "confirm"]},
        }, _revert_commit, is_code_tool=True),
    ]
