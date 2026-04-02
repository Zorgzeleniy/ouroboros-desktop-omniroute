"""Blocking scope reviewer for Ouroboros commit pipeline.

Runs AFTER the triad diff review. Single-model (configurable via OUROBOROS_SCOPE_REVIEW_MODEL,
fail-closed: timeout, parse error, API failure, or incomplete context all block.

Role: completeness, forgotten touchpoints, cross-surface consistency,
incomplete migrations, intent mismatch. NOT a duplicate of line-by-line diff review.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from typing import Any, Dict, List, Optional

from ouroboros.llm import LLMClient
from ouroboros.tools.registry import ToolContext
from ouroboros.tools.review_helpers import (
    build_broader_repo_pack,
    build_goal_section,
    build_scope_section,
    build_touched_file_pack,
    load_checklist_section,
)
from ouroboros.utils import run_cmd, utc_now_iso, append_jsonl

log = logging.getLogger(__name__)

_SCOPE_MODEL_DEFAULT = "anthropic/claude-opus-4.6"
_SCOPE_MAX_TOKENS = 8192


def _get_scope_model() -> str:
    """Return the configured scope review model (env → settings default)."""
    return (
        os.environ.get("OUROBOROS_SCOPE_REVIEW_MODEL", "").strip()
        or _SCOPE_MODEL_DEFAULT
    )

_SCOPE_PREAMBLE = (
    "You are a pre-commit reviewer for Ouroboros, a self-modifying AI agent.\n"
    "Its Constitution is BIBLE.md. Its engineering handbook is DEVELOPMENT.md.\n"
)


def _load_dev_guide(repo_dir: pathlib.Path) -> str:
    try:
        p = repo_dir / "docs" / "DEVELOPMENT.md"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return "(DEVELOPMENT.md not found)"


def _build_review_history_section(history: list) -> str:
    if not history:
        return ""
    lines = ["## Previous triad review rounds\n"]
    for entry in history[-3:]:
        lines.append(f"### Round {entry.get('attempt', '?')}")
        if entry.get("critical"):
            for f in entry["critical"]:
                lines.append(f"- CRITICAL: {f}")
        if entry.get("advisory"):
            for f in entry["advisory"][:5]:
                lines.append(f"- Advisory: {f}")
        lines.append("")
    return "\n".join(lines)


def _build_scope_prompt(
    repo_dir: pathlib.Path,
    commit_message: str,
    goal: str = "",
    scope: str = "",
    review_rebuttal: str = "",
    review_history: Optional[list] = None,
) -> tuple:
    """Build the scope review prompt with full context packs.

    Returns (prompt_str, touched_omitted) where touched_omitted is:
    - None if all touched files were read successfully
    - "__empty__" if no touched files could be read at all
    - comma-separated string of omitted filenames otherwise
    """
    try:
        scope_checklist = load_checklist_section("Intent / Scope Review Checklist")
    except Exception:
        scope_checklist = "(Intent / Scope Review Checklist not found in docs/CHECKLISTS.md)"

    goal_section = build_goal_section(goal, scope, commit_message)
    scope_section = build_scope_section(scope)
    dev_guide = _load_dev_guide(repo_dir)

    rebuttal_section = ""
    if review_rebuttal:
        rebuttal_section = (
            "\n## Developer's rebuttal to previous review feedback\n\n"
            f"{review_rebuttal}\n\n"
            "Reconsider previous FAIL verdict(s) in light of this argument.\n"
        )

    history_section = _build_review_history_section(review_history or [])

    # Get diff and changed files
    try:
        diff_text = run_cmd(["git", "diff", "--cached"], cwd=repo_dir)
    except Exception:
        diff_text = "(failed to get staged diff)"

    try:
        changed = run_cmd(["git", "diff", "--cached", "--name-only"], cwd=repo_dir)
    except Exception:
        changed = ""

    # Build touched-file pack — omission data returned to caller for fail-closed check
    touched_paths = [f.strip() for f in changed.strip().splitlines() if f.strip()]
    current_files_section, omitted = build_touched_file_pack(repo_dir, touched_paths)

    # Compute omission signal for caller
    touched_omitted = None
    if not current_files_section.strip():
        touched_omitted = "__empty__"
    elif omitted:
        touched_omitted = ", ".join(omitted)

    # Build broader repo pack (best-effort)
    exclude_set = set(touched_paths)
    try:
        repo_pack_section = build_broader_repo_pack(repo_dir, exclude_set)
        if not repo_pack_section.strip():
            repo_pack_section = "(no additional repo files)"
    except Exception:
        repo_pack_section = "(broader repo pack unavailable)"

    return f"""\
{_SCOPE_PREAMBLE}

