"""Claude Code advisory pre-review gate.

Runs a read-only Claude Code review of the current worktree BEFORE the unified
multi-model pre-commit review. Advisory findings are non-blocking by themselves;
only the *absence* of a fresh matching advisory run blocks repo_commit.

Workflow:
  edit files
  -> advisory_pre_review(commit_message="...")   ← this module
  -> fix obvious issues
  -> repo_commit(...)                            ← existing unified review still runs

Tool surface:
  advisory_pre_review   run a fresh advisory review
  review_status         show recent advisory run history (read-only diagnostic)
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import shutil
from typing import List, Optional

from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.review_state import (
    AdvisoryRunRecord,
    AdvisoryReviewState,
    compute_snapshot_hash,
    format_status_section,
    load_state,
    save_state,
    _utc_now,
)
from ouroboros.tools.review_helpers import (
    load_checklist_section,
    build_touched_file_pack,
    build_goal_section,
    build_scope_section,
)
from ouroboros.utils import append_jsonl, utc_now_iso

log = logging.getLogger(__name__)

_CLAUDE_CODE_TIMEOUT_SEC = 120  # Advisory run budget — keep it fast
_MAX_DIFF_CHARS = 80_000        # Explicit omission note beyond this


def _find_claude_bin() -> Optional[str]:
    """Locate the claude binary using the same PATH augmentation as shell.py."""
    try:
        from ouroboros.tools.shell import _ensure_path
        _ensure_path()
    except Exception:
        pass
    return shutil.which("claude")


def _load_doc(repo_dir: pathlib.Path, relpath: str, fallback: str = "") -> str:
    try:
        p = repo_dir / relpath
        if p.is_file():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return fallback


def _get_staged_diff(repo_dir: pathlib.Path) -> str:
    """Return staged diff + unstaged diff of changed files.

    If the combined diff exceeds _MAX_DIFF_CHARS, an explicit omission note
    is appended (no silent truncation).
    """
    try:
        staged = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
        ).stdout or ""
        unstaged = subprocess.run(
            ["git", "diff"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
        ).stdout or ""
        combined = (staged + unstaged).strip()
        if len(combined) > _MAX_DIFF_CHARS:
            total_len = len(combined)
            combined = combined[:_MAX_DIFF_CHARS] + (
                f"\n\n⚠️ OMISSION NOTE: diff truncated at {_MAX_DIFF_CHARS:,} of {total_len:,} chars. "
                "Use Read/Grep tools to inspect the omitted portions if needed."
            )
        return combined or "(no unstaged/staged changes found)"
    except Exception:
        return "(failed to retrieve diff)"


def _get_changed_file_list(repo_dir: pathlib.Path) -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            return "\n".join(lines) if lines else "(clean — no changed files)"
        return "(git status failed)"
    except Exception:
        return "(git status error)"


def _build_advisory_prompt(
    repo_dir: pathlib.Path,
    commit_message: str,
    goal: str = "",
    scope: str = "",
    paths: Optional[List[str]] = None,
) -> str:
    """Build the read-only advisory review prompt.

    Includes: BIBLE.md, CHECKLISTS.md, DEVELOPMENT.md, git status, staged diff,
    touched file pack, goal/scope sections.
    Does NOT include raw chat/task context.
    """
    bible = _load_doc(repo_dir, "BIBLE.md", "(BIBLE.md not found)")
    try:
        checklists = load_checklist_section("Repo Commit Checklist")
    except Exception:
        checklists = _load_doc(repo_dir, "docs/CHECKLISTS.md", "(CHECKLISTS.md not found)")
    dev_guide = _load_doc(repo_dir, "docs/DEVELOPMENT.md", "(DEVELOPMENT.md not found)")
    diff = _get_staged_diff(repo_dir)
    changed_files = _get_changed_file_list(repo_dir)

    touched_pack, _omitted = build_touched_file_pack(repo_dir, paths)
    goal_section = build_goal_section(goal, scope, commit_message)
    scope_section = build_scope_section(scope)

    prompt = f"""\
You are performing an ADVISORY pre-commit review of an Ouroboros self-modifying AI agent codebase.

## Your role
- Review the current working tree changes (git diff / git status).
- Use ONLY Read, Grep, Glob tools — do NOT edit or run any files.
- Return a STRUCTURED JSON array of findings. No prose, no fences — only a JSON array.

## Output format
Return ONLY a JSON array. Each element:
{{
  "item": "<checklist item name>",
  "verdict": "PASS" | "FAIL",
  "severity": "critical" | "advisory",
  "reason": "<one-line explanation>"
}}

## CHECKLISTS.md (What to review)

