"""
Ouroboros — LLM tool loop.

Core loop: send messages to LLM, execute tool calls, repeat until final response.
Extracted from agent.py to keep the agent thin.
"""

from __future__ import annotations

import os
import queue
import pathlib
from typing import Any, Callable, Dict, List, Optional, Tuple

import logging

from ouroboros.llm import LLMClient, normalize_reasoning_effort, add_usage
from ouroboros.tool_policy import initial_tool_schemas, list_non_core_tools
from ouroboros.tools.registry import ToolRegistry
from ouroboros.context import build_user_content
from ouroboros.context_compaction import compact_tool_history_llm
from ouroboros.utils import estimate_tokens

from ouroboros.loop_tool_execution import (
    StatefulToolExecutor,
    handle_tool_calls,
    _truncate_tool_result,
    _TOOL_RESULT_LIMITS,
    _DEFAULT_TOOL_RESULT_LIMIT,
)
from ouroboros.loop_llm_call import call_llm_with_retry, emit_llm_usage_event, estimate_cost

# Backward-compat alias for source-inspecting and monkeypatched tests
_call_llm_with_retry = call_llm_with_retry

log = logging.getLogger(__name__)


def _provider_failure_hint(accumulated_usage: Dict[str, Any]) -> str:
    detail = " ".join(str(accumulated_usage.get("_last_llm_error") or "").split()).strip()
    if not detail:
        return ""
    return f" Last provider error: {detail}"


