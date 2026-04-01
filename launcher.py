"""
Ouroboros Launcher — Immutable process manager.

This file is bundled into the .app via PyInstaller. It never self-modifies.
All agent logic lives in REPO_DIR and is launched as a subprocess via the
embedded python-build-standalone interpreter.

Responsibilities:
  - PID lock (single instance)
  - Bootstrap REPO_DIR on first run
  - Start/restart agent subprocess (server.py)
  - Display pywebview window pointing at agent's local HTTP server
  - Handle restart signals (agent exits with code 42)
"""

import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional

from ouroboros import get_version
from ouroboros.launcher_bootstrap import (
    BootstrapContext,
    bootstrap_repo as _bootstrap_repo,
    check_git as _check_git,
    install_deps as _install_deps_impl,
)
from ouroboros.compat import (
    IS_WINDOWS, IS_MACOS,
    embedded_python_candidates, kill_process_on_port, force_kill_pid,
    git_install_hint,
    create_kill_on_close_job, assign_pid_to_job, terminate_job, close_job,
    resume_process,
)

# ---------------------------------------------------------------------------
# Paths (single source of truth: ouroboros.config)
# ---------------------------------------------------------------------------
from ouroboros.config import (
    HOME, APP_ROOT, REPO_DIR, DATA_DIR, SETTINGS_PATH, PID_FILE, PORT_FILE,
    RESTART_EXIT_CODE, PANIC_EXIT_CODE, AGENT_SERVER_PORT,
    load_settings, save_settings, acquire_pid_lock, release_pid_lock,
)
from ouroboros.onboarding_wizard import build_onboarding_html, prepare_onboarding_settings
from ouroboros.server_runtime import apply_runtime_provider_defaults, has_startup_ready_provider
MAX_CRASH_RESTARTS = 5
CRASH_WINDOW_SEC = 120

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_log_dir = DATA_DIR / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)

from logging.handlers import RotatingFileHandler

_file_handler = RotatingFileHandler(
    _log_dir / "launcher.log", maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
_handlers: list = [_file_handler]
if not getattr(sys, "frozen", False):
    _handlers.append(logging.StreamHandler())
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, handlers=_handlers)
log = logging.getLogger("launcher")


APP_VERSION = get_version()

# Windows: prevent console windows when spawning subprocesses from the GUI app.
_SUBPROCESS_NO_WINDOW = (
    getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if IS_WINDOWS else 0
)


def _hidden_run(command, **kwargs):
    if _SUBPROCESS_NO_WINDOW:
        kwargs = dict(kwargs)
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _SUBPROCESS_NO_WINDOW
    return subprocess.run(command, **kwargs)


def _hidden_popen(command, **kwargs):
    if _SUBPROCESS_NO_WINDOW:
        kwargs = dict(kwargs)
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _SUBPROCESS_NO_WINDOW
    return subprocess.Popen(command, **kwargs)


# ---------------------------------------------------------------------------
# Embedded Python
# ---------------------------------------------------------------------------
def _find_embedded_python() -> str:
    """Locate the embedded python-build-standalone interpreter."""
    if getattr(sys, "frozen", False):
        base = pathlib.Path(sys._MEIPASS)
    else:
        base = pathlib.Path(__file__).parent
    for p in embedded_python_candidates(base):
        if p.exists():
            return str(p)
    return sys.executable


EMBEDDED_PYTHON = _find_embedded_python()


# ---------------------------------------------------------------------------
# Windows UI runtime
# ---------------------------------------------------------------------------
_windows_dll_dir_handles: list = []