{checklists}

{scope_section}

{goal_section}

## DEVELOPMENT.md (Engineering standards)

{dev_guide}

## BIBLE.md (Constitutional context — top priority)

{bible}

## Commit message

{commit_message}

## Changed files (git status --porcelain)

{changed_files}

## Current touched files

{touched_pack}

## Staged diff

{diff}

## Instructions
1. Read all changed files mentioned in the diff using the Read tool.
2. Check each item from the "Repo Commit Checklist" in CHECKLISTS.md.
3. Pay special attention to BIBLE.md compliance (item 1: bible_compliance).
4. Output ONLY the JSON array — no markdown, no commentary outside the JSON.
"""
    return prompt


def _run_claude_advisory(
    repo_dir: pathlib.Path,
    commit_message: str,
    ctx: ToolContext,
    goal: str = "",
    scope: str = "",
    paths: Optional[List[str]] = None,
) -> tuple[list, str]:
    """Run the advisory review via Claude Code CLI.

    Returns (items: list, raw_result: str).
    items is a list of review finding dicts (may be empty on error).
    raw_result is the raw CLI output string.
    """
    claude_bin = _find_claude_bin()
    if not claude_bin:
        return [], "⚠️ ADVISORY_ERROR: claude binary not found. Run ensure_claude_cli first."

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return [], "⚠️ ADVISORY_ERROR: ANTHROPIC_API_KEY not set."

    prompt = _build_advisory_prompt(repo_dir, commit_message, goal=goal, scope=scope, paths=paths)

    cmd = [
        claude_bin,
        "-p", prompt,
        "--output-format", "json",
        "--max-turns", "8",
        "--tools", "Read,Grep,Glob",
        "--no-session-persistence",
        "--model", "opus",
    ]

    # Prefer bypassPermissions; fall back to legacy flag
    perm_mode = os.environ.get("OUROBOROS_CLAUDE_CODE_PERMISSION_MODE", "bypassPermissions").strip()
    cmd_primary = cmd + ["--permission-mode", perm_mode]
    cmd_legacy = cmd + ["--dangerously-skip-permissions"]

    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = api_key
    try:
        from ouroboros.tools.shell import _build_augmented_path
        env["PATH"] = _build_augmented_path()
    except Exception:
        pass

    def _run_cmd(cmd_variant: list):
        try:
            from ouroboros.tools.shell import _tracked_subprocess_run
        except Exception:
            import subprocess as _sp

            class _compat:
                @staticmethod
                def _tracked_subprocess_run(c, **kw):
                    return _sp.run(c, **kw)
            _tracked_subprocess_run = _compat._tracked_subprocess_run

        return _tracked_subprocess_run(
            cmd_variant,
            cwd=str(repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_CLAUDE_CODE_TIMEOUT_SEC,
            env=env,
        )

    try:
        res = _run_cmd(cmd_primary)
        # Fallback if --permission-mode is not recognized
        if res.returncode != 0:
            combined = ((res.stdout or "") + (res.stderr or "")).lower()
            if "--permission-mode" in combined and any(
                m in combined for m in ("unknown option", "unknown argument", "unrecognized option")
            ):
                res = _run_cmd(cmd_legacy)
    except subprocess.TimeoutExpired:
        return [], f"⚠️ ADVISORY_ERROR: Claude Code timed out after {_CLAUDE_CODE_TIMEOUT_SEC}s."
    except Exception as e:
        return [], f"⚠️ ADVISORY_ERROR: subprocess failed: {type(e).__name__}: {e}"

    stdout = (res.stdout or "").strip()
    stderr = (res.stderr or "").strip()

    if res.returncode != 0:
        raw = f"exit_code={res.returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        return [], f"⚠️ ADVISORY_ERROR: Claude Code exited {res.returncode}.\n{raw}"

    # Parse JSON from CLI output (may be wrapped in Claude's JSON envelope)
    items = _parse_advisory_output(stdout)
    return items, stdout


def _parse_advisory_output(stdout: str) -> list:
    """Extract the JSON findings array from Claude CLI output."""
    # Try direct parse first
    text = stdout.strip()

    # Unwrap Claude Code JSON envelope: {"result": "...", ...}
    try:
        outer = json.loads(text)
        if isinstance(outer, dict) and "result" in outer:
            text = str(outer["result"]).strip()
        elif isinstance(outer, list):
            return outer
    except (json.JSONDecodeError, ValueError):
        pass

    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    # Try direct parse of the inner result
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    # Find embedded JSON array
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, list):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass

    return []


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def _audit_bypass(ctx: ToolContext, snapshot_hash: str, commit_message: str,
                  bypass_reason: str, task_id: str) -> None:
    try:
        append_jsonl(ctx.drive_logs() / "events.jsonl", {
            "ts": utc_now_iso(),
            "type": "advisory_pre_review_bypassed",
            "snapshot_hash": snapshot_hash,
            "commit_message": commit_message[:200],
            "bypass_reason": bypass_reason,
            "task_id": task_id,
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

def _handle_advisory_pre_review(
    ctx: ToolContext,
    commit_message: str = "",
    skip_advisory_pre_review: bool = False,
    goal: str = "",
    scope: str = "",
    paths: Optional[List[str]] = None,
) -> str:
    """Run an advisory pre-commit review via Claude Code CLI (read-only).

    Stores result in durable state so repo_commit can verify freshness.
    Returns structured JSON with findings + status.
    """
    repo_dir = pathlib.Path(ctx.repo_dir)
    drive_root = pathlib.Path(ctx.drive_root)

    snapshot_hash = compute_snapshot_hash(repo_dir, commit_message, paths=paths)
    state = load_state(drive_root)
    task_id = str(getattr(ctx, "task_id", "") or "")

    # Auto-bypass if Anthropic key is absent — audit it transparently
    if not os.environ.get("ANTHROPIC_API_KEY", ""):
        reason = "ANTHROPIC_API_KEY not set — auto-bypassed"
        _audit_bypass(ctx, snapshot_hash, commit_message, reason, task_id)
        run = AdvisoryRunRecord(
            snapshot_hash=snapshot_hash,
            commit_message=commit_message,
            status="bypassed",
            ts=_utc_now(),
            bypass_reason=reason,
            bypassed_by_task=task_id,
        )
        state.add_run(run)
        save_state(drive_root, state)
        return json.dumps({
            "status": "bypassed",
            "snapshot_hash": snapshot_hash,
            "bypass_reason": reason,
            "message": (
                "⚠️ ANTHROPIC_API_KEY is not set — advisory review skipped automatically. "
                "Bypass has been durably audited in events.jsonl. "
                "Set ANTHROPIC_API_KEY in Settings to enable Claude Code advisory reviews."
            ),
        }, ensure_ascii=False, indent=2)

    # Handle explicit bypass
    if skip_advisory_pre_review:
        reason = "explicit skip_advisory_pre_review=True"
        _audit_bypass(ctx, snapshot_hash, commit_message, reason, task_id)
        run = AdvisoryRunRecord(
            snapshot_hash=snapshot_hash,
            commit_message=commit_message,
            status="bypassed",
            ts=_utc_now(),
            bypass_reason=reason,
            bypassed_by_task=task_id,
        )
        state.add_run(run)
        save_state(drive_root, state)
        return json.dumps({
            "status": "bypassed",
            "snapshot_hash": snapshot_hash,
            "bypass_reason": reason,
            "message": "Advisory review bypassed. Bypass has been durably audited.",
        }, ensure_ascii=False, indent=2)

    # Check if we already have a fresh run for this snapshot
    existing = state.find_by_hash(snapshot_hash)
    if existing and existing.status in ("fresh", "bypassed"):
        return json.dumps({
            "status": "already_fresh",
            "snapshot_hash": snapshot_hash,
            "ts": existing.ts,
            "items": existing.items,
            "message": "A fresh advisory run already exists for this snapshot. Proceed with repo_commit.",
        }, ensure_ascii=False, indent=2)

    # Run the advisory review
    ctx.emit_progress_fn("Running advisory pre-review (Claude Code, read-only)...")
    changed_files = _get_changed_file_list(repo_dir)
    items, raw_result = _run_claude_advisory(repo_dir, commit_message, ctx, goal=goal, scope=scope, paths=paths)

    # Handle errors from the CLI
    if raw_result.startswith("⚠️ ADVISORY_ERROR"):
        return json.dumps({
            "status": "error",
            "snapshot_hash": snapshot_hash,
            "error": raw_result,
            "message": (
                "Advisory review failed to run. Fix the error and retry, "
                "or use skip_advisory_pre_review=True to bypass (will be audited)."
            ),
        }, ensure_ascii=False, indent=2)

    # Classify findings
    critical_fails = [i for i in items if isinstance(i, dict)
                      and str(i.get("verdict", "")).upper() == "FAIL"
                      and str(i.get("severity", "")).lower() == "critical"]
    advisory_fails = [i for i in items if isinstance(i, dict)
                      and str(i.get("verdict", "")).upper() == "FAIL"
                      and str(i.get("severity", "")).lower() != "critical"]

    snapshot_summary = f"{changed_files.count(chr(10)) + 1} file(s) changed"

    run = AdvisoryRunRecord(
        snapshot_hash=snapshot_hash,
        commit_message=commit_message,
        status="fresh",
        ts=_utc_now(),
        items=items,
        snapshot_summary=snapshot_summary,
        raw_result=raw_result,
    )
    state.add_run(run)
    save_state(drive_root, state)

    # Build human-readable summary
    findings_summary: List[str] = []
    for item in critical_fails:
        findings_summary.append(f"  CRITICAL [{item.get('item','?')}]: {item.get('reason','')}")
    for item in advisory_fails:
        findings_summary.append(f"  ADVISORY [{item.get('item','?')}]: {item.get('reason','')}")

    result = {
        "status": "fresh",
        "snapshot_hash": snapshot_hash,
        "ts": run.ts,
        "items": items,
        "critical_count": len(critical_fails),
        "advisory_count": len(advisory_fails),
        "snapshot_summary": snapshot_summary,
        "message": (
            f"Advisory review complete. {len(critical_fails)} critical, "
            f"{len(advisory_fails)} advisory findings. "
            "Fix issues and run repo_commit when ready."
        ),
    }
    if findings_summary:
        result["findings"] = findings_summary

    return json.dumps(result, ensure_ascii=False, indent=2)


def _handle_review_status(ctx: ToolContext) -> str:
    """Show recent advisory pre-review run history (read-only diagnostic)."""
    drive_root = pathlib.Path(ctx.drive_root)
    state = load_state(drive_root)

    if not state.runs:
        return json.dumps({
            "status": "no_runs",
            "message": (
                "No advisory pre-review runs recorded. "
                "Run advisory_pre_review(commit_message='...') before repo_commit."
            ),
        }, ensure_ascii=False, indent=2)

    runs_data = []
    for run in reversed(state.runs[-5:]):
        findings = [i for i in (run.items or []) if isinstance(i, dict)
                    and str(i.get("verdict", "")).upper() == "FAIL"]
        critical = [i for i in findings if str(i.get("severity", "")).lower() == "critical"]
        runs_data.append({
            "snapshot_hash": run.snapshot_hash[:12],
            "commit_message": run.commit_message[:80],
            "status": run.status,
            "ts": run.ts[:16],
            "critical_findings": len(critical),
            "total_findings": len(findings),
            "snapshot_summary": run.snapshot_summary,
            "bypass_reason": run.bypass_reason or None,
        })

    latest = state.latest()
    return json.dumps({
        "latest_status": latest.status if latest else "none",
        "latest_hash": latest.snapshot_hash[:12] if latest else None,
        "runs": runs_data,
        "message": (
            f"Latest advisory run: {latest.status if latest else 'none'}. "
            "Use advisory_pre_review(commit_message='...') to run a fresh review."
        ),
    }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def get_tools() -> list:
    return [
        ToolEntry(
            name="advisory_pre_review",
            schema={
                "name": "advisory_pre_review",
                "description": (
                    "Run an advisory pre-commit review via Claude Code CLI (read-only: Read, Grep, Glob only). "
                    "MUST be called before repo_commit. Returns structured JSON findings. "
                    "Findings are advisory (non-blocking), but the absence of a fresh matching "
                    "advisory run will block repo_commit. "
                    "Workflow: edit -> advisory_pre_review(...) -> fix issues -> repo_commit(...). "
                    "Use skip_advisory_pre_review=True to bypass (bypass is durably audited)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "commit_message": {
                            "type": "string",
                            "description": "Intended commit message. Used to bind the advisory run to this specific commit.",
                        },
                        "skip_advisory_pre_review": {
                            "type": "boolean",
                            "default": False,
                            "description": (
                                "Explicitly bypass the advisory review. "
                                "Bypass is durably audited in events.jsonl. "
                                "Default: False."
                            ),
                        },
                        "goal": {
                            "type": "string",
                            "description": "High-level goal of this change. Used to judge completeness.",
                        },
                        "scope": {
                            "type": "string",
                            "description": "Declared scope boundary. Issues outside scope are advisory-only.",
                        },
                        "paths": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Explicit list of changed file paths. Auto-detected from git status if omitted.",
                        },
                    },
                    "required": ["commit_message"],
                },
            },
            handler=_handle_advisory_pre_review,
        ),
        ToolEntry(
            name="review_status",
            schema={
                "name": "review_status",
                "description": (
                    "Show recent advisory pre-review run history. "
                    "Read-only diagnostic — use to check if a fresh advisory run exists "
                    "before calling repo_commit."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            handler=_handle_review_status,
        ),
    ]