## Your role

You are the supplemental blocking scope reviewer for Ouroboros.

The diff reviewers already perform the strict line-by-line commit gate.
Do NOT merely repeat generic diff review. Focus on completeness, forgotten
touchpoints, stale adjacent surfaces, incomplete migrations, and intent mismatch.

## Your task

Judge whether the intended transformation is actually complete across:
code, tests, prompts, docs, configs, architecture surfaces, and sibling flows.

Use the richer context pack below.

## Output format

Output ONLY a valid JSON array.

Each element must have:
- "item"
- "verdict": "PASS" or "FAIL"
- "severity": "critical" or "advisory"
- "reason"

Severity rules:
- Use "critical" only when you can cite a concrete missing file, symbol, test, prompt, doc, config, or sibling path and explain why the transformation is incomplete or inconsistent.
- If you cannot point to an exact touchpoint, use "advisory".
- Scope affects only unchanged legacy code outside the diff. The diff itself is always fully reviewable.

{scope_checklist}
{scope_section}

{goal_section}

## DEVELOPMENT.md

{dev_guide}

{rebuttal_section}{history_section}

## Current touched files

{current_files_section}

## Staged diff

{diff_text}

## Wider repository context

{repo_pack_section}
""", touched_omitted


def _parse_scope_json(raw: str) -> Optional[list]:
    """Best-effort extraction of a JSON array from model output."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, list):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _emit_usage(ctx: ToolContext, model: str, usage: dict) -> None:
    """Emit a standard llm_usage event for cost tracking."""
    from ouroboros.pricing import infer_api_key_type, infer_model_category
    event = {
        "type": "llm_usage", "ts": utc_now_iso(),
        "task_id": getattr(ctx, "task_id", "") or "",
        "model": model,
        "api_key_type": infer_api_key_type(model, "openrouter"),
        "model_category": infer_model_category(model),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "cached_tokens": usage.get("cached_tokens", 0),
            "cost": usage.get("cost", 0),
        },
        "provider": "openrouter",
        "source": "scope_review",
        "category": "review",
    }
    eq = getattr(ctx, "event_queue", None)
    if eq:
        try:
            eq.put_nowait(event)
        except Exception:
            pass