def _show_windows_message(title: str, message: str) -> None:
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def _prepare_windows_webview_runtime() -> tuple[bool, str]:
    """Prepare pythonnet/pywebview runtime before importing webview on Windows."""
    if not IS_WINDOWS:
        return True, ""

    base_dir = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(sys.executable).parent))
    exe_dir = pathlib.Path(sys.executable).parent
    runtime_dir = base_dir / "pythonnet" / "runtime"
    webview_lib_dir = base_dir / "webview" / "lib"
    py_dll_name = f"python{sys.version_info[0]}{sys.version_info[1]}.dll"

    def _unblock_file(path: pathlib.Path) -> None:
        try:
            os.remove(f"{path}:Zone.Identifier")
        except OSError:
            pass

    def _unblock_tree(root: pathlib.Path) -> None:
        if not root.is_dir():
            return
        for child in root.rglob("*"):
            if child.is_file() and child.suffix.lower() in {".dll", ".exe", ".pyd"}:
                _unblock_file(child)

    py_dll_candidates = [
        base_dir / py_dll_name,
        exe_dir / py_dll_name,
    ]
    for root, _dirs, files in os.walk(base_dir):
        if py_dll_name in files:
            py_dll_candidates.append(pathlib.Path(root) / py_dll_name)
            if len(py_dll_candidates) >= 6:
                break

    py_dll_path = next((p for p in py_dll_candidates if p.is_file()), None)
    runtime_dll_path = runtime_dir / "Python.Runtime.dll"
    if not runtime_dll_path.is_file():
        for root, _dirs, files in os.walk(base_dir):
            if "Python.Runtime.dll" in files:
                runtime_dll_path = pathlib.Path(root) / "Python.Runtime.dll"
                break

    if py_dll_path is None:
        return False, f"Bundled {py_dll_name} was not found."
    if not runtime_dll_path.is_file():
        return False, "Bundled Python.Runtime.dll was not found."

    _unblock_file(py_dll_path)
    _unblock_file(runtime_dll_path)
    _unblock_tree(runtime_dll_path.parent)
    _unblock_tree(webview_lib_dir)

    os.environ["PYTHONNET_RUNTIME"] = "netfx"
    os.environ["PYTHONNET_PYDLL"] = str(py_dll_path)

    search_dirs = []
    for candidate in (base_dir, exe_dir, runtime_dir, runtime_dll_path.parent, py_dll_path.parent, webview_lib_dir):
        candidate_str = str(candidate)
        if candidate.is_dir() and candidate_str not in search_dirs:
            search_dirs.append(candidate_str)

    current_path_parts = os.environ.get("PATH", "").split(os.pathsep) if os.environ.get("PATH") else []
    os.environ["PATH"] = os.pathsep.join(search_dirs + [p for p in current_path_parts if p and p not in search_dirs])

    if hasattr(os, "add_dll_directory"):
        global _windows_dll_dir_handles
        for candidate in search_dirs:
            try:
                _windows_dll_dir_handles.append(os.add_dll_directory(candidate))
            except (FileNotFoundError, OSError):
                pass

    try:
        from clr_loader import get_netfx
        from pythonnet import set_runtime
        set_runtime(get_netfx())
    except Exception as exc:
        return False, f"Windows .NET runtime init failed: {exc}"

    return True, ""


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
def _bundle_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys._MEIPASS)
    return pathlib.Path(__file__).parent


def _bootstrap_context() -> BootstrapContext:
    return BootstrapContext(
        bundle_dir=_bundle_dir(),
        repo_dir=REPO_DIR,
        data_dir=DATA_DIR,
        settings_path=SETTINGS_PATH,
        embedded_python=EMBEDDED_PYTHON,
        app_version=APP_VERSION,
        hidden_run=_hidden_run,
        save_settings=save_settings,
        log=log,
    )


def check_git() -> bool:
    return _check_git(IS_WINDOWS)


def bootstrap_repo() -> None:
    _bootstrap_repo(_bootstrap_context())


def _install_deps() -> None:
    _install_deps_impl(_bootstrap_context())


# ---------------------------------------------------------------------------
# Agent process management
# ---------------------------------------------------------------------------
_agent_proc: Optional[subprocess.Popen] = None
_agent_job: Optional[object] = None          # Windows Job Object handle
_agent_lock = threading.Lock()
_shutdown_event = threading.Event()


