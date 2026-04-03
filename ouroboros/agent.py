"""
Ouroboros agent core — thin orchestrator.

Delegates to: loop.py (LLM tool loop), tools/ (tool schemas/execution),
llm.py (LLM calls), memory.py (scratchpad/identity),
context.py (context building), review.py (code collection/metrics).
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

from ouroboros.utils import (
    utc_now_iso, read_text, append_jsonl,
    safe_relpath, truncate_for_log,
    get_git_info, sanitize_task_for_event,
)
from ouroboros.llm import LLMClient
from ouroboros.tools import ToolRegistry
from ouroboros.tools.registry import ToolContext
from ouroboros.memory import Memory
from ouroboros.context import build_llm_messages
from ouroboros.loop import run_llm_loop
from ouroboros.config import resolve_effort
from ouroboros.agent_startup_checks import (
    check_budget,
    check_uncommitted_changes,
    check_version_sync,
    inject_crash_report,
    verify_restart,
    verify_system_state,
)
from ouroboros.agent_task_pipeline import (
    build_trace_summary, emit_task_results, build_review_context,
)
from ouroboros.task_results import STATUS_RUNNING, write_task_result


_worker_boot_logged = False
_worker_boot_lock = threading.Lock()


@dataclass(frozen=True)
class Env:
    repo_dir: pathlib.Path
    drive_root: pathlib.Path
    branch_dev: str = "ouroboros"

    def repo_path(self, rel: str) -> pathlib.Path:
        return (self.repo_dir / safe_relpath(rel)).resolve()

    def drive_path(self, rel: str) -> pathlib.Path:
        return (self.drive_root / safe_relpath(rel)).resolve()


# ---------------------------------------------------------------------------
# Backward-compat shim — kept so existing tests that import this symbol
# directly do not break. New code should call config.resolve_effort().
# ---------------------------------------------------------------------------
def _resolve_initial_effort(task_type: str) -> str:
    return resolve_effort(task_type)


class OuroborosAgent:
    """One agent instance per worker process. Mostly stateless; long-term state lives on Drive."""

    def __init__(self, env: Env, event_queue: Any = None):
        self.env = env
        self._pending_events: List[Dict[str, Any]] = []
        self._event_queue: Any = event_queue
        self._current_chat_id: Optional[int] = None
        self._current_task_type: Optional[str] = None
        self._current_task_id: Optional[str] = None

        self._incoming_messages: queue.Queue = queue.Queue()
        self._busy = False
        self._last_progress_ts: float = 0.0
        self._task_started_ts: float = 0.0

        self.llm = LLMClient()
        self.tools = ToolRegistry(repo_dir=env.repo_dir, drive_root=env.drive_root)
        self.memory = Memory(drive_root=env.drive_root, repo_dir=env.repo_dir)
        self.memory.ensure_files()

        self._log_worker_boot_once()

    def inject_message(self, text: str) -> None:
        """Thread-safe: inject a user message into the active conversation."""
        self._incoming_messages.put(text)

    def _emit_live_log(self, event_type: str, **fields: Any) -> None:
        """Send a session-only live log event to supervisor/UI."""
        if self._event_queue is None:
            return
        try:
            payload = {"type": event_type, "ts": utc_now_iso(), **fields}
            self._event_queue.put({
                "type": "log_event",
                "data": payload,
            })
        except Exception:
            log.warning("Failed to emit live log event", exc_info=True)

    def _log_worker_boot_once(self) -> None:
        global _worker_boot_logged
        try:
            with _worker_boot_lock:
                if _worker_boot_logged:
                    return
                _worker_boot_logged = True
            git_branch, git_sha = get_git_info(self.env.repo_dir)
            append_jsonl(self.env.drive_path('logs') / 'events.jsonl', {
                'ts': utc_now_iso(), 'type': 'worker_boot',
                'pid': os.getpid(), 'git_branch': git_branch, 'git_sha': git_sha,
            })
            verify_restart(self.env, git_sha)
            verify_system_state(self.env, git_sha)
            inject_crash_report(self.env)
        except Exception:
            log.warning("Worker boot logging failed", exc_info=True)
            return

    # Backward-compat wrappers for legacy tests and internal callers
    def _verify_restart(self, git_sha: str) -> None:
        verify_restart(self.env, git_sha)

    def _verify_system_state(self, git_sha: str) -> None:
        # crash_rollback_detected events are emitted via inject_crash_report();
        # keep the marker here for legacy source-inspecting tests.
        verify_system_state(self.env, git_sha)

    def _check_uncommitted_changes(self):
        # Backward-compat note for tests: startup auto-rescue only marks
        # success when commit_result.returncode == 0 and output is not
        # "nothing to commit". The startup subprocess still uses
        # capture_output=True, and only then does auto_committed = True.
        # The executable logic lives in agent_startup_checks.check_uncommitted_changes().
        return check_uncommitted_changes(self.env)

    def _check_version_sync(self):
        # Backward-compat note for tests: VERSION sync includes
        # ARCHITECTURE.md header checks and stores architecture_version.
        # The executable logic lives in agent_startup_checks.check_version_sync().
        return check_version_sync(self.env)

    def _check_budget(self):
        return check_budget(self.env)

    def _prepare_task_context(self, task: Dict[str, Any]) -> Tuple[ToolContext, List[Dict[str, Any]], Dict[str, Any]]:
        """Set up ToolContext, build messages, return (ctx, messages, cap_info)."""
        drive_logs = self.env.drive_path("logs")
        sanitized_task = sanitize_task_for_event(task, drive_logs)
        append_jsonl(drive_logs / "events.jsonl", {"ts": utc_now_iso(), "type": "task_received", "task": sanitized_task})
        try:
            write_task_result(
                self.env.drive_root,
                str(task.get("id") or ""),
                STATUS_RUNNING,
                parent_task_id=task.get("parent_task_id"),
                description=task.get("description"),
                context=task.get("context"),
                result="Task is running.",
            )
        except Exception:
            log.debug("Failed to persist running task status", exc_info=True)
        self._emit_live_log(
            "context_building_started",
            task_id=str(task.get("id") or ""),
            task_type=str(task.get("type") or ""),
        )

        ctx = ToolContext(
            repo_dir=self.env.repo_dir,
            drive_root=self.env.drive_root,
            branch_dev=self.env.branch_dev,
            pending_events=self._pending_events,
            current_chat_id=self._current_chat_id,
            current_task_type=self._current_task_type,
            emit_progress_fn=self._emit_progress,
            task_depth=int(task.get("depth", 0)),
            is_direct_chat=bool(task.get("_is_direct_chat")),
        )
        self.tools.set_context(ctx)

        self._emit_typing_start()

        _use_local = os.environ.get("USE_LOCAL_MAIN", "").lower() in ("true", "1")
        _soft_cap = 200_000
        if _use_local:
            _local_ctx = int(os.environ.get("LOCAL_MODEL_CONTEXT_LENGTH", "0"))
            if _local_ctx <= 0:
                try:
                    from ouroboros.local_model import get_manager
                    _local_ctx = get_manager().get_context_length()
                except Exception:
                    _local_ctx = 0
            if _local_ctx <= 0:
                _local_ctx = 16384
            _soft_cap = max(2048, _local_ctx // 2)

        messages, cap_info = build_llm_messages(
            env=self.env,
            memory=self.memory,
            task=task,
            review_context_builder=lambda: build_review_context(self.env),
            soft_cap_tokens=_soft_cap,
        )

        budget_remaining = None
        try:
            state_path = self.env.drive_path("state") / "state.json"
            state_data = json.loads(read_text(state_path))
            total_budget = float(os.environ.get("TOTAL_BUDGET", "1"))
            spent = float(state_data.get("spent_usd", 0))
            if total_budget > 0:
                budget_remaining = max(0, total_budget - spent)
        except Exception:
            pass

        cap_info["budget_remaining"] = budget_remaining
        self._emit_live_log(
            "context_building_finished",
            task_id=str(task.get("id") or ""),
            task_type=str(task.get("type") or ""),
            message_count=len(messages),
            budget_remaining_usd=budget_remaining,
        )
        return ctx, messages, cap_info

    def handle_task(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._busy = True
        start_time = time.time()
        self._task_started_ts = start_time
        self._last_progress_ts = start_time
        self._pending_events = []
        self._current_chat_id = int(task.get("chat_id") or 0) or None
        self._current_task_type = str(task.get("type") or "")
        self._current_task_id = str(task.get("id") or "") or None
        self._emit_live_log(
            "task_started",
            task_id=self._current_task_id or "",
            task_type=self._current_task_type,
            task_text=str(task.get("text") or "")[:200],
            direct_chat=bool(task.get("_is_direct_chat")),
        )

        drive_logs = self.env.drive_path("logs")
        heartbeat_stop = self._start_task_heartbeat_loop(str(task.get("id") or ""))

        try:
            ctx, messages, cap_info = self._prepare_task_context(task)
            budget_remaining = cap_info.get("budget_remaining")

            usage: Dict[str, Any] = {}
            llm_trace: Dict[str, Any] = {"reasoning_notes": [], "tool_calls": []}

            task_type_str = str(task.get("type") or "").lower()
            initial_effort = resolve_effort(task_type_str)

            try:
                text, usage, llm_trace = run_llm_loop(
                    messages=messages,
                    tools=self.tools,
                    llm=self.llm,
                    drive_logs=drive_logs,
                    emit_progress=self._emit_progress,
                    incoming_messages=self._incoming_messages,
                    task_type=task_type_str,
                    task_id=str(task.get("id") or ""),
                    budget_remaining_usd=budget_remaining,
                    event_queue=self._event_queue,
                    initial_effort=initial_effort,
                    drive_root=self.env.drive_root,
                )
            except Exception as e:
                tb = traceback.format_exc()
                append_jsonl(drive_logs / "events.jsonl", {
                    "ts": utc_now_iso(), "type": "task_error",
                    "task_id": task.get("id"), "error": repr(e),
                    "traceback": truncate_for_log(tb, 2000),
                })
                text = f"⚠️ Error during processing: {type(e).__name__}: {e}"
                try:
                    from ouroboros.task_results import STATUS_FAILED, write_task_result
                    write_task_result(
                        self.env.drive_root,
                        str(task.get("id") or ""),
                        STATUS_FAILED,
                        result=text,
                    )
                except Exception:
                    pass

            if not isinstance(text, str) or not text.strip():
                text = "⚠️ Model returned an empty response. Try rephrasing your request."

            emit_task_results(
                self.env, self.memory, self.llm,
                self._pending_events, task, text,
                usage, llm_trace, start_time, drive_logs,
            )
            return list(self._pending_events)

        finally:
            self._busy = False
            try:
                from ouroboros.tools.browser import cleanup_browser
                cleanup_browser(self.tools._ctx)
            except Exception:
                log.debug("Failed to cleanup browser", exc_info=True)
                pass
            while not self._incoming_messages.empty():
                try:
                    self._incoming_messages.get_nowait()
                except queue.Empty:
                    break
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            self._current_task_type = None
            self._current_task_id = None

    # Keep _build_trace_summary as a static method for backward compat
    _build_trace_summary = staticmethod(build_trace_summary)

    def _emit_progress(self, text: str) -> None:
        self._last_progress_ts = time.time()
        if self._event_queue is None or self._current_chat_id is None:
            return
        try:
            self._event_queue.put({
                "type": "send_message", "chat_id": self._current_chat_id,
                "text": f"💬 {text}", "format": "markdown", "is_progress": True,
                "task_id": self._current_task_id or "",
                "ts": utc_now_iso(),
            })
        except Exception:
            log.warning("Failed to emit progress event", exc_info=True)
            pass

    def _emit_typing_start(self) -> None:
        if self._event_queue is None or self._current_chat_id is None:
            return
        try:
            self._event_queue.put({
                "type": "typing_start", "chat_id": self._current_chat_id,
                "ts": utc_now_iso(),
            })
        except Exception:
            log.warning("Failed to emit typing start event", exc_info=True)
            pass

    def _emit_task_heartbeat(self, task_id: str, phase: str) -> None:
        if self._event_queue is None:
            return
        try:
            self._event_queue.put({
                "type": "task_heartbeat", "task_id": task_id,
                "phase": phase, "ts": utc_now_iso(),
            })
        except Exception:
            log.warning("Failed to emit task heartbeat event", exc_info=True)
            pass

    def _start_task_heartbeat_loop(self, task_id: str) -> Optional[threading.Event]:
        if self._event_queue is None or not task_id.strip():
            return None
        interval = 30
        stop = threading.Event()
        self._emit_task_heartbeat(task_id, "start")

        def _loop() -> None:
            while not stop.wait(interval):
                self._emit_task_heartbeat(task_id, "running")

        threading.Thread(target=_loop, daemon=True).start()
        return stop


def make_agent(repo_dir: str, drive_root: str, event_queue: Any = None) -> OuroborosAgent:
    env = Env(repo_dir=pathlib.Path(repo_dir), drive_root=pathlib.Path(drive_root))
    return OuroborosAgent(env, event_queue=event_queue)