def run_scope_review(
    ctx: ToolContext,
    commit_message: str,
    goal: str = "",
    scope: str = "",
    review_rebuttal: str = "",
    review_history: Optional[list] = None,
) -> Optional[str]:
    """Run the blocking scope review. Returns None if commit may proceed.

    Returns a blocking error string if the scope review rejects the commit
    or if the review fails to run (fail-closed).
    """
    repo_dir = pathlib.Path(ctx.repo_dir)

    prompt, touched_omitted = _build_scope_prompt(
        repo_dir, commit_message,
        goal=goal, scope=scope,
        review_rebuttal=review_rebuttal,
        review_history=review_history,
    )

    # Fail-closed: incomplete touched-file context blocks immediately
    if touched_omitted is not None:
        if touched_omitted == "__empty__":
            return (
                "⚠️ SCOPE_REVIEW_BLOCKED: Could not read any touched files — "
                "scope review requires direct file context. Commit blocked."
            )
        return (
            f"⚠️ SCOPE_REVIEW_BLOCKED: Some touched file(s) could not be included "
            f"in direct context (binary/oversize/unreadable): {touched_omitted}.\n"
            "Scope review requires complete touched-file context. Commit blocked.\n"
            "Possible fixes: reduce file size, commit binary files separately, "
            "or ensure all touched files are readable text."
        )

    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": "Review the staged change and context above. Output ONLY a JSON array.",
        },
    ]

    # Call the LLM
    from ouroboros.config import resolve_effort as _resolve_effort
    scope_model = _get_scope_model()
    scope_effort = _resolve_effort("scope_review")
    llm = LLMClient()
    try:
        try:
            asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                msg, usage = pool.submit(
                    asyncio.run,
                    llm.chat_async(
                        messages=messages,
                        model=scope_model,
                        reasoning_effort=scope_effort,
                        max_tokens=_SCOPE_MAX_TOKENS,
                        temperature=0.2,
                    ),
                ).result(timeout=180)
        except RuntimeError:
            msg, usage = asyncio.run(
                llm.chat_async(
                    messages=messages,
                    model=scope_model,
                    reasoning_effort=scope_effort,
                    max_tokens=_SCOPE_MAX_TOKENS,
                    temperature=0.2,
                )
            )
    except Exception as e:
        # Fail-closed: API failure blocks commit
        return (
            f"⚠️ SCOPE_REVIEW_BLOCKED: Scope reviewer ({scope_model}) failed — commit blocked.\n"
            f"Error: {type(e).__name__}: {e}\n"
            "Retry the commit, or check API key and network connectivity."
        )

    if usage:
        _emit_usage(ctx, scope_model, usage or {})

    raw_text = str(msg.get("content") or "")
    if not raw_text.strip():
        return (
            "⚠️ SCOPE_REVIEW_BLOCKED: Scope reviewer returned empty response — commit blocked.\n"
            "Retry the commit."
        )

    items = _parse_scope_json(raw_text)
    if items is None:
        return (
            "⚠️ SCOPE_REVIEW_BLOCKED: Could not parse scope reviewer output as JSON — commit blocked.\n"
            f"Raw preview: {raw_text[:500]}"
        )

    # Classify findings
    critical_fails: List[str] = []
    advisory_warns: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        verdict = str(item.get("verdict", "")).upper()
        severity = str(item.get("severity", "advisory")).lower()
        if verdict != "FAIL":
            continue
        desc = f"[scope:{item.get('item', '?')}] {item.get('reason', '')}"
        if severity == "critical":
            critical_fails.append(desc)
        else:
            advisory_warns.append(desc)

    # Log scope review result
    try:
        append_jsonl(ctx.drive_logs() / "events.jsonl", {
            "ts": utc_now_iso(), "type": "scope_review_complete",
            "task_id": getattr(ctx, "task_id", "") or "",
            "model": scope_model,
            "critical_count": len(critical_fails),
            "advisory_count": len(advisory_warns),
        })
    except Exception:
        pass

    if critical_fails:
        from ouroboros import config as _cfg
        review_enforcement = _cfg.get_review_enforcement()
        if review_enforcement == "blocking":
            return (
                f"⚠️ SCOPE_REVIEW_BLOCKED: Scope reviewer found critical completeness issues.\n"
                "Commit has NOT been created. Fix the issues and try again.\n\n"
                + "\n".join(f"  CRITICAL: {f}" for f in critical_fails)
                + ("\n\nAdvisory warnings:\n"
                   + "\n".join(f"  WARN: {w}" for w in advisory_warns)
                   if advisory_warns else "")
            )
        # Advisory mode: log but don't block
        for f in critical_fails:
            ctx._review_advisory.append(f"SCOPE CRITICAL (advisory mode): {f}")
        for w in advisory_warns:
            ctx._review_advisory.append(f"SCOPE WARN: {w}")

    elif advisory_warns:
        for w in advisory_warns:
            ctx._review_advisory.append(f"SCOPE WARN: {w}")

    return None  # commit may proceed