def start_agent(port: int = AGENT_SERVER_PORT) -> subprocess.Popen:
    """Start the agent server.py as a subprocess."""
    global _agent_proc, _agent_job
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_DIR)
    env["OUROBOROS_SERVER_PORT"] = str(port)
    env["OUROBOROS_DATA_DIR"] = str(DATA_DIR)
    env["OUROBOROS_REPO_DIR"] = str(REPO_DIR)
    env["OUROBOROS_APP_VERSION"] = str(APP_VERSION)
    env["OUROBOROS_MANAGED_BY_LAUNCHER"] = "1"

    # Pass settings as env vars
    settings = _load_settings()
    for key, val in settings.items():
        if val:
            env[key] = str(val)

    server_py = REPO_DIR / "server.py"
    log.info("Starting agent: %s %s (port=%d)", EMBEDDED_PYTHON, server_py, port)

    popen_kwargs: dict = dict(
        cwd=str(REPO_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if IS_WINDOWS:
        from ouroboros.compat import _CREATE_SUSPENDED
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED
        )

    proc = _hidden_popen([EMBEDDED_PYTHON, str(server_py)], **popen_kwargs)
    _agent_proc = proc

    if IS_WINDOWS:
        job = create_kill_on_close_job()
        if job is None:
            log.error(
                "Failed to create Windows Job Object; refusing to run "
                "without process-tree ownership."
            )
            proc.kill()
            return proc
        if not assign_pid_to_job(job, proc.pid):
            log.error(
                "Failed to assign agent pid %d to Windows Job Object; "
                "refusing to run without process-tree ownership.",
                proc.pid,
            )
            close_job(job)
            proc.kill()
            return proc
        _agent_job = job
        if not resume_process(proc.pid):
            log.error("Failed to resume agent process %d — killing", proc.pid)
            with _agent_lock:
                if _agent_job is job:
                    _agent_job = None
            terminate_job(job)
            close_job(job)
            return proc
        log.info("Agent pid %d assigned to Windows Job Object", proc.pid)

    # Stream agent stdout to log file in background
    def _stream_output():
        log_path = DATA_DIR / "logs" / "agent_stdout.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                for line in iter(proc.stdout.readline, b""):
                    decoded = line.decode("utf-8", errors="replace")
                    f.write(decoded)
                    f.flush()
        except Exception:
            pass

    threading.Thread(target=_stream_output, daemon=True).start()
    return proc


def stop_agent() -> None:
    """Gracefully stop the agent process."""
    global _agent_proc, _agent_job
    with _agent_lock:
        if _agent_proc is None:
            return
        proc = _agent_proc
        job = _agent_job
        _agent_proc = None
        _agent_job = None
    log.info("Stopping agent (pid=%s)...", proc.pid)
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if IS_WINDOWS and job is not None:
            terminate_job(job)
        else:
            proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass
    if IS_WINDOWS and job is not None:
        close_job(job)


def _read_port_file() -> int:
    """Read the active port from PORT_FILE (written by server.py)."""
    try:
        if PORT_FILE.exists():
            return int(PORT_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        pass
    return AGENT_SERVER_PORT


def _kill_stale_on_port(port: int) -> None:
    """Kill any process listening on the given port (cleanup from previous runs)."""
    kill_process_on_port(port)


def _wait_for_server(port: int, timeout: float = 30.0) -> bool:
    """Wait for the agent HTTP server to become responsive."""
    import urllib.request
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _poll_port_file(timeout: float = 30.0) -> int:
    """Poll port file until it's freshly written (mtime within last 10s)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if PORT_FILE.exists():
                age = time.time() - PORT_FILE.stat().st_mtime
                if age < 10:
                    return int(PORT_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pass
        time.sleep(0.5)
    return _read_port_file()


_webview_window = None  # set by main(), used by lifecycle loop


def agent_lifecycle_loop(port: int = AGENT_SERVER_PORT) -> None:
    """Main loop: start agent, monitor, restart on exit code 42 or crash."""
    global _agent_proc, _agent_job
    crash_times: list = []

    # Kill anything left over from a previous launcher session
    _kill_stale_on_port(port)

    while not _shutdown_event.is_set():
        # Delete stale port file so _poll_port_file waits for a fresh write
        try:
            PORT_FILE.unlink(missing_ok=True)
        except OSError:
            pass

        proc = start_agent(port)

        # Wait for the server to write a fresh port file, then check health
        actual_port = _poll_port_file(timeout=30)
        if not _wait_for_server(actual_port, timeout=45):
            log.warning("Agent server did not become responsive within 45s (port %d)", actual_port)

        proc.wait()
        exit_code = proc.returncode
        log.info("Agent exited with code %d", exit_code)

        with _agent_lock:
            _agent_proc = None
            if IS_WINDOWS and _agent_job is not None:
                close_job(_agent_job)
                _agent_job = None

        if _shutdown_event.is_set():
            break

        # Panic stop: kill everything, close app, no restart
        if exit_code == PANIC_EXIT_CODE:
            log.info("Panic stop (exit code %d) — shutting down completely.", PANIC_EXIT_CODE)
            _shutdown_event.set()
            _kill_stale_on_port(port)
            import multiprocessing as _mp
            for child in _mp.active_children():
                force_kill_pid(child.pid)
            if _webview_window:
                try:
                    _webview_window.destroy()
                except Exception:
                    pass
            break

        # Wait for port to fully release after process exit
        time.sleep(2)

        if exit_code == RESTART_EXIT_CODE:
            log.info("Agent requested restart (exit code 42). Restarting...")
            _sync_existing_repo_from_bundle()
            _install_deps()
            _kill_stale_on_port(port)
            continue

        # Crash detection
        now = time.time()
        crash_times.append(now)
        crash_times[:] = [t for t in crash_times if (now - t) < CRASH_WINDOW_SEC]
        if len(crash_times) >= MAX_CRASH_RESTARTS:
            log.error("Agent crashed %d times in %ds. Stopping.", MAX_CRASH_RESTARTS, CRASH_WINDOW_SEC)
            break

        log.info("Agent crashed. Restarting in 3s...")
        _kill_stale_on_port(port)
        time.sleep(3)


# ---------------------------------------------------------------------------
# Settings (delegated to ouroboros.config)
# ---------------------------------------------------------------------------
def _load_settings() -> dict:
    return load_settings()


# ---------------------------------------------------------------------------
# First-run wizard
# ---------------------------------------------------------------------------
def _save_settings(settings: dict) -> None:
    save_settings(settings)


def _run_first_run_wizard() -> bool:
    """Show setup wizard if no runtime provider or local model is configured."""
    settings, provider_defaults_changed, _provider_default_keys = apply_runtime_provider_defaults(_load_settings())
    if provider_defaults_changed:
        _save_settings(settings)
    if has_startup_ready_provider(settings):
        return True

    import webview
    _wizard_done = {"ok": False}

    class WizardApi:
        def save_wizard(self, data: dict) -> str:
            prepared_settings, error = prepare_onboarding_settings(data, settings)
            if error:
                return error
            settings.update(prepared_settings)
            settings.update(apply_runtime_provider_defaults(settings)[0])
            try:
                _save_settings(settings)
                _wizard_done["ok"] = True
                for w in webview.windows:
                    w.destroy()
                return "ok"
            except Exception as e:
                return f"Failed to save: {e}"

    webview.create_window(
        "Ouroboros — Setup",
        html=build_onboarding_html(settings, host_mode="desktop"),
        js_api=WizardApi(),
        width=980,
        height=780,
        min_size=(840, 640),
    )
    webview.start()
    return _wizard_done["ok"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if IS_WINDOWS:
        ok, reason = _prepare_windows_webview_runtime()
        if not ok:
            log.error("Windows UI runtime initialization failed: %s", reason)
            _show_windows_message(
                "Ouroboros — Startup Failed",
                "Windows UI runtime initialization failed.\n\n"
                f"{reason}\n\n"
                "Check launcher.log for details.",
            )
            return

    import webview

    if not acquire_pid_lock():
        log.error("Another instance already running.")
        webview.create_window(
            "Ouroboros",
            html="<html><body style='background:#1a1a2e;color:white;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
                 "<div style='text-align:center'><h2>Ouroboros is already running</h2><p>Only one instance can run at a time.</p></div></body></html>",
            width=420, height=200,
        )
        webview.start()
        return

    import atexit
    atexit.register(release_pid_lock)

    # Check git
    if not check_git():
        log.warning("Git not found.")
        _result = {"installed": False}
        _hint = git_install_hint()

        def _git_page(window):
            window.evaluate_js("""
                document.getElementById('install-btn').onclick = function() {
                    document.getElementById('status').textContent = 'Installing... Please wait.';
                    window.pywebview.api.install_git();
                };
            """)

        class GitApi:
            def install_git(self):
                if IS_MACOS:
                    _hidden_popen(["xcode-select", "--install"])
                elif IS_WINDOWS:
                    _hidden_popen(["winget", "install", "Git.Git", "--source", "winget", "--accept-source-agreements"])
                else:
                    for cmd in [["sudo", "apt", "install", "-y", "git"],
                                ["sudo", "dnf", "install", "-y", "git"]]:
                        try:
                            _hidden_popen(cmd)
                            break
                        except FileNotFoundError:
                            continue
                for _ in range(300):
                    time.sleep(3)
                    if shutil.which("git"):
                        _result["installed"] = True
                        return "installed"
                return "timeout"

        git_window = webview.create_window(
            "Ouroboros — Setup Required",
            html=f"""<html><body style="background:#1a1a2e;color:white;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
            <div style="text-align:center">
                <h2>Git is required</h2>
                <p>Ouroboros needs Git to manage its local repository.</p>
                <p style="color:#94a3b8;font-size:13px;margin-top:8px">{_hint}</p>
                <button id="install-btn" style="padding:10px 24px;border-radius:8px;border:none;background:#0ea5e9;color:white;cursor:pointer;font-size:14px;margin-top:12px">
                    Install Git
                </button>
                <p id="status" style="color:#fbbf24;margin-top:12px"></p>
            </div></body></html>""",
            js_api=GitApi(),
            width=520, height=300,
        )
        webview.start(func=_git_page, args=[git_window])
        if not check_git():
            sys.exit(1)

    # Bootstrap
    bootstrap_repo()

    # First-run wizard (runtime provider)
    if not _run_first_run_wizard():
        log.info("Wizard was closed without saving. Launching anyway (Settings page available).")

    global _webview_window
    port = AGENT_SERVER_PORT

    # Start agent lifecycle in background
    lifecycle_thread = threading.Thread(target=agent_lifecycle_loop, args=(port,), daemon=True)
    lifecycle_thread.start()

    # Wait for server to be ready, then read actual port (may differ if default was busy)
    server_ready = _wait_for_server(port, timeout=15)
    actual_port = _read_port_file()
    if actual_port != port:
        server_ready = _wait_for_server(actual_port, timeout=45)
    else:
        server_ready = server_ready or _wait_for_server(port, timeout=45)

    if not server_ready:
        log.error("Agent failed to become healthy on port %d; aborting UI startup.", actual_port)
        _shutdown_event.set()
        stop_agent()
        lifecycle_thread.join(timeout=5)
        webview.create_window(
            "Ouroboros — Startup Failed",
            html=(
                "<html><body style='background:#1a1a2e;color:white;font-family:system-ui;"
                "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
                "<div style='text-align:center;max-width:460px;padding:24px'>"
                "<h2>Ouroboros failed to start</h2>"
                "<p>The local agent server did not become ready.</p>"
                "<p style='color:#94a3b8;font-size:13px;margin-top:10px'>"
                "Check launcher.log and agent_stdout.log in the Ouroboros data directory "
                "for details.</p>"
                "</div></body></html>"
            ),
            width=520,
            height=260,
        )
        webview.start()
        return

    url = f"http://127.0.0.1:{actual_port}"

    window = webview.create_window(
        f"Ouroboros v{APP_VERSION}",
        url=url,
        width=1100,
        height=750,
        min_size=(800, 500),
        background_color="#0d0b0f",
        text_select=True,
    )

    def _on_closing():
        log.info("Window closing — graceful shutdown.")
        _shutdown_event.set()
        stop_agent()
        _kill_orphaned_children()
        release_pid_lock()
        os._exit(0)

    def _kill_orphaned_children():
        """Final safety net: kill any processes still on the server port.

        After stop_agent() terminates server.py, worker grandchildren may
        survive as orphans.  Sweeping the port guarantees nothing lingers.
        """
        _kill_stale_on_port(port)
        _kill_stale_on_port(8766)
        for child in __import__('multiprocessing').active_children():
            force_kill_pid(child.pid)
            log.info("Killed orphaned child pid=%d", child.pid)

    window.events.closing += _on_closing
    _webview_window = window

    webview.start(debug=False)


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()

    if sys.platform == "darwin":
        try:
            _shell_path = subprocess.check_output(
                ["/bin/bash", "-l", "-c", "echo $PATH"], text=True, timeout=5,
            ).strip()
            if _shell_path:
                os.environ["PATH"] = _shell_path
        except Exception:
            pass

    main()
