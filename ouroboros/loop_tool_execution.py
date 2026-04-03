"""
Tool execution machinery for the LLM loop.

Handles single-tool execution, parallel dispatch, timeouts, browser thread-affinity,
result truncation, and progress/trace logging.
Extracted from loop.py to keep the main loop orchestrator focused.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

import logging

from ouroboros.tools.registry import ToolRegistry
from ouroboros.utils import utc_now_iso, append_jsonl, truncate_for_log, sanitize_tool_args_for_log, sanitize_tool_result_for_log

log = logging.getLogger(__name__)

READ_ONLY_PARALLEL_TOOLS = frozenset({
    "repo_read", "repo_list",
    "data_read", "data_list",
    "web_search", "codebase_digest", "chat_history",
})

STATEFUL_BROWSER_TOOLS = frozenset({"browse_page", "browser_action"})

_TOOL_RESULT_LIMITS: Dict[str, int] = {
    "repo_read": 80_000,
    "data_read": 80_000,
    "knowledge_read": 80_000,
    "run_shell": 80_000,
}
_DEFAULT_TOOL_RESULT_LIMIT = 15_000

_UNTRUNCATED_TOOL_RESULTS = frozenset({
    "repo_commit",
    "repo_write_commit",
    "multi_model_review",
})

_UNTRUNCATED_REPO_READ_PATHS = frozenset({
    "BIBLE.md",
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/CHECKLISTS.md",
    "docs/DEVELOPMENT.md",
})


def _emit_live_log(tools: ToolRegistry, payload: Dict[str, Any]) -> None:
    event_queue = getattr(getattr(tools, "_ctx", None), "event_queue", None)
    if event_queue is None:
        return
    try:
        event_queue.put_nowait({
            "type": "log_event",
            "data": {"ts": utc_now_iso(), **payload},
        })
    except Exception:
        log.debug("Failed to emit live tool log event", exc_info=True)


def _get_tool_timeout(tools: ToolRegistry, tool_name: str) -> int:
    """Get timeout for a tool call. Env override takes precedence over per-tool default."""
    env_val = os.environ.get("OUROBOROS_TOOL_TIMEOUT_SEC")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return tools.get_timeout(tool_name)


def _path_is_cognitive_artifact(tool_name: str, tool_args: Optional[Dict[str, Any]]) -> bool:
    """Return True when the tool is reading memory/prompt files that must stay whole."""
    if not tool_args:
        return False

    raw_path = str(tool_args.get("path") or "").strip()
    if not raw_path:
        return False

    normalized = raw_path.replace("\\", "/").lstrip("./")

    if tool_name == "data_read":
        return normalized.startswith("memory/") and "/_backup/" not in normalized

    if tool_name == "repo_read":
        return normalized.startswith("prompts/") or normalized in _UNTRUNCATED_REPO_READ_PATHS

    return False


def _should_skip_tool_result_truncation(
    tool_name: str,
    tool_args: Optional[Dict[str, Any]] = None,
) -> bool:
    """Canonical reads must remain whole; warnings happen elsewhere via health invariants."""
    return tool_name in _UNTRUNCATED_TOOL_RESULTS or _path_is_cognitive_artifact(tool_name, tool_args)


def _truncate_tool_result(
    result: Any,
    tool_name: str = "",
    tool_args: Optional[Dict[str, Any]] = None,
) -> str:
    """Cap tool result unless the read target is a cognitive artifact that must stay whole."""
    limit = _TOOL_RESULT_LIMITS.get(tool_name, _DEFAULT_TOOL_RESULT_LIMIT)
    s = str(result)
    if _should_skip_tool_result_truncation(tool_name, tool_args):
        return s
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n... (truncated from {len(s)} chars, limit={limit})"


def _execute_single_tool(
    tools: ToolRegistry,
    tc: Dict[str, Any],
    drive_logs: pathlib.Path,
    task_id: str = "",
) -> Dict[str, Any]:
    """
    Execute a single tool call and return all needed info.

    Returns dict with: tool_call_id, fn_name, result, is_error, args_for_log, is_code_tool
    """
    fn_name = tc["function"]["name"]
    tool_call_id = tc["id"]
    is_code_tool = fn_name in tools.CODE_TOOLS

    try:
        args = json.loads(tc["function"]["arguments"] or "{}")
    except (json.JSONDecodeError, ValueError) as e:
        result = f"⚠️ TOOL_ARG_ERROR: Could not parse arguments for '{fn_name}': {e}"
        return {
            "tool_call_id": tool_call_id,
            "fn_name": fn_name,
            "result": result,
            "is_error": True,
            "tool_args": {},
            "args_for_log": {},
            "is_code_tool": is_code_tool,
        }

    args_for_log = sanitize_tool_args_for_log(fn_name, args if isinstance(args, dict) else {})

    tool_ok = True
    try:
        result = tools.execute(fn_name, args)
    except Exception as e:
        tool_ok = False
        result = f"⚠️ TOOL_ERROR ({fn_name}): {type(e).__name__}: {e}"
        append_jsonl(drive_logs / "events.jsonl", {
            "ts": utc_now_iso(), "type": "tool_error", "task_id": task_id,
            "tool": fn_name, "args": args_for_log, "error": repr(e),
        })

    append_jsonl(drive_logs / "tools.jsonl", {
        "ts": utc_now_iso(), "type": "tool_call", "tool": fn_name, "task_id": task_id,
        "args": args_for_log,
        "result_preview": sanitize_tool_result_for_log(truncate_for_log(result, 2000)),
    })

    is_error = (not tool_ok) or str(result).startswith("⚠️")

    return {
        "tool_call_id": tool_call_id,
        "fn_name": fn_name,
        "result": result,
        "is_error": is_error,
        "tool_args": args if isinstance(args, dict) else {},
        "args_for_log": args_for_log,
        "is_code_tool": is_code_tool,
    }


class StatefulToolExecutor:
    """
    Thread-sticky executor for stateful tools (browser, etc).

    Playwright sync API uses greenlet internally which has strict thread-affinity:
    once a greenlet starts in a thread, all subsequent calls must happen in the same thread.
    This executor ensures browse_page/browser_action always run in the same thread.

    On timeout: we shutdown the executor and create a fresh one to reset state.
    """
    def __init__(self):
        self._executor: Optional[ThreadPoolExecutor] = None

    def submit(self, fn, *args, **kwargs):
        """Submit work to the sticky thread. Creates executor on first call."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stateful_tool")
        return self._executor.submit(fn, *args, **kwargs)

    def reset(self):
        """Shutdown current executor and create a fresh one. Used after timeout/error."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def shutdown(self, wait=True, cancel_futures=False):
        """Final cleanup."""
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            self._executor = None


def _make_timeout_result(
    fn_name: str,
    tool_call_id: str,
    is_code_tool: bool,
    tc: Dict[str, Any],
    drive_logs: pathlib.Path,
    timeout_sec: int,
    task_id: str = "",
    reset_msg: str = "",
) -> Dict[str, Any]:
    """Create a timeout error result dictionary and log the timeout event."""
    args_for_log = {}
    try:
        args = json.loads(tc["function"]["arguments"] or "{}")
        args_for_log = sanitize_tool_args_for_log(fn_name, args if isinstance(args, dict) else {})
    except Exception:
        pass

    result = (
        f"⚠️ TOOL_TIMEOUT ({fn_name}): exceeded {timeout_sec}s limit. "
        f"The tool is still running in background but control is returned to you. "
        f"{reset_msg}Try a different approach or inform the user{' about the issue' if not reset_msg else ''}."
    )

    append_jsonl(drive_logs / "events.jsonl", {
        "ts": utc_now_iso(), "type": "tool_timeout",
        "tool": fn_name, "args": args_for_log,
        "timeout_sec": timeout_sec,
    })
    append_jsonl(drive_logs / "tools.jsonl", {
        "ts": utc_now_iso(), "type": "tool_call", "tool": fn_name,
        "args": args_for_log, "result_preview": result,
    })

    return {
        "tool_call_id": tool_call_id,
        "fn_name": fn_name,
        "result": result,
        "is_error": True,
        "args_for_log": args_for_log,
        "is_code_tool": is_code_tool,
    }


def _execute_with_timeout(
    tools: ToolRegistry,
    tc: Dict[str, Any],
    drive_logs: pathlib.Path,
    timeout_sec: int,
    task_id: str = "",
    stateful_executor: Optional[StatefulToolExecutor] = None,
) -> Dict[str, Any]:
    """Execute a tool call with a hard timeout."""
    fn_name = tc["function"]["name"]
    tool_call_id = tc["id"]
    is_code_tool = fn_name in tools.CODE_TOOLS
    use_stateful = stateful_executor and fn_name in STATEFUL_BROWSER_TOOLS
    started_at = time.perf_counter()
    args_for_log = {}
    try:
        args = json.loads(tc["function"]["arguments"] or "{}")
        if isinstance(args, dict):
            args_for_log = sanitize_tool_args_for_log(fn_name, args)
    except Exception:
        pass
    _emit_live_log(tools, {
        "type": "tool_call_started",
        "task_id": task_id,
        "tool": fn_name,
        "timeout_sec": timeout_sec,
        "args": args_for_log,
    })

    if use_stateful:
        future = stateful_executor.submit(_execute_single_tool, tools, tc, drive_logs, task_id)
        try:
            result = future.result(timeout=timeout_sec)
            _emit_live_log(tools, {
                "type": "tool_call_finished",
                "task_id": task_id,
                "tool": fn_name,
                "args": result.get("args_for_log", args_for_log),
                "duration_sec": round(time.perf_counter() - started_at, 3),
                "is_error": bool(result.get("is_error")),
                "result_preview": sanitize_tool_result_for_log(
                    truncate_for_log(result.get("result", ""), 500)
                ),
            })
            return result
        except (TimeoutError, concurrent.futures.TimeoutError):
            stateful_executor.reset()
            reset_msg = "Browser state has been reset. "
            timeout_result = _make_timeout_result(
                fn_name, tool_call_id, is_code_tool, tc, drive_logs,
                timeout_sec, task_id, reset_msg
            )
            _emit_live_log(tools, {
                "type": "tool_call_timeout",
                "task_id": task_id,
                "tool": fn_name,
                "args": args_for_log,
                "duration_sec": round(time.perf_counter() - started_at, 3),
                "timeout_sec": timeout_sec,
            })
            return timeout_result
    else:
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(_execute_single_tool, tools, tc, drive_logs, task_id)
            try:
                result = future.result(timeout=timeout_sec)
                _emit_live_log(tools, {
                    "type": "tool_call_finished",
                    "task_id": task_id,
                    "tool": fn_name,
                    "args": result.get("args_for_log", args_for_log),
                    "duration_sec": round(time.perf_counter() - started_at, 3),
                    "is_error": bool(result.get("is_error")),
                    "result_preview": sanitize_tool_result_for_log(
                        truncate_for_log(result.get("result", ""), 500)
                    ),
                })
                return result
            except (TimeoutError, concurrent.futures.TimeoutError):
                timeout_result = _make_timeout_result(
                    fn_name, tool_call_id, is_code_tool, tc, drive_logs,
                    timeout_sec, task_id, reset_msg=""
                )
                _emit_live_log(tools, {
                    "type": "tool_call_timeout",
                    "task_id": task_id,
                    "tool": fn_name,
                    "args": args_for_log,
                    "duration_sec": round(time.perf_counter() - started_at, 3),
                    "timeout_sec": timeout_sec,
                })
                return timeout_result
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def handle_tool_calls(
    tool_calls: List[Dict[str, Any]],
    tools: ToolRegistry,
    drive_logs: pathlib.Path,
    task_id: str,
    stateful_executor: StatefulToolExecutor,
    messages: List[Dict[str, Any]],
    llm_trace: Dict[str, Any],
    emit_progress: Callable[[str], None],
) -> int:
    """
    Execute tool calls and append results to messages.

    Returns: Number of errors encountered
    """
    can_parallel = (
        len(tool_calls) > 1 and
        all(
            tc.get("function", {}).get("name") in READ_ONLY_PARALLEL_TOOLS
            for tc in tool_calls
        )
    )

    if not can_parallel:
        results = [
            _execute_with_timeout(tools, tc, drive_logs,
                                  _get_tool_timeout(tools, tc["function"]["name"]), task_id,
                                  stateful_executor)
            for tc in tool_calls
        ]
    else:
        max_workers = min(len(tool_calls), 8)
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_to_index = {
                executor.submit(
                    _execute_with_timeout, tools, tc, drive_logs,
                    _get_tool_timeout(tools, tc["function"]["name"]), task_id,
                    stateful_executor,
                ): idx
                for idx, tc in enumerate(tool_calls)
            }
            results = [None] * len(tool_calls)
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    results[idx] = future.result()
                except Exception as exc:
                    tc = tool_calls[idx]
                    fn_name = tc.get("function", {}).get("name", "unknown")
                    results[idx] = {
                        "tool_call_id": tc.get("id", ""),
                        "fn_name": fn_name,
                        "result": f"⚠️ TOOL_ERROR: Unexpected error: {exc}",
                        "is_error": True,
                        "tool_args": {},
                        "args_for_log": {},
                        "is_code_tool": fn_name in tools.CODE_TOOLS,
                    }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    return process_tool_results(results, messages, llm_trace, emit_progress)


def process_tool_results(
    results: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    llm_trace: Dict[str, Any],
    emit_progress: Callable[[str], None],
) -> int:
    """
    Process tool execution results and append to messages/trace.

    Returns: Number of errors encountered
    """
    error_count = 0

    for exec_result in results:
        fn_name = exec_result["fn_name"]
        is_error = exec_result["is_error"]

        if is_error:
            error_count += 1

        truncated_result = _truncate_tool_result(
            exec_result["result"],
            tool_name=fn_name,
            tool_args=exec_result.get("tool_args"),
        )

        messages.append({
            "role": "tool",
            "tool_call_id": exec_result["tool_call_id"],
            "content": truncated_result
        })

        llm_trace["tool_calls"].append({
            "tool": fn_name,
            "args": _safe_args(exec_result["args_for_log"]),
            "result": truncate_for_log(exec_result["result"], 700),
            "is_error": is_error,
        })

    return error_count


def _safe_args(v: Any) -> Any:
    """Ensure args are JSON-serializable for trace logging."""
    try:
        return json.loads(json.dumps(v, ensure_ascii=False, default=str))
    except Exception:
        log.debug("Failed to serialize args for trace logging", exc_info=True)
        return {"_repr": repr(v)}
