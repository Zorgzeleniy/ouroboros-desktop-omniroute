"""
Ouroboros Agent Server — Self-editable entry point.

This file lives in REPO_DIR and can be modified by the agent.
It runs as a subprocess of the launcher, serving the web UI and
coordinating the supervisor/worker system.

Starlette + uvicorn on localhost:{PORT}.
"""

import argparse
import asyncio
import collections
import importlib.util
import json
import logging
import mimetypes
import os
import pathlib
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse, FileResponse
from starlette.routing import Route, Mount, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

import uvicorn

from ouroboros import get_version
from ouroboros.utils import safe_relpath

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_DIR = pathlib.Path(os.environ.get("OUROBOROS_REPO_DIR", pathlib.Path(__file__).parent))
DATA_DIR = pathlib.Path(os.environ.get("OUROBOROS_DATA_DIR",
    pathlib.Path.home() / "Ouroboros" / "data"))
DEFAULT_HOST = os.environ.get("OUROBOROS_SERVER_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("OUROBOROS_SERVER_PORT", "8765"))

sys.path.insert(0, str(REPO_DIR))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_log_dir = DATA_DIR / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
from logging.handlers import RotatingFileHandler
_file_handler = RotatingFileHandler(
    _log_dir / "server.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, handlers=[_file_handler, logging.StreamHandler()])
log = logging.getLogger("server")

# ---------------------------------------------------------------------------
# Restart signal
# ---------------------------------------------------------------------------
RESTART_EXIT_CODE = 42
PANIC_EXIT_CODE = 99
_restart_requested = threading.Event()

# ---------------------------------------------------------------------------
# WebSocket connections manager
# ---------------------------------------------------------------------------
_ws_clients: List[WebSocket] = []
_ws_lock = threading.Lock()


def _has_ws_clients() -> bool:
    with _ws_lock:
        return bool(_ws_clients)

async def broadcast_ws(msg: dict) -> None:
    """Send a message to all connected WebSocket clients."""
    data = json.dumps(msg, ensure_ascii=False, default=str)
    with _ws_lock:
        clients = list(_ws_clients)
    dead = []
    for ws in clients:
        try:
            await ws.send_text(data)
        except Exception:
            log.debug("Dropping dead WebSocket client during broadcast", exc_info=True)
            dead.append(ws)
    if dead:
        with _ws_lock:
            for ws in dead:
                try:
                    _ws_clients.remove(ws)
                except ValueError:
                    pass


def broadcast_ws_sync(msg: dict) -> None:
    """Thread-safe sync wrapper for broadcasting.

    Uses the saved _event_loop reference (set in startup_event) rather than
    asyncio.get_event_loop(), which is unreliable from non-main threads
    in Python 3.10+.
    """
    loop = _event_loop
    if loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(broadcast_ws(msg), loop)
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Settings (single source of truth: ouroboros.config)
# ---------------------------------------------------------------------------
from ouroboros.config import (
    SETTINGS_DEFAULTS as _SETTINGS_DEFAULTS,
    load_settings, save_settings, apply_settings_to_env as _apply_settings_to_env,
)
from ouroboros.server_runtime import has_local_routing, setup_remote_if_configured, ws_heartbeat_loop


# ---------------------------------------------------------------------------
# Supervisor integration
# ---------------------------------------------------------------------------
_supervisor_ready = threading.Event()
_supervisor_error: Optional[str] = None
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def _run_supervisor(settings: dict) -> None:
    """Initialize and run the supervisor loop. Called in a background thread."""
    global _supervisor_error

    _apply_settings_to_env(settings)

    try:
        from supervisor.message_bus import init as bus_init
        from supervisor.message_bus import LocalChatBridge

        bridge = LocalChatBridge()
        bridge._broadcast_fn = broadcast_ws_sync

        from ouroboros.utils import set_log_sink
        set_log_sink(bridge.push_log)

        bus_init(
            drive_root=DATA_DIR,
            total_budget_limit=float(settings.get("TOTAL_BUDGET", 10.0)),
            budget_report_every=10,
            chat_bridge=bridge,
        )

        from supervisor.state import init as state_init, init_state, load_state, save_state
        from supervisor.state import append_jsonl, update_budget_from_usage, rotate_chat_log_if_needed
        state_init(DATA_DIR, float(settings.get("TOTAL_BUDGET", 10.0)))
        init_state()

        from supervisor.git_ops import init as git_ops_init, ensure_repo_present, safe_restart
        git_ops_init(
            repo_dir=REPO_DIR, drive_root=DATA_DIR, remote_url="",
            branch_dev="ouroboros", branch_stable="ouroboros-stable",
        )
        ensure_repo_present()
        setup_remote_if_configured(settings, log)
        ok, msg = safe_restart(reason="bootstrap", unsynced_policy="rescue_and_reset")
        if not ok:
            log.error("Supervisor bootstrap failed: %s", msg)

        from supervisor.queue import (
            enqueue_task, enforce_task_timeouts, enqueue_evolution_task_if_needed,
            persist_queue_snapshot, restore_pending_from_snapshot,
            cancel_task_by_id, queue_review_task, sort_pending,
        )
        from supervisor.workers import (
            init as workers_init, get_event_q, WORKERS, PENDING, RUNNING,
            spawn_workers, kill_workers, assign_tasks, ensure_workers_healthy,
            handle_chat_direct, _get_chat_agent, auto_resume_after_restart,
        )

        max_workers = int(settings.get("OUROBOROS_MAX_WORKERS", 5))
        soft_timeout = int(settings.get("OUROBOROS_SOFT_TIMEOUT_SEC", 600))
        hard_timeout = int(settings.get("OUROBOROS_HARD_TIMEOUT_SEC", 1800))

        workers_init(
            repo_dir=REPO_DIR, drive_root=DATA_DIR, max_workers=max_workers,
            soft_timeout=soft_timeout, hard_timeout=hard_timeout,
            total_budget_limit=float(settings.get("TOTAL_BUDGET", 10.0)),
            branch_dev="ouroboros", branch_stable="ouroboros-stable",
        )

        from supervisor.events import dispatch_event
        from supervisor.message_bus import send_with_budget
        from ouroboros.consciousness import BackgroundConsciousness
        import types
        import queue as _queue_mod

        kill_workers()
        spawn_workers(max_workers)
        restored_pending = restore_pending_from_snapshot()
        persist_queue_snapshot(reason="startup")

        if restored_pending > 0:
            st_boot = load_state()
            if st_boot.get("owner_chat_id"):
                send_with_budget(int(st_boot["owner_chat_id"]),
                    f"♻️ Restored pending queue from snapshot: {restored_pending} tasks.")

        auto_resume_after_restart()

        def _get_owner_chat_id() -> Optional[int]:
            try:
                st = load_state()
                cid = st.get("owner_chat_id")
                return int(cid) if cid else None
            except Exception:
                return None

        _consciousness = BackgroundConsciousness(
            drive_root=DATA_DIR, repo_dir=REPO_DIR,
            event_queue=get_event_q(), owner_chat_id_fn=_get_owner_chat_id,
        )

        _bg_st = load_state()
        if _bg_st.get("bg_consciousness_enabled"):
            _consciousness.start()
            log.info("Background consciousness auto-restored from saved state.")

        _event_ctx = types.SimpleNamespace(
            DRIVE_ROOT=DATA_DIR, REPO_DIR=REPO_DIR,
            BRANCH_DEV="ouroboros", BRANCH_STABLE="ouroboros-stable",
            bridge=bridge, WORKERS=WORKERS, PENDING=PENDING, RUNNING=RUNNING,
            MAX_WORKERS=max_workers,
            send_with_budget=send_with_budget, load_state=load_state, save_state=save_state,
            update_budget_from_usage=update_budget_from_usage, append_jsonl=append_jsonl,
            enqueue_task=enqueue_task, cancel_task_by_id=cancel_task_by_id,
            queue_review_task=queue_review_task, persist_queue_snapshot=persist_queue_snapshot,
            safe_restart=safe_restart, kill_workers=kill_workers, spawn_workers=spawn_workers,
            sort_pending=sort_pending, consciousness=_consciousness,
            request_restart=_request_restart_exit,
        )
    except Exception as exc:
        _supervisor_error = f"Supervisor init failed: {exc}"
        log.critical("Supervisor initialization failed", exc_info=True)
        _supervisor_ready.set()
        return

    _supervisor_ready.set()
    log.info("Supervisor ready.")

    # Main supervisor loop
    offset = 0
    crash_count = 0
    while not _restart_requested.is_set():
        try:
            rotate_chat_log_if_needed(DATA_DIR)
            ensure_workers_healthy()

            event_q = get_event_q()
            while True:
                try:
                    evt = event_q.get_nowait()
                except _queue_mod.Empty:
                    break
                if evt.get("type") == "restart_request":
                    _handle_restart_in_supervisor(evt, _event_ctx)
                    continue
                dispatch_event(evt, _event_ctx)

            enforce_task_timeouts()
            enqueue_evolution_task_if_needed()
            assign_tasks()
            persist_queue_snapshot(reason="main_loop")

            # Process messages from WebSocket bridge
            updates = bridge.get_updates(offset=offset, timeout=1)
            for upd in updates:
                offset = int(upd["update_id"]) + 1
                msg = upd.get("message") or {}
                if not msg:
                    continue

                chat_id = 1
                user_id = 1
                text = str(msg.get("text") or "")
                now_iso = datetime.now(timezone.utc).isoformat()

                st = load_state()
                if st.get("owner_id") is None:
                    st["owner_id"] = user_id
                    st["owner_chat_id"] = chat_id

                from supervisor.message_bus import log_chat
                log_chat("in", chat_id, user_id, text)
                st["last_owner_message_at"] = now_iso
                save_state(st)

                if not text:
                    continue

                lowered = text.strip().lower()
                if lowered.startswith("/panic"):
                    send_with_budget(chat_id, "🛑 PANIC: killing everything. App will close.")
                    _execute_panic_stop(_consciousness, kill_workers)
                elif lowered.startswith("/restart"):
                    send_with_budget(chat_id, "♻️ Restarting (soft).")
                    ok, restart_msg = safe_restart(reason="owner_restart", unsynced_policy="rescue_and_reset")
                    if not ok:
                        send_with_budget(chat_id, f"⚠️ Restart cancelled: {restart_msg}")
                        continue
                    kill_workers()
                    _request_restart_exit()
                elif lowered.startswith("/review"):
                    queue_review_task(reason="owner:/review", force=True)
                elif lowered.startswith("/evolve"):
                    parts = lowered.split()
                    action = parts[1] if len(parts) > 1 else "on"
                    turn_on = action not in ("off", "stop", "0")
                    st2 = load_state()
                    st2["evolution_mode_enabled"] = bool(turn_on)
                    if turn_on:
                        st2["evolution_consecutive_failures"] = 0
                    save_state(st2)
                    if not turn_on:
                        PENDING[:] = [t for t in PENDING if str(t.get("type")) != "evolution"]
                        sort_pending()
                        persist_queue_snapshot(reason="evolve_off")
                    state_str = "ON" if turn_on else "OFF"
                    send_with_budget(chat_id, f"🧬 Evolution: {state_str}")
                elif lowered.startswith("/bg"):
                    parts = lowered.split()
                    action = parts[1] if len(parts) > 1 else "status"
                    if action in ("start", "on", "1"):
                        result = _consciousness.start()
                        _bg_s = load_state(); _bg_s["bg_consciousness_enabled"] = True; save_state(_bg_s)
                        send_with_budget(chat_id, f"🧠 {result}")
                    elif action in ("stop", "off", "0"):
                        result = _consciousness.stop()
                        _bg_s = load_state(); _bg_s["bg_consciousness_enabled"] = False; save_state(_bg_s)
                        send_with_budget(chat_id, f"🧠 {result}")
                    else:
                        bg_status = "running" if _consciousness.is_running else "stopped"
                        send_with_budget(chat_id, f"🧠 Background consciousness: {bg_status}")
                elif lowered.startswith("/status"):
                    from supervisor.state import status_text
                    status = status_text(WORKERS, PENDING, RUNNING, soft_timeout, hard_timeout)
                    send_with_budget(chat_id, status, force_budget=True)
                else:
                    _consciousness.inject_observation(f"Owner message: {text}")
                    agent = _get_chat_agent()
                    if agent._busy:
                        agent.inject_message(text)
                    else:
                        _consciousness.pause()
                        def _run_and_resume(cid, txt):
                            try:
                                handle_chat_direct(cid, txt, None)
                            finally:
                                _consciousness.resume()
                        threading.Thread(
                            target=_run_and_resume, args=(chat_id, text), daemon=True,
                        ).start()

            crash_count = 0
            time.sleep(0.5)

        except Exception as exc:
            crash_count += 1
            log.error("Supervisor loop crash #%d: %s", crash_count, exc, exc_info=True)
            if crash_count >= 3:
                log.critical("Supervisor exceeded max retries.")
                return
            time.sleep(min(30, 2 ** crash_count))


def _handle_restart_in_supervisor(evt: Dict[str, Any], ctx: Any) -> None:
    """Handle restart request from agent — graceful shutdown + exit(42)."""
    st = ctx.load_state()
    if st.get("owner_chat_id"):
        ctx.send_with_budget(
            int(st["owner_chat_id"]),
            f"♻️ Restart requested by agent: {evt.get('reason')}",
        )
    ok, msg = ctx.safe_restart(
        reason="agent_restart_request", unsynced_policy="rescue_and_reset",
    )
    if not ok:
        if st.get("owner_chat_id"):
            ctx.send_with_budget(int(st["owner_chat_id"]), f"⚠️ Restart skipped: {msg}")
        return
    ctx.kill_workers()
    st2 = ctx.load_state()
    st2["session_id"] = uuid.uuid4().hex
    ctx.save_state(st2)
    ctx.persist_queue_snapshot(reason="pre_restart_exit")
    _request_restart_exit()


def _request_restart_exit() -> None:
    """Signal the server to shut down with restart exit code."""
    _restart_requested.set()


def _execute_panic_stop(consciousness, kill_workers_fn) -> None:
    """Full emergency stop: kill everything, write panic flag, hard-exit.

    This is intentionally harsh — os._exit() bypasses atexit handlers.
    All critical cleanup is done manually before the exit call.
    """
    log.critical("PANIC STOP initiated.")
    try:
        consciousness.stop()
    except Exception:
        pass

    try:
        from supervisor.state import load_state, save_state
        st = load_state()
        st["evolution_mode_enabled"] = False
        st["bg_consciousness_enabled"] = False
        save_state(st)
    except Exception:
        pass

    # Write panic flag to prevent auto-resume on next manual launch
    try:
        panic_flag = DATA_DIR / "state" / "panic_stop.flag"
        panic_flag.parent.mkdir(parents=True, exist_ok=True)
        panic_flag.write_text("panic", encoding="utf-8")
    except Exception:
        pass

    # Kill local model server if running
    try:
        from ouroboros.local_model import get_manager
        get_manager().stop_server()
    except Exception:
        pass

    # Kill all tracked subprocess process groups (claude CLI, shell, etc.)
    try:
        from ouroboros.tools.shell import kill_all_tracked_subprocesses
        kill_all_tracked_subprocesses()
    except Exception:
        pass

    try:
        kill_workers_fn(force=True)
    except Exception:
        pass

    log.critical("PANIC STOP complete — hard exit with code %d.", PANIC_EXIT_CODE)
    os._exit(PANIC_EXIT_CODE)


# ---------------------------------------------------------------------------
# HTTP/WebSocket routes
# ---------------------------------------------------------------------------
APP_START = time.time()


async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    with _ws_lock:
        _ws_clients.append(websocket)
    log.info("WebSocket client connected (total: %d)", len(_ws_clients))
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")
            payload = msg.get("content", "") if msg_type == "chat" else msg.get("cmd", "")
            if msg_type in ("chat", "command") and payload:
                try:
                    from supervisor.message_bus import get_bridge
                    bridge = get_bridge()
                    bridge.ui_send(payload)
                except Exception:
                    ts = datetime.now(timezone.utc).isoformat()
                    await websocket.send_text(json.dumps({
                        "type": "chat", "role": "assistant",
                        "content": "⚠️ System is still initializing. Please wait a moment and try again.",
                        "ts": ts,
                    }))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("WebSocket error: %s", e)
    finally:
        with _ws_lock:
            try:
                _ws_clients.remove(websocket)
            except ValueError:
                pass
        log.info("WebSocket client disconnected (total: %d)", len(_ws_clients))


async def api_health(request: Request) -> JSONResponse:
    runtime_version = get_version()
    app_version = os.environ.get("OUROBOROS_APP_VERSION", "").strip() or runtime_version
    return JSONResponse({
        "status": "ok",
        # legacy field for backward compatibility
        "version": runtime_version,
        "runtime_version": runtime_version,
        "app_version": app_version,
    })


async def api_state(request: Request) -> JSONResponse:
    try:
        from supervisor.state import load_state, budget_remaining, budget_pct, TOTAL_BUDGET_LIMIT
        from supervisor.workers import WORKERS, PENDING, RUNNING
        st = load_state()
        alive = 0
        total_w = 0
        try:
            alive = sum(1 for w in WORKERS.values() if w.proc.is_alive())
            total_w = len(WORKERS)
        except Exception:
            pass
        spent = float(st.get("spent_usd") or 0.0)
        limit = float(TOTAL_BUDGET_LIMIT or 10.0)
        return JSONResponse({
            "uptime": int(time.time() - APP_START),
            "workers_alive": alive,
            "workers_total": total_w,
            "pending_count": len(PENDING),
            "running_count": len(RUNNING),
            "spent_usd": round(spent, 4),
            "budget_limit": limit,
            "budget_pct": round((spent / limit * 100) if limit > 0 else 0, 1),
            "branch": st.get("current_branch", "ouroboros"),
            "sha": (st.get("current_sha") or "")[:8],
            "evolution_enabled": bool(st.get("evolution_mode_enabled")),
            "bg_consciousness_enabled": bool(st.get("bg_consciousness_enabled")),
            "evolution_cycle": int(st.get("evolution_cycle") or 0),
            "spent_calls": int(st.get("spent_calls") or 0),
            "supervisor_ready": _supervisor_ready.is_set(),
            "supervisor_error": _supervisor_error,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_settings_get(request: Request) -> JSONResponse:
    settings = load_settings()
    safe = {k: v for k, v in settings.items()}
    for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN"):
        if safe.get(key):
            safe[key] = safe[key][:8] + "..." if len(safe[key]) > 8 else "***"
    return JSONResponse(safe)


async def api_settings_post(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        current = load_settings()
        for key in _SETTINGS_DEFAULTS:
            if key in body:
                current[key] = body[key]
        save_settings(current)
        _apply_settings_to_env(current)
        warnings = []
        _repo_slug = current.get("GITHUB_REPO", "")
        _gh_token = current.get("GITHUB_TOKEN", "")
        if _repo_slug and _gh_token:
            from supervisor.git_ops import configure_remote, migrate_remote_credentials
            remote_ok, remote_msg = configure_remote(_repo_slug, _gh_token)
            if not remote_ok:
                log.warning("Remote configuration failed on settings save: %s", remote_msg)
                warnings.append(f"Remote config failed: {remote_msg}")
            else:
                mig_ok, mig_msg = migrate_remote_credentials()
                if not mig_ok:
                    log.warning("Credential migration failed: %s", mig_msg)
        resp = {"status": "saved"}
        if warnings:
            resp["warnings"] = warnings
        return JSONResponse(resp)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


async def api_reset(request: Request) -> JSONResponse:
    """Reset all runtime data (state, memory, logs, settings) but keep repo.

    After reset the launcher will show the onboarding wizard on next start.
    """
    import shutil
    try:
        deleted = []
        for subdir in ("state", "memory", "logs", "archive", "locks", "task_results"):
            p = DATA_DIR / subdir
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)
                deleted.append(subdir)
        settings_file = DATA_DIR / "settings.json"
        if settings_file.exists():
            settings_file.unlink()
            deleted.append("settings.json")
        _request_restart_exit()
        return JSONResponse({"status": "ok", "deleted": deleted, "restarting": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_command(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        cmd = body.get("cmd", "")
        if cmd:
            from supervisor.message_bus import get_bridge
            bridge = get_bridge()
            bridge.ui_send(cmd)
        return JSONResponse({"status": "ok"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


async def api_git_log(request: Request) -> JSONResponse:
    """Return recent commits, tags, and current branch/sha."""
    try:
        from supervisor.git_ops import list_commits, list_versions, git_capture
        commits = list_commits(max_count=30)
        tags = list_versions(max_count=20)
        rc, branch, _ = git_capture(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        rc2, sha, _ = git_capture(["git", "rev-parse", "--short", "HEAD"])
        return JSONResponse({
            "commits": commits,
            "tags": tags,
            "branch": branch.strip() if rc == 0 else "unknown",
            "sha": sha.strip() if rc2 == 0 else "",
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_git_rollback(request: Request) -> JSONResponse:
    """Roll back to a specific commit or tag, then restart."""
    try:
        body = await request.json()
        target = body.get("target", "").strip()
        if not target:
            return JSONResponse({"error": "missing target"}, status_code=400)
        from supervisor.git_ops import rollback_to_version
        ok, msg = rollback_to_version(target, reason="ui_rollback")
        if not ok:
            return JSONResponse({"error": msg}, status_code=400)
        _request_restart_exit()
        return JSONResponse({"status": "ok", "message": msg})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_git_promote(request: Request) -> JSONResponse:
    """Promote current ouroboros branch to ouroboros-stable."""
    try:
        import subprocess as sp
        sp.run(["git", "branch", "-f", "ouroboros-stable", "ouroboros"],
               cwd=str(REPO_DIR), check=True, capture_output=True)
        return JSONResponse({"status": "ok", "message": "ouroboros-stable updated to match ouroboros"})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


_evo_cache: Dict[str, Any] = {}


async def api_evolution_data(request: Request) -> JSONResponse:
    """Collect evolution metrics for each git tag."""
    from ouroboros.utils import collect_evolution_metrics
    import time as _t

    now = _t.time()
    if _evo_cache.get("ts") and now - _evo_cache["ts"] < 60:
        return JSONResponse({"points": _evo_cache["points"]})

    data_dir = os.environ.get("OUROBOROS_DATA_DIR", os.path.expanduser("~/Ouroboros/data"))
    data_points = await collect_evolution_metrics(str(REPO_DIR), data_dir=data_dir)
    _evo_cache["ts"] = now
    _evo_cache["points"] = data_points
    return JSONResponse({"points": data_points})


_FILE_BROWSER_MAX_DIR_ENTRIES = 500
_FILE_BROWSER_MAX_READ_BYTES = 256 * 1024
_FILE_BROWSER_MAX_PREVIEW_CHARS = 120_000
_FILE_BROWSER_UPLOAD_CHUNK_SIZE = 1024 * 1024
_FILE_BROWSER_DEFAULT = os.environ.get("OUROBOROS_FILE_BROWSER_DEFAULT", "").strip()
_IMAGE_PREVIEW_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
_TEXT_PREVIEW_EXTENSIONS = {
    ".py", ".md", ".txt", ".json", ".jsonl", ".toml", ".yml", ".yaml",
    ".js", ".css", ".html", ".ts", ".tsx", ".jsx", ".ini", ".cfg",
    ".sh", ".zsh", ".bash", ".ps1", ".env", ".xml", ".csv",
}


def _normalize_file_browser_root(raw: str) -> pathlib.Path:
    text = (raw or "").strip()
    if not text:
        return pathlib.Path.home().resolve()
    return pathlib.Path(os.path.expanduser(os.path.expandvars(text))).resolve()


_FILE_BROWSER_ROOT_DIR = _normalize_file_browser_root(_FILE_BROWSER_DEFAULT)


def _format_file_browser_path(rel_path: str) -> str:
    rel = rel_path or "."
    root_dir = _get_file_browser_root()
    return str(root_dir) if rel in {"", "."} else str(root_dir / rel)


def _get_file_browser_root() -> pathlib.Path:
    try:
        if _FILE_BROWSER_ROOT_DIR.exists() and _FILE_BROWSER_ROOT_DIR.is_dir():
            return _FILE_BROWSER_ROOT_DIR
    except Exception:
        log.warning(
            "Invalid file browser default directory: default=%s",
            _FILE_BROWSER_DEFAULT,
            exc_info=True,
        )
    fallback = pathlib.Path.home().resolve()
    log.warning("Falling back to home directory for file browser root: %s", fallback)
    return fallback


def _resolve_file_browser_target(rel_path: str) -> pathlib.Path:
    root_dir = _get_file_browser_root()
    safe_path = safe_relpath(rel_path or ".")
    return root_dir / safe_path


def _guess_text_file(path: pathlib.Path) -> bool:
    if path.suffix.lower() in _TEXT_PREVIEW_EXTENSIONS:
        return True
    try:
        sample = path.read_bytes()[:4096]
    except Exception:
        return False
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _sanitize_upload_filename(filename: str) -> str:
    raw = (filename or "").replace("\\", "/").strip()
    name = pathlib.PurePosixPath(raw).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("Invalid upload filename.")
    if "/" in name:
        raise ValueError("Upload filename must not contain path separators.")
    return name


def _guess_media_type(path: pathlib.Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


async def api_files_list(request: Request) -> JSONResponse:
    root_dir = _get_file_browser_root()
    rel_path = request.query_params.get("path") or "."
    try:
        target = _resolve_file_browser_target(rel_path)
        if not target.exists():
            return JSONResponse({"error": f"Path not found: {rel_path}"}, status_code=404)
        if not target.is_dir():
            return JSONResponse({"error": f"Not a directory: {rel_path}"}, status_code=400)

        entries: List[Dict[str, Any]] = []
        for idx, entry in enumerate(sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))):
            if idx >= _FILE_BROWSER_MAX_DIR_ENTRIES:
                break
            item: Dict[str, Any] = {
                "name": entry.name,
                "path": entry.relative_to(root_dir).as_posix() or ".",
                "type": "dir" if entry.is_dir() else "file",
            }
            if entry.is_file():
                try:
                    item["size"] = int(entry.stat().st_size)
                except Exception:
                    item["size"] = None
            entries.append(item)

        target_rel = target.relative_to(root_dir).as_posix() or "."
        parts = [] if target_rel == "." else [part for part in target_rel.split("/") if part]
        breadcrumb = [{"name": str(root_dir), "path": "."}]
        accum: List[str] = []
        for part in parts:
            accum.append(part)
            breadcrumb.append({"name": part, "path": "/".join(accum)})

        parent_path = "."
        if target_rel != ".":
            parent_path = "/".join(parts[:-1]) if len(parts) > 1 else "."

        return JSONResponse({
            "root_path": str(root_dir),
            "path": target_rel,
            "display_path": _format_file_browser_path(target_rel),
            "parent_path": parent_path,
            "breadcrumb": breadcrumb,
            "entries": entries,
            "truncated": len(entries) >= _FILE_BROWSER_MAX_DIR_ENTRIES,
            "default_path": ".",
            "default_display_path": str(root_dir),
        })
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_files_read(request: Request) -> JSONResponse:
    rel_path = request.query_params.get("path", "")
    try:
        if not rel_path:
            return JSONResponse({"error": "Missing path."}, status_code=400)
        root_dir = _get_file_browser_root()
        target = _resolve_file_browser_target(rel_path)
        if not target.exists():
            return JSONResponse({"error": f"Path not found: {rel_path}"}, status_code=404)
        if not target.is_file():
            return JSONResponse({"error": f"Not a file: {rel_path}"}, status_code=400)

        size = int(target.stat().st_size)
        rel = target.relative_to(root_dir).as_posix()
        if target.suffix.lower() in _IMAGE_PREVIEW_EXTENSIONS:
            return JSONResponse({
                "root_path": str(root_dir),
                "path": rel,
                "display_path": _format_file_browser_path(rel),
                "name": target.name,
                "size": size,
                "is_text": False,
                "is_image": True,
                "media_type": _guess_media_type(target),
                "content_url": f"/api/files/content?path={rel}",
                "content": "",
                "truncated": False,
            })
        if not _guess_text_file(target):
            return JSONResponse({
                "root_path": str(root_dir),
                "path": rel,
                "display_path": _format_file_browser_path(rel),
                "name": target.name,
                "size": size,
                "is_text": False,
                "is_image": False,
                "content": "",
                "truncated": False,
            })

        raw = target.read_bytes()[:_FILE_BROWSER_MAX_READ_BYTES]
        text = raw.decode("utf-8", errors="replace")
        truncated = size > _FILE_BROWSER_MAX_READ_BYTES or len(text) > _FILE_BROWSER_MAX_PREVIEW_CHARS
        if len(text) > _FILE_BROWSER_MAX_PREVIEW_CHARS:
            text = text[:_FILE_BROWSER_MAX_PREVIEW_CHARS]

        return JSONResponse({
            "root_path": str(root_dir),
            "path": rel,
            "display_path": _format_file_browser_path(rel),
            "name": target.name,
            "size": size,
            "is_text": True,
            "is_image": False,
            "content": text,
            "truncated": truncated,
        })
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_files_download(request: Request) -> FileResponse | JSONResponse:
    rel_path = request.query_params.get("path", "")
    try:
        if not rel_path:
            return JSONResponse({"error": "Missing path."}, status_code=400)
        target = _resolve_file_browser_target(rel_path)
        if not target.exists():
            return JSONResponse({"error": f"Path not found: {rel_path}"}, status_code=404)
        if not target.is_file():
            return JSONResponse({"error": f"Not a file: {rel_path}"}, status_code=400)
        return FileResponse(str(target), filename=target.name)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_files_content(request: Request) -> FileResponse | JSONResponse:
    rel_path = request.query_params.get("path", "")
    try:
        if not rel_path:
            return JSONResponse({"error": "Missing path."}, status_code=400)
        target = _resolve_file_browser_target(rel_path)
        if not target.exists():
            return JSONResponse({"error": f"Path not found: {rel_path}"}, status_code=404)
        if not target.is_file():
            return JSONResponse({"error": f"Not a file: {rel_path}"}, status_code=400)
        return FileResponse(str(target), media_type=_guess_media_type(target))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_files_write(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload."}, status_code=400)

    try:
        rel_path = str(payload.get("path") or "").strip()
        if not rel_path:
            return JSONResponse({"error": "Missing path."}, status_code=400)

        if "content" not in payload:
            return JSONResponse({"error": "Missing content."}, status_code=400)
        content = str(payload.get("content"))
        create = bool(payload.get("create"))

        target = _resolve_file_browser_target(rel_path)
        if not target.exists():
            if not create:
                return JSONResponse({"error": f"Path not found: {rel_path}"}, status_code=404)
            parent = target.parent
            if not parent.exists():
                return JSONResponse({"error": f"Parent directory not found: {parent}"}, status_code=404)
            if not parent.is_dir():
                return JSONResponse({"error": "Parent path is not a directory."}, status_code=400)
            tmp_target = target.with_name(f".{target.name}.editing")
            try:
                tmp_target.write_text(content, encoding="utf-8")
                tmp_target.replace(target)
            finally:
                if tmp_target.exists():
                    with suppress(Exception):
                        tmp_target.unlink()
            size = int(target.stat().st_size)
            root_dir = _get_file_browser_root()
            rel = target.relative_to(root_dir).as_posix()
            return JSONResponse({
                "ok": True,
                "created": True,
                "path": rel,
                "display_path": _format_file_browser_path(rel),
                "name": target.name,
                "size": size,
            })
        if not target.is_file():
            return JSONResponse({"error": f"Not a file: {rel_path}"}, status_code=400)
        if target.suffix.lower() in _IMAGE_PREVIEW_EXTENSIONS or not _guess_text_file(target):
            return JSONResponse({"error": "Only text files can be edited in the browser."}, status_code=400)

        tmp_target = target.with_name(f".{target.name}.editing")
        try:
            tmp_target.write_text(content, encoding="utf-8")
            tmp_target.replace(target)
        finally:
            if tmp_target.exists():
                with suppress(Exception):
                    tmp_target.unlink()

        size = int(target.stat().st_size)
        root_dir = _get_file_browser_root()
        rel = target.relative_to(root_dir).as_posix()
        return JSONResponse({
            "ok": True,
            "path": rel,
            "display_path": _format_file_browser_path(rel),
            "name": target.name,
            "size": size,
        })
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_files_mkdir(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload."}, status_code=400)

    try:
        rel_dir = str(payload.get("path") or ".").strip() or "."
        name = _sanitize_upload_filename(str(payload.get("name") or ""))
        target_dir = _resolve_file_browser_target(rel_dir)
        if not target_dir.exists():
            return JSONResponse({"error": f"Path not found: {rel_dir}"}, status_code=404)
        if not target_dir.is_dir():
            return JSONResponse({"error": f"Not a directory: {rel_dir}"}, status_code=400)

        destination = target_dir / name

        if destination.exists():
            return JSONResponse({"error": f"Path already exists: {name}"}, status_code=409)

        destination.mkdir(parents=False, exist_ok=False)
        rel = destination.relative_to(_get_file_browser_root()).as_posix()
        return JSONResponse({
            "ok": True,
            "path": rel,
            "display_path": _format_file_browser_path(rel),
            "name": destination.name,
            "type": "dir",
        })
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_files_delete(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload."}, status_code=400)

    try:
        rel_path = str(payload.get("path") or "").strip()
        if not rel_path:
            return JSONResponse({"error": "Missing path."}, status_code=400)

        target = _resolve_file_browser_target(rel_path)
        if not target.exists():
            return JSONResponse({"error": f"Path not found: {rel_path}"}, status_code=404)

        root_dir = _get_file_browser_root()
        rel = target.relative_to(root_dir).as_posix()

        if target.is_file():
            target.unlink()
            deleted_type = "file"
        elif target.is_dir():
            shutil.rmtree(target)
            deleted_type = "dir"
        else:
            return JSONResponse({"error": f"Unsupported path type: {rel_path}"}, status_code=400)

        return JSONResponse({
            "ok": True,
            "path": rel,
            "type": deleted_type,
        })
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_files_transfer(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload."}, status_code=400)

    try:
        source_rel = str(payload.get("source_path") or "").strip()
        dest_rel = str(payload.get("destination_dir") or ".").strip() or "."
        mode = str(payload.get("mode") or "copy").strip().lower()
        if not source_rel:
            return JSONResponse({"error": "Missing source_path."}, status_code=400)
        if mode not in {"copy", "move"}:
            return JSONResponse({"error": "Invalid mode. Expected copy or move."}, status_code=400)

        source = _resolve_file_browser_target(source_rel)
        dest_dir = _resolve_file_browser_target(dest_rel)
        if not source.exists():
            return JSONResponse({"error": f"Path not found: {source_rel}"}, status_code=404)
        if not dest_dir.exists():
            return JSONResponse({"error": f"Path not found: {dest_rel}"}, status_code=404)
        if not dest_dir.is_dir():
            return JSONResponse({"error": f"Not a directory: {dest_rel}"}, status_code=400)

        destination = dest_dir / source.name
        if destination == source:
            return JSONResponse({"error": "Source and destination are the same."}, status_code=409)
        if destination.exists():
            return JSONResponse({"error": f"Path already exists: {destination.name}"}, status_code=409)

        if source.is_dir():
            try:
                destination.relative_to(source)
            except ValueError:
                pass
            else:
                return JSONResponse({"error": "Cannot move or copy a directory into itself."}, status_code=400)

        if mode == "copy":
            if source.is_symlink():
                os.symlink(os.readlink(source), destination, target_is_directory=source.is_dir())
            elif source.is_dir():
                shutil.copytree(source, destination, symlinks=True)
            else:
                shutil.copy2(source, destination, follow_symlinks=False)
        else:
            shutil.move(str(source), str(destination))

        root_dir = _get_file_browser_root()
        rel = destination.relative_to(root_dir).as_posix()
        return JSONResponse({
            "ok": True,
            "mode": mode,
            "path": rel,
            "display_path": _format_file_browser_path(rel),
            "name": destination.name,
            "type": "dir" if destination.is_dir() else "file",
        })
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def api_files_upload(request: Request) -> JSONResponse:
    try:
        form = await request.form()
        rel_dir = str(form.get("path") or ".")
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            return JSONResponse({"error": "Missing file upload."}, status_code=400)

        target_dir = _resolve_file_browser_target(rel_dir)
        if not target_dir.exists():
            return JSONResponse({"error": f"Path not found: {rel_dir}"}, status_code=404)
        if not target_dir.is_dir():
            return JSONResponse({"error": f"Not a directory: {rel_dir}"}, status_code=400)

        filename = _sanitize_upload_filename(upload.filename or "")
        destination = target_dir / filename

        if destination.exists():
            return JSONResponse({"error": f"File already exists: {filename}"}, status_code=409)

        tmp_destination = destination.with_name(f".{destination.name}.uploading")
        bytes_written = 0
        try:
            with tmp_destination.open("wb") as out:
                while True:
                    chunk = await upload.read(_FILE_BROWSER_UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                    bytes_written += len(chunk)
            tmp_destination.replace(destination)
        finally:
            await upload.close()
            if tmp_destination.exists():
                with suppress(Exception):
                    tmp_destination.unlink()

        rel_file = destination.relative_to(_get_file_browser_root()).as_posix()
        return JSONResponse({
            "ok": True,
            "path": rel_file,
            "display_path": _format_file_browser_path(rel_file),
            "name": destination.name,
            "size": bytes_written,
        })
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def index_page(request: Request) -> FileResponse:
    index = web_dir / "index.html"
    if index.exists():
        return FileResponse(str(index), media_type="text/html")
    return HTMLResponse("<html><body><h1>Ouroboros — web/ not found</h1></body></html>", status_code=404)


async def api_cost_breakdown(request: Request) -> JSONResponse:
    """Aggregate llm_usage events from events.jsonl into cost breakdowns."""
    events_path = DATA_DIR / "logs" / "events.jsonl"
    by_model: Dict[str, Dict[str, Any]] = {}
    by_api_key: Dict[str, Dict[str, Any]] = {}
    by_model_category: Dict[str, Dict[str, Any]] = {}
    by_task_category: Dict[str, Dict[str, Any]] = {}
    total_cost = 0.0
    total_calls = 0

    def _acc(d, key):
        if key not in d:
            d[key] = {"cost": 0.0, "calls": 0}
        return d[key]

    try:
        if events_path.exists():
            with events_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    if evt.get("type") != "llm_usage":
                        continue
                    cost = float(evt.get("cost") or 0)
                    model = str(evt.get("model") or "unknown")
                    api_key_type = str(evt.get("api_key_type") or evt.get("provider") or "openrouter")
                    model_cat = str(evt.get("model_category") or "other")
                    task_cat = str(evt.get("category") or "task")

                    total_cost += cost
                    total_calls += 1

                    e = _acc(by_model, model)
                    e["cost"] += cost
                    e["calls"] += 1

                    e = _acc(by_api_key, api_key_type)
                    e["cost"] += cost
                    e["calls"] += 1

                    e = _acc(by_model_category, model_cat)
                    e["cost"] += cost
                    e["calls"] += 1

                    e = _acc(by_task_category, task_cat)
                    e["cost"] += cost
                    e["calls"] += 1
    except Exception:
        pass

    def _sorted(d):
        return dict(sorted(d.items(), key=lambda x: x[1]["cost"], reverse=True))

    return JSONResponse({
        "total_cost": round(total_cost, 4),
        "total_calls": total_calls,
        "by_model": _sorted(by_model),
        "by_api_key": _sorted(by_api_key),
        "by_model_category": _sorted(by_model_category),
        "by_task_category": _sorted(by_task_category),
    })


async def api_chat_history(request: Request) -> JSONResponse:
    """Return recent chat, system, and progress messages merged chronologically."""
    try:
        limit = max(0, min(int(request.query_params.get("limit", 1000)), 2000))
    except (ValueError, TypeError):
        limit = 1000

    combined: list = []

    # Read chat.jsonl
    chat_path = DATA_DIR / "logs" / "chat.jsonl"
    if chat_path.exists():
        try:
            with chat_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    direction = str(entry.get("direction", "")).lower()
                    role = {"in": "user", "out": "assistant", "system": "system"}.get(direction)
                    if role is None:
                        continue
                    combined.append({
                        "text": str(entry.get("text", "")),
                        "role": role,
                        "ts": str(entry.get("ts", "")),
                        "is_progress": False,
                        "system_type": str(entry.get("type", "")),
                        "markdown": str(entry.get("format", "")).lower() == "markdown",
                    })
        except Exception as e:
            log.warning("Failed to read chat history: %s", e)

    # Read progress.jsonl
    progress_path = DATA_DIR / "logs" / "progress.jsonl"
    if progress_path.exists():
        try:
            with progress_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    text = str(entry.get("content", entry.get("text", "")))
                    if not text:
                        continue
                    combined.append({
                        "text": text,
                        "role": "assistant",
                        "ts": str(entry.get("ts", "")),
                        "is_progress": True,
                        "markdown": str(entry.get("format", "")).lower() == "markdown",
                    })
        except Exception as e:
            log.warning("Failed to read progress log: %s", e)

    # Sort by timestamp, take last `limit`
    combined.sort(key=lambda m: m.get("ts", ""))
    messages = combined[-limit:] if len(combined) > limit else combined

    return JSONResponse({"messages": messages})

from ouroboros.local_model_api import (
    api_local_model_start, api_local_model_stop,
    api_local_model_status, api_local_model_test,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
web_dir = REPO_DIR / "web"


def _resolve_web_dir() -> pathlib.Path:
    repo_web_dir = REPO_DIR / "web"
    if repo_web_dir.exists():
        return repo_web_dir

    spec = importlib.util.find_spec("web")
    origin = getattr(spec, "origin", None) if spec else None
    if origin:
        package_dir = pathlib.Path(origin).resolve().parent
        if package_dir.exists():
            return package_dir

    return repo_web_dir


web_dir = _resolve_web_dir()
web_dir.mkdir(parents=True, exist_ok=True)

class NoCacheStaticFiles:
    """Wrap StaticFiles to add Cache-Control: no-cache headers.
    Forces PyWebView to always revalidate, preventing stale JS/CSS."""
    def __init__(self, **kwargs):
        self._app = StaticFiles(**kwargs)
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            async def send_with_no_cache(message):
                if message["type"] == "http.response.start":
                    headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-cache, must-revalidate"))
                    message = {**message, "headers": headers}
                await send(message)
            await self._app(scope, receive, send_with_no_cache)
        else:
            await self._app(scope, receive, send)

routes = [
    Route("/", endpoint=index_page),
    Route("/api/health", endpoint=api_health),
    Route("/api/state", endpoint=api_state),
    Route("/api/files/list", endpoint=api_files_list),
    Route("/api/files/read", endpoint=api_files_read),
    Route("/api/files/content", endpoint=api_files_content),
    Route("/api/files/write", endpoint=api_files_write, methods=["POST"]),
    Route("/api/files/mkdir", endpoint=api_files_mkdir, methods=["POST"]),
    Route("/api/files/delete", endpoint=api_files_delete, methods=["POST"]),
    Route("/api/files/transfer", endpoint=api_files_transfer, methods=["POST"]),
    Route("/api/files/download", endpoint=api_files_download),
    Route("/api/files/upload", endpoint=api_files_upload, methods=["POST"]),
    Route("/api/settings", endpoint=api_settings_get, methods=["GET"]),
    Route("/api/settings", endpoint=api_settings_post, methods=["POST"]),
    Route("/api/command", endpoint=api_command, methods=["POST"]),
    Route("/api/reset", endpoint=api_reset, methods=["POST"]),
    Route("/api/git/log", endpoint=api_git_log),
    Route("/api/git/rollback", endpoint=api_git_rollback, methods=["POST"]),
    Route("/api/git/promote", endpoint=api_git_promote, methods=["POST"]),
    Route("/api/cost-breakdown", endpoint=api_cost_breakdown),
    Route("/api/evolution-data", endpoint=api_evolution_data),
    Route("/api/chat/history", endpoint=api_chat_history),
    Route("/api/local-model/start", endpoint=api_local_model_start, methods=["POST"]),
    Route("/api/local-model/stop", endpoint=api_local_model_stop, methods=["POST"]),
    Route("/api/local-model/status", endpoint=api_local_model_status),
    Route("/api/local-model/test", endpoint=api_local_model_test, methods=["POST"]),
    WebSocketRoute("/ws", endpoint=ws_endpoint),
    Mount("/static", app=NoCacheStaticFiles(directory=str(web_dir)), name="static"),
]

from contextlib import asynccontextmanager, suppress


@asynccontextmanager
async def lifespan(app):
    global _event_loop
    _event_loop = asyncio.get_running_loop()
    ws_heartbeat_task = asyncio.create_task(
        ws_heartbeat_loop(_has_ws_clients, broadcast_ws),
        name="ws-heartbeat",
    )

    settings = load_settings()
    has_api_key = bool(settings.get("OPENROUTER_API_KEY"))
    has_local = has_local_routing(settings)

    if has_api_key or has_local:
        threading.Thread(target=_run_supervisor, args=(settings,), daemon=True).start()
    else:
        _supervisor_ready.set()
        log.info("No API key or local model configured. Supervisor not started.")

    if has_local and settings.get("LOCAL_MODEL_SOURCE"):
        from ouroboros.local_model_autostart import auto_start_local_model
        threading.Thread(
            target=auto_start_local_model, args=(settings,),
            daemon=True, name="local-model-autostart",
        ).start()

    try:
        yield
    finally:
        ws_heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await ws_heartbeat_task

        log.info("Server shutting down...")
        try:
            from ouroboros.local_model import get_manager
            get_manager().stop_server()
        except Exception:
            pass
        try:
            from ouroboros.tools.shell import kill_all_tracked_subprocesses
            kill_all_tracked_subprocesses()
        except Exception:
            pass
        try:
            from supervisor.workers import kill_workers
            kill_workers(force=True)
        except Exception:
            pass


app = Starlette(routes=routes, lifespan=lifespan)


# ---------------------------------------------------------------------------
# Port selection
# ---------------------------------------------------------------------------
PORT_FILE = DATA_DIR / "state" / "server_port"


def _find_free_port(host: str, start: int = 8765, max_tries: int = 10) -> int:
    """Try binding to *start* with SO_REUSEADDR (survives TIME_WAIT after restart).
    Falls back to scanning subsequent ports if the default is truly occupied."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, start))
            return start
        except OSError:
            pass
    for offset in range(1, max_tries):
        port = start + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
            return port
        except OSError:
            continue
    return start


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Ouroboros web server.")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Host interface to bind (default: %(default)s or OUROBOROS_SERVER_HOST).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to bind (default: %(default)s or OUROBOROS_SERVER_PORT).",
    )
    return parser.parse_args()


def _write_port_file(port: int) -> None:
    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORT_FILE.write_text(str(port), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    args = _parse_args()
    actual_port = _find_free_port(args.host, args.port)
    if actual_port != args.port:
        log.info("Port %d busy on %s, using %d instead", args.port, args.host, actual_port)
    _write_port_file(actual_port)
    log.info("Starting Ouroboros server on %s:%d", args.host, actual_port)
    config = uvicorn.Config(
        app,
        host=args.host,
        port=actual_port,
        log_level="warning",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )
    server = uvicorn.Server(config)

    def _check_restart():
        """Monitor for restart signal, then shut down uvicorn."""
        while not _restart_requested.is_set():
            time.sleep(0.5)
        log.info("Restart requested — closing WebSocket clients and shutting down server.")

        # Close all WebSocket connections so uvicorn can shut down cleanly
        loop = _event_loop
        if loop:
            async def _close_all_ws():
                with _ws_lock:
                    clients = list(_ws_clients)
                for ws in clients:
                    try:
                        await ws.close(code=1012, reason="Server restarting")
                    except Exception:
                        pass
            try:
                future = asyncio.run_coroutine_threadsafe(_close_all_ws(), loop)
                future.result(timeout=3)
            except Exception:
                pass

        server.should_exit = True

        # Safety net: if uvicorn doesn't exit within 5 seconds, force it
        time.sleep(5)
        log.warning("Uvicorn did not exit within 5s — forcing os._exit(%d)", RESTART_EXIT_CODE)
        os._exit(RESTART_EXIT_CODE)

    threading.Thread(target=_check_restart, daemon=True).start()

    server.run()

    if _restart_requested.is_set():
        log.info("Exiting with code %d (restart signal).", RESTART_EXIT_CODE)
        try:
            from ouroboros.tools.shell import kill_all_tracked_subprocesses
            kill_all_tracked_subprocesses()
        except Exception:
            pass
        try:
            from supervisor.workers import kill_workers
            kill_workers(force=True)
        except Exception:
            pass
        import multiprocessing
        from ouroboros.compat import force_kill_pid
        for child in multiprocessing.active_children():
            try:
                force_kill_pid(child.pid)
            except (ProcessLookupError, PermissionError):
                pass
        # Hard exit — sys.exit() can hang if threads/children are stuck
        os._exit(RESTART_EXIT_CODE)

    return 0


if __name__ == "__main__":
    sys.exit(main())