def _handle_text_response(
    content: Optional[str],
    llm_trace: Dict[str, Any],
    accumulated_usage: Dict[str, Any],
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Handle LLM response without tool calls (final response)."""
    if content and content.strip():
        llm_trace["reasoning_notes"].append(content.strip())
    return (content or ""), accumulated_usage, llm_trace


def _check_budget_limits(
    budget_remaining_usd: Optional[float],
    accumulated_usage: Dict[str, Any],
    round_idx: int,
    messages: List[Dict[str, Any]],
    llm: LLMClient,
    active_model: str,
    active_effort: str,
    max_retries: int,
    drive_logs: pathlib.Path,
    task_id: str,
    event_queue: Optional[queue.Queue],
    llm_trace: Dict[str, Any],
    task_type: str = "task",
    use_local: bool = False,
) -> Optional[Tuple[str, Dict[str, Any], Dict[str, Any]]]:
    """
    Check budget limits and handle budget overrun.

    Returns:
        None if budget is OK (continue loop)
        (final_text, accumulated_usage, llm_trace) if budget exceeded (stop loop)
    """
    if budget_remaining_usd is None:
        return None

    task_cost = accumulated_usage.get("cost", 0)

    if budget_remaining_usd <= 0:
        finish_reason = f"🚫 Task rejected. Total budget exhausted. Please increase TOTAL_BUDGET in settings."
        return finish_reason, accumulated_usage, llm_trace

    budget_pct = task_cost / budget_remaining_usd if budget_remaining_usd > 0 else 1.0

    per_task_limit = float(os.environ.get("OUROBOROS_PER_TASK_COST_USD", "20.0") or 20.0)
    if task_cost >= per_task_limit and round_idx % 10 == 0:
        messages.append({
            "role": "user",
            "content": f"[COST NOTE] Task spent ${task_cost:.3f}, which is at or above the per-task soft threshold of ${per_task_limit:.2f}. Continue only if the expected value still justifies the cost.",
        })

    if budget_pct > 0.5:
        finish_reason = f"Task spent ${task_cost:.3f} (>50% of remaining ${budget_remaining_usd:.2f}). Budget exhausted."
        messages.append({"role": "user", "content": f"[BUDGET LIMIT] {finish_reason} Give your final response now."})
        try:
            final_msg, final_cost = _call_llm_with_retry(
                llm, messages, active_model, None, active_effort,
                max_retries, drive_logs, task_id, round_idx, event_queue, accumulated_usage, task_type,
                use_local=use_local,
            )
            if final_msg:
                return (final_msg.get("content") or finish_reason), accumulated_usage, llm_trace
            return finish_reason, accumulated_usage, llm_trace
        except Exception:
            log.warning("Failed to get final response after budget limit", exc_info=True)
            return finish_reason, accumulated_usage, llm_trace
    elif budget_pct > 0.3 and round_idx % 10 == 0:
        messages.append({"role": "user", "content": f"[INFO] Task spent ${task_cost:.3f} of ${budget_remaining_usd:.2f}. Wrap up if possible."})

    return None


def _maybe_inject_self_check(
    round_idx: int,
    max_rounds: int,
    messages: List[Dict[str, Any]],
    accumulated_usage: Dict[str, Any],
    emit_progress: Callable[[str], None],
) -> bool:
    """Inject a soft self-check reminder every REMINDER_INTERVAL rounds.

    Returns True if a checkpoint was injected (caller boosts reasoning effort).
    """
    REMINDER_INTERVAL = 15
    if round_idx <= 1 or round_idx % REMINDER_INTERVAL != 0:
        return False
    ctx_tokens = sum(
        estimate_tokens(str(m.get("content", "")))
        if isinstance(m.get("content"), str)
        else sum(estimate_tokens(str(b.get("text", ""))) for b in m.get("content", []) if isinstance(b, dict))
        for m in messages
    )
    task_cost = accumulated_usage.get("cost", 0)
    checkpoint_num = round_idx // REMINDER_INTERVAL

    reminder = (
        f"[CHECKPOINT {checkpoint_num} — round {round_idx}/{max_rounds}]\n"
        f"📊 Context: ~{ctx_tokens} tokens | Cost so far: ${task_cost:.2f} | "
        f"Rounds remaining: {max_rounds - round_idx}\n\n"
        f"⏸️ PAUSE AND REFLECT before continuing:\n"
        f"1. Am I making real progress, or repeating the same actions?\n"
        f"2. Is my current strategy working? Should I try something different?\n"
        f"3. Is my context bloated with old tool results I no longer need?\n"
        f"   → If yes, call `compact_context` to summarize them selectively.\n"
        f"4. Have I been stuck on the same sub-problem for many rounds?\n"
        f"   → If yes, consider: simplify the approach, skip the sub-problem, or finish with what I have.\n"
        f"5. Should I just STOP and return my best result so far?\n"
        f"6. Multiple REVIEW_BLOCKED results in context? Consider saving WIP\n"
        f"   (git_diff → data_write) and breaking into smaller commits.\n\n"
        f"This is not a hard limit — you decide. But be honest with yourself."
    )
    messages.append({"role": "system", "content": reminder})
    emit_progress(f"🔄 Checkpoint {checkpoint_num} at round {round_idx}: ~{ctx_tokens} tokens, ${task_cost:.2f} spent")
    return True


def _extract_plain_text_from_content(content: Any) -> str:
    """Extract plain text from either a string or a multipart content list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content) if content is not None else ""


