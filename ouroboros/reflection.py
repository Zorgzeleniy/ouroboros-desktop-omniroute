"""
Ouroboros — Execution Reflection (Process Memory).

Generates brief LLM summaries of task execution when errors occurred.
Stored in task_reflections.jsonl and loaded into the next task's context,
giving Ouroboros visibility into its own process across task boundaries.

Process memory is as essential as factual memory — seeing the class of
error requires seeing the process that produced it.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any, Dict, List, Optional

from ouroboros.utils import utc_now_iso, append_jsonl

log = logging.getLogger(__name__)

_ERROR_MARKERS = frozenset({
    "REVIEW_BLOCKED",
    "TESTS_FAILED",
    "COMMIT_BLOCKED",
    "REVIEW_MAX_ITERATIONS",
    "TOOL_ERROR",
    "TOOL_TIMEOUT",
})

REFLECTIONS_FILENAME = "task_reflections.jsonl"

_REFLECTION_PROMPT = """\
You are reviewing a completed task execution trace for Ouroboros, a self-modifying AI agent.
The task had errors. Write a concise 150-250 word reflection covering:

1. What was the goal?
2. What specific errors/blocks occurred?
3. What was the root cause (if identifiable)?
4. What should be done differently next time?

Be concrete — cite specific file names, tool names, error messages. No platitudes.

## Task goal

{goal}

## Execution trace

{trace_summary}

## Error details

{error_details}

Write the reflection now. Plain text, no markdown headers.
"""


def should_generate_reflection(llm_trace: Dict[str, Any]) -> bool:
    """Check if a task's execution warrants an automatic reflection.

    Returns True when tool calls had errors or results contained
    known blocking markers (REVIEW_BLOCKED, TESTS_FAILED, etc.).
    """
    tool_calls = llm_trace.get("tool_calls") or []

    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        if tc.get("is_error"):
            return True
        result_str = str(tc.get("result", ""))
        for marker in _ERROR_MARKERS:
            if marker in result_str:
                return True

    return False


def _collect_error_details(llm_trace: Dict[str, Any], cap: int = 3000) -> str:
    """Extract error tool results from the trace, up to *cap* chars."""
    parts: List[str] = []
    total = 0
    tool_calls = llm_trace.get("tool_calls") or []

    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        result_str = str(tc.get("result", ""))
        is_relevant = tc.get("is_error") or any(m in result_str for m in _ERROR_MARKERS)
        if not is_relevant:
            continue
        tool_name = tc.get("tool", "unknown")
        snippet = f"[{tool_name}]: {result_str}"
        if total + len(snippet) > cap:
            remaining = cap - total
            if remaining > 50:
                parts.append(_truncate_with_notice(snippet, remaining))
            break
        parts.append(snippet)
        total += len(snippet)

    return "\n\n".join(parts) if parts else "(no error details captured)"


def _detect_markers(llm_trace: Dict[str, Any]) -> List[str]:
    """Return list of error marker strings found in the trace."""
    found: set = set()
    for tc in (llm_trace.get("tool_calls") or []):
        result_str = str(tc.get("result", "") if isinstance(tc, dict) else "")
        for marker in _ERROR_MARKERS:
            if marker in result_str:
                found.add(marker)
    return sorted(found)


def generate_reflection(
    task: Dict[str, Any],
    llm_trace: Dict[str, Any],
    trace_summary: str,
    llm_client: Any,
    usage_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """Call the light LLM to produce an execution reflection.

    Returns a structured dict ready for appending to the reflections JSONL.
    """
    from ouroboros.llm import DEFAULT_LIGHT_MODEL

    goal = _truncate_with_notice(task.get("text", ""), 200)
    error_details = _collect_error_details(llm_trace)
    markers = _detect_markers(llm_trace)
    error_count = sum(
        1 for tc in (llm_trace.get("tool_calls") or [])
        if isinstance(tc, dict) and tc.get("is_error")
    )

    prompt = _REFLECTION_PROMPT.format(
        goal=goal or "(no goal text)",
        trace_summary=_truncate_with_notice(trace_summary, 2000),
        error_details=error_details,
    )

    light_model = os.environ.get("OUROBOROS_MODEL_LIGHT") or DEFAULT_LIGHT_MODEL
    try:
        resp_msg, _usage = llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=light_model,
            reasoning_effort="low",
            max_tokens=512,
        )
        reflection_text = (resp_msg.get("content") or "").strip()
    except Exception as e:
        log.warning("Reflection LLM call failed: %s", e)
        reflection_text = f"(reflection generation failed: {e})"

    return {
        "ts": utc_now_iso(),
        "task_id": task.get("id", ""),
        "task_type": str(task.get("type", "")),
        "goal": goal,
        "rounds": int(usage_dict.get("rounds", 0)),
        "cost_usd": round(float(usage_dict.get("cost", 0)), 4),
        "error_count": error_count,
        "key_markers": markers,
        "reflection": reflection_text,
    }


def append_reflection(drive_root: pathlib.Path, entry: Dict[str, Any]) -> None:
    """Persist a reflection entry to the JSONL file."""
    reflections_path = drive_root / "logs" / REFLECTIONS_FILENAME
    try:
        append_jsonl(reflections_path, entry)
        log.info("Execution reflection saved (task=%s, markers=%s)",
                 entry.get("task_id", "?"), entry.get("key_markers", []))
    except Exception:
        log.warning("Failed to save execution reflection", exc_info=True)

    if entry.get("key_markers"):
        try:
            _update_patterns(drive_root, entry)
        except Exception:
            log.debug("Pattern register update failed (non-critical)", exc_info=True)


_PATTERNS_PROMPT = """\
You maintain a Pattern Register for Ouroboros, a self-modifying AI agent.
Below is the current register and a new error reflection. Update the register.