def seal_task_transcript(
    messages: List[Dict[str, Any]],
    keep_active: int = 5,
    min_prefix_tokens: int = 2048,
) -> None:
    """Seal one stable tool-result message with cache_control to improve prompt cache hits.

    Strategy:
    - First, revert any previously sealed tool message back to a plain string so
      compaction and later rounds always see normal content (not stale multipart blocks).
    - Then identify the last tool-result message that falls BEFORE the active recent
      window (last `keep_active` tool results). That message is the "seal boundary".
    - If the token estimate for content up to and including that message exceeds
      `min_prefix_tokens`, mark it with a multipart cache_control block.
    - Only one sealed boundary exists at a time. Non-Anthropic paths strip
      cache_control in llm.py before sending, so they are unaffected.

    Mutates `messages` in-place. Returns None.
    """
    # Step 1: revert any previously sealed tool messages to plain strings
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if isinstance(content, list):
            # Was sealed — flatten back to plain text
            msg["content"] = _extract_plain_text_from_content(content)

    # Step 2: collect indices of all tool-result messages
    tool_indices = [
        i for i, m in enumerate(messages)
        if m.get("role") == "tool"
    ]
    if len(tool_indices) <= keep_active:
        # Not enough tool rounds for a stable prefix yet
        return

    # The candidate to seal: last tool result before the active window
    seal_candidate_idx = tool_indices[-(keep_active + 1)]

    # Step 3: estimate prefix token count up to and including the candidate
    prefix_text_len = sum(
        len(_extract_plain_text_from_content(m.get("content", "")))
        for m in messages[: seal_candidate_idx + 1]
    )
    prefix_tokens = prefix_text_len // 4  # rough 4-chars-per-token estimate

    if prefix_tokens < min_prefix_tokens:
        return

    # Step 4: seal the candidate message
    candidate = messages[seal_candidate_idx]
    plain_text = str(candidate.get("content", ""))
    candidate["content"] = [
        {
            "type": "text",
            "text": plain_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _setup_dynamic_tools(tools_registry, tool_schemas, messages):
    """
    Wire tool-discovery handlers onto an existing tool_schemas list.

    Creates closures for list_available_tools / enable_tools, registers them
    as handler overrides, and injects a system message advertising non-core
    tools.  Mutates tool_schemas in-place (via list.append) when tools are
    enabled, so the caller's reference stays live.

    Returns (tool_schemas, enabled_extra_set).
    """
    enabled_extra: set = set()

    def _handle_list_tools(ctx=None, **kwargs):
        non_core = list_non_core_tools(tools_registry)
        if not non_core:
            return "All tools are already in your active set."
        lines = [f"**{len(non_core)} additional tools available** (use `enable_tools` to activate):\n"]
        for t in non_core:
            lines.append(f"- **{t['name']}**: {t['description'][:120]}")
        return "\n".join(lines)

    def _handle_enable_tools(ctx=None, tools: str = "", **kwargs):
        names = [n.strip() for n in tools.split(",") if n.strip()]
        enabled, not_found = [], []
        for name in names:
            schema = tools_registry.get_schema_by_name(name)
            if schema and name not in enabled_extra:
                tool_schemas.append(schema)
                enabled_extra.add(name)
                enabled.append(name)
            elif name in enabled_extra:
                enabled.append(f"{name} (already active)")
            else:
                not_found.append(name)
        parts = []
        if enabled:
            parts.append(f"✅ Enabled: {', '.join(enabled)}")
        if not_found:
            parts.append(f"❌ Not found: {', '.join(not_found)}")
        return "\n".join(parts) if parts else "No tools specified."

    tools_registry.override_handler("list_available_tools", _handle_list_tools)
    tools_registry.override_handler("enable_tools", _handle_enable_tools)

    non_core_count = len(list_non_core_tools(tools_registry))
    if non_core_count > 0:
        messages.append({
            "role": "system",
            "content": (
                f"Note: You have {len(tool_schemas)} core tools loaded. "
                f"There are {non_core_count} additional tools available "
                f"(use `list_available_tools` to see them, `enable_tools` to activate). "
                f"Core tools cover most tasks. Enable extras only when needed."
            ),
        })

    return tool_schemas, enabled_extra


def _drain_incoming_messages(
    messages: List[Dict[str, Any]],
    incoming_messages: queue.Queue,
    drive_root: Optional[pathlib.Path],
    task_id: str,
    event_queue: Optional[queue.Queue],
    _owner_msg_seen: set,
) -> None:
    """Inject owner messages received during task execution."""
    while not incoming_messages.empty():
        try:
            injected = incoming_messages.get_nowait()
            if isinstance(injected, dict):
                messages.append({"role": "user", "content": build_user_content(injected)})
            else:
                messages.append({"role": "user", "content": injected})
        except queue.Empty:
            break

    if drive_root is not None and task_id:
        from ouroboros.owner_inject import drain_owner_messages
        drive_msgs = drain_owner_messages(drive_root, task_id=task_id, seen_ids=_owner_msg_seen)
        for dmsg in drive_msgs:
            messages.append({
                "role": "user",
                "content": f"[Owner message during task]: {dmsg}",
            })
            if event_queue is not None:
                try:
                    event_queue.put_nowait({
                        "type": "owner_message_injected",
                        "task_id": task_id,
                        "text": dmsg,
                    })
                except Exception:
                    pass


def run_llm_loop(
    messages: List[Dict[str, Any]],
    tools: ToolRegistry,
    llm: LLMClient,
    drive_logs: pathlib.Path,
    emit_progress: Callable[[str], None],
    incoming_messages: queue.Queue,
    task_type: str = "",
    task_id: str = "",
    budget_remaining_usd: Optional[float] = None,
    event_queue: Optional[queue.Queue] = None,
    initial_effort: str = "medium",
    drive_root: Optional[pathlib.Path] = None,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """
    Core LLM-with-tools loop.

    Sends messages to LLM, executes tool calls, retries on errors.
    LLM controls model/effort via switch_model tool (LLM-first, Bible P3).

    Returns: (final_text, accumulated_usage, llm_trace)
    """
    active_model = llm.default_model()
    active_effort = initial_effort
    active_use_local = os.environ.get("USE_LOCAL_MAIN", "").lower() in ("true", "1")

    llm_trace: Dict[str, Any] = {"reasoning_notes": [], "tool_calls": []}
    accumulated_usage: Dict[str, Any] = {}
    max_retries = 3
    from ouroboros.tools import tool_discovery as _td
    _td.set_registry(tools)

    tool_schemas = initial_tool_schemas(tools)
    tool_schemas, _enabled_extra_tools = _setup_dynamic_tools(tools, tool_schemas, messages)

    tools._ctx.event_queue = event_queue
    tools._ctx.task_id = task_id
    tools._ctx.messages = messages
    stateful_executor = StatefulToolExecutor()
    _owner_msg_seen: set = set()
    try:
        MAX_ROUNDS = max(1, int(os.environ.get("OUROBOROS_MAX_ROUNDS", "200")))
    except (ValueError, TypeError):
        MAX_ROUNDS = 200
        log.warning("Invalid OUROBOROS_MAX_ROUNDS, defaulting to 200")
    round_idx = 0
    try:
        while True:
            round_idx += 1

            if round_idx > MAX_ROUNDS:
                finish_reason = f"⚠️ Task exceeded MAX_ROUNDS ({MAX_ROUNDS}). Consider decomposing into subtasks via schedule_task."
                messages.append({"role": "system", "content": f"[ROUND_LIMIT] {finish_reason}"})
                try:
                    final_msg, final_cost = call_llm_with_retry(
                        llm, messages, active_model, None, active_effort,
                        max_retries, drive_logs, task_id, round_idx, event_queue, accumulated_usage, task_type,
                        use_local=active_use_local,
                    )
                    if final_msg:
                        return (final_msg.get("content") or finish_reason), accumulated_usage, llm_trace
                    return finish_reason, accumulated_usage, llm_trace
                except Exception:
                    log.warning("Failed to get final response after round limit", exc_info=True)
                    return finish_reason, accumulated_usage, llm_trace

            _checkpoint_injected = _maybe_inject_self_check(round_idx, MAX_ROUNDS, messages, accumulated_usage, emit_progress)

            ctx = tools._ctx
            if ctx.active_model_override:
                active_model = ctx.active_model_override
                ctx.active_model_override = None
            if getattr(ctx, "active_use_local_override", None) is not None:
                active_use_local = ctx.active_use_local_override
                ctx.active_use_local_override = None
            if ctx.active_effort_override:
                active_effort = normalize_reasoning_effort(ctx.active_effort_override, default=active_effort)
                ctx.active_effort_override = None

            _pre_checkpoint_effort = None
            if _checkpoint_injected:
                _pre_checkpoint_effort = active_effort
                active_effort = "xhigh"

            _drain_incoming_messages(messages, incoming_messages, drive_root, task_id, event_queue, _owner_msg_seen)

            _compaction_usage = None
            pending_compaction = getattr(tools._ctx, '_pending_compaction', None)
            if pending_compaction is not None:
                messages, _compaction_usage = compact_tool_history_llm(messages, keep_recent=pending_compaction)
                tools._ctx._pending_compaction = None
            elif round_idx > 12:
                messages, _compaction_usage = compact_tool_history_llm(messages, keep_recent=50)
            elif round_idx > 6:
                if len(messages) > 80:
                    messages, _compaction_usage = compact_tool_history_llm(messages, keep_recent=50)
            if tools._ctx.messages is not messages:
                tools._ctx.messages = messages
            if _compaction_usage:
                add_usage(accumulated_usage, _compaction_usage)
                _cm = os.environ.get("OUROBOROS_MODEL_LIGHT") or "anthropic/claude-sonnet-4.6"
                _cc = float(_compaction_usage.get("cost") or 0) or estimate_cost(
                    _cm, int(_compaction_usage.get("prompt_tokens") or 0),
                    int(_compaction_usage.get("completion_tokens") or 0),
                    int(_compaction_usage.get("cached_tokens") or 0))
                emit_llm_usage_event(event_queue, task_id, _cm, _compaction_usage, _cc, "compaction")

            # Seal one stable tool-result boundary for prompt caching (Anthropic-only path;
            # non-Anthropic providers strip cache_control in llm.py).
            seal_task_transcript(messages)

            msg, cost = call_llm_with_retry(
                llm, messages, active_model, tool_schemas, active_effort,
                max_retries, drive_logs, task_id, round_idx, event_queue, accumulated_usage, task_type,
                use_local=active_use_local,
            )

            if _pre_checkpoint_effort is not None:
                active_effort = _pre_checkpoint_effort

            if msg is None:
                fallback_model = os.environ.get("OUROBOROS_MODEL_FALLBACK", "").strip()
                if not fallback_model or fallback_model == active_model:
                    local_tag = " (local)" if active_use_local else ""
                    return (
                        f"⚠️ Failed to get a response from model {active_model}{local_tag} after {max_retries} attempts. "
                        f"No viable fallback model configured.{_provider_failure_hint(accumulated_usage)} "
                        f"If background consciousness is running, it will retry when the provider recovers."
                    ), accumulated_usage, llm_trace

                fallback_use_local = os.environ.get("USE_LOCAL_FALLBACK", "").lower() in ("true", "1")
                primary_tag = " (local)" if active_use_local else ""
                fallback_tag = " (local)" if fallback_use_local else ""
                emit_progress(f"⚡ Fallback: {active_model}{primary_tag} → {fallback_model}{fallback_tag} after empty response")
                msg, fallback_cost = call_llm_with_retry(
                    llm, messages, fallback_model, tool_schemas, active_effort,
                    max_retries, drive_logs, task_id, round_idx, event_queue, accumulated_usage, task_type,
                    use_local=fallback_use_local,
                )

                if msg is None:
                    return (
                        f"⚠️ All models are down. Primary ({active_model}{primary_tag}) and fallback ({fallback_model}{fallback_tag}) "
                        f"both returned no response. Stopping.{_provider_failure_hint(accumulated_usage)} "
                        f"Background consciousness will attempt recovery when the provider is back."
                    ), accumulated_usage, llm_trace

            tool_calls = msg.get("tool_calls") or []
            content = msg.get("content")
            if not tool_calls:
                return _handle_text_response(content, llm_trace, accumulated_usage)

            messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})

            if content and content.strip():
                emit_progress(content.strip())
                llm_trace["reasoning_notes"].append(content.strip())

            error_count = handle_tool_calls(
                tool_calls, tools, drive_logs, task_id, stateful_executor,
                messages, llm_trace, emit_progress
            )

            budget_result = _check_budget_limits(
                budget_remaining_usd, accumulated_usage, round_idx, messages,
                llm, active_model, active_effort, max_retries, drive_logs,
                task_id, event_queue, llm_trace, task_type, active_use_local
            )
            if budget_result is not None:
                return budget_result

    finally:
        if stateful_executor:
            try:
                from ouroboros.tools.browser import cleanup_browser
                stateful_executor.submit(cleanup_browser, tools._ctx).result(timeout=5)
            except Exception:
                log.debug("Browser cleanup on executor thread failed or timed out", exc_info=True)
            try:
                stateful_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                log.warning("Failed to shutdown stateful executor", exc_info=True)
        if drive_root is not None and task_id:
            try:
                from ouroboros.owner_inject import cleanup_task_mailbox
                cleanup_task_mailbox(drive_root, task_id)
            except Exception:
                log.debug("Failed to cleanup task mailbox", exc_info=True)