Rules:
- If this is a NEW error class: add a row.
- If this is a RECURRING class: increment count, update root cause/fix if you have better info.
- Keep the markdown table format.
- Be concrete: cite file names, tool names, error types.
- Max 20 rows. If full, merge least-important entries.

## Current register

{current_patterns}

## New reflection

Task: {goal}
Markers: {markers}
Reflection: {reflection}

Output ONLY the updated markdown table (with header). No extra text.
"""

_PATTERNS_HEADER = (
    "# Pattern Register\n\n"
    "| Error class | Count | Root cause | Structural fix | Status |\n"
    "|-------------|-------|------------|----------------|--------|\n"
)


def _truncate_with_notice(text: Any, limit: int) -> str:
    raw = str(text or "")
    if len(raw) <= limit:
        return raw
    marker = f"... [+{len(raw) - limit} chars]"
    available = max(0, limit - len(marker))
    marker = f"... [+{len(raw) - available} chars]"
    available = max(0, limit - len(marker))
    return raw[:available] + marker


def _update_patterns(drive_root: pathlib.Path, entry: Dict[str, Any]) -> None:
    """Update patterns.md knowledge base topic via LLM (Pattern Register)."""
    from ouroboros.llm import LLMClient, DEFAULT_LIGHT_MODEL

    patterns_path = drive_root / "memory" / "knowledge" / "patterns.md"
    patterns_path.parent.mkdir(parents=True, exist_ok=True)

    if patterns_path.exists():
        current = patterns_path.read_text(encoding="utf-8")
    else:
        current = _PATTERNS_HEADER

    prompt = _PATTERNS_PROMPT.format(
        current_patterns=(
            _truncate_with_notice(current, 3000)
            + (
                "\n\n[IMPORTANT: The current register was compacted for prompt size. "
                "Preserve existing rows unless you are intentionally merging or updating them.]"
                if len(current) > 3000 else ""
            )
        ),
        goal=_truncate_with_notice(entry.get("goal", "?"), 200),
        markers=", ".join(entry.get("key_markers", [])),
        reflection=_truncate_with_notice(entry.get("reflection", ""), 500),
    )

    light_model = os.environ.get("OUROBOROS_MODEL_LIGHT") or DEFAULT_LIGHT_MODEL
    client = LLMClient()
    resp_msg, _usage = client.chat(
        messages=[{"role": "user", "content": prompt}],
        model=light_model,
        reasoning_effort="low",
        max_tokens=1024,
    )
    updated = (resp_msg.get("content") or "").strip()
    if not updated or "|" not in updated:
        log.warning("Pattern register LLM returned invalid output, skipping update")
        return

    if not updated.startswith("#"):
        updated = "# Pattern Register\n\n" + updated

    patterns_path.write_text(updated + "\n", encoding="utf-8")
    log.info("Pattern register updated (%d chars)", len(updated))

    try:
        from ouroboros.consolidator import _rebuild_knowledge_index
        _rebuild_knowledge_index(patterns_path.parent)
    except Exception:
        log.debug("Failed to rebuild knowledge index after patterns update", exc_info=True)
