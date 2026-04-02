"""Shell tools: run_shell, claude_code_edit."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import platform
import re
import shutil
import signal
import subprocess
import threading
import time
from subprocess import Popen, CompletedProcess
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from ouroboros.compat import IS_WINDOWS, PATH_SEP, kill_process_tree, node_download_info
from ouroboros.config import load_settings
from ouroboros.tools.registry import ToolContext, ToolEntry
from ouroboros.utils import utc_now_iso, run_cmd, append_jsonl, truncate_for_log

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Subprocess process-group registry (for panic kill)
# ---------------------------------------------------------------------------
_active_subprocesses: set = set()
_subprocess_lock = threading.Lock()

_RUN_SHELL_DEFAULT_TIMEOUT_SEC = 360
_CLAUDE_CODE_DEFAULT_TIMEOUT_SEC = 300


def _tracked_subprocess_run(cmd, **kwargs):
    """subprocess.run() replacement with process group tracking.

    Each subprocess gets its own session (start_new_session=True) so the
    entire process tree can be killed via os.killpg() on panic.
    """
    timeout = kwargs.pop("timeout", None)
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    proc = Popen(cmd, **kwargs)
    with _subprocess_lock:
        _active_subprocesses.add(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return CompletedProcess(proc.args, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        proc.wait(timeout=5)
        raise
    finally:
        with _subprocess_lock:
            _active_subprocesses.discard(proc)


def _kill_process_group(proc):
    """Kill a subprocess and its entire process tree."""
    kill_process_tree(proc)


def kill_all_tracked_subprocesses():
    """Kill all tracked subprocess trees. Called on panic."""
    with _subprocess_lock:
        procs = list(_active_subprocesses)
    for proc in procs:
        _kill_process_group(proc)
    with _subprocess_lock:
        _active_subprocesses.clear()


def _resolve_effective_timeout(default_timeout_sec: int) -> int:
    """Resolve effective timeout from settings.json with env fallback."""
    try:
        settings_val = int(load_settings().get("OUROBOROS_TOOL_TIMEOUT_SEC") or 0)
        if settings_val > 0:
            return settings_val
    except Exception:
        pass
    raw = str(os.environ.get("OUROBOROS_TOOL_TIMEOUT_SEC", "") or "").strip()
    if raw:
        try:
            parsed = int(raw)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return max(int(default_timeout_sec), 1)


def _describe_returncode(returncode: int) -> str:
    """Render a return code with signal details when applicable."""
    if int(returncode) < 0:
        signal_num = abs(int(returncode))
        try:
            signal_name = signal.Signals(signal_num).name
        except ValueError:
            signal_name = f"SIG{signal_num}"
        return f"exit_code={returncode} (signal={signal_name})"
    return f"exit_code={returncode}"


def _format_process_output(stdout: str, stderr: str, *, limit: int = 50_000) -> str:
    """Render stdout/stderr sections with truncation."""
    stdout_text = str(stdout or "").strip()
    stderr_text = str(stderr or "").strip()
    parts: List[str] = []
    if stdout_text:
        parts.append(f"STDOUT:\n{stdout_text}")
    if stderr_text:
        parts.append(f"STDERR:\n{stderr_text}")
    rendered = "\n\n".join(parts) if parts else "STDOUT:\n(empty)"
    if len(rendered) > limit:
        rendered = rendered[: limit // 2] + "\n...(truncated)...\n" + rendered[-limit // 2 :]
    return rendered


def _format_process_failure(prefix: str, action: str, res: CompletedProcess) -> str:
    """Render a subprocess failure with output context."""
    return (
        f"{prefix}: {action} with {_describe_returncode(res.returncode)}.\n\n"
        f"{_format_process_output(res.stdout or '', res.stderr or '')}"
    )


# ---------------------------------------------------------------------------
# Shell builtins / operators that cannot run via subprocess
# ---------------------------------------------------------------------------
_SHELL_BUILTINS = frozenset([
    "cd", "source", ".", "export", "alias", "eval",
    "set", "unset", "pushd", "popd", "read", "ulimit",
])

_SHELL_OPERATORS = frozenset(["&&", "||", "|", ";", ">", ">>", "<", "<<"])
_SHELL_INTERPRETERS = frozenset({
    "sh", "bash", "zsh", "fish",
    "cmd", "cmd.exe",
    "powershell", "powershell.exe",
    "pwsh", "pwsh.exe",
})
_ENV_REF_PATTERN = re.compile(r'\$(?:\{[A-Z][A-Z0-9_]*\}|[A-Z][A-Z0-9_]*)')


# ---------------------------------------------------------------------------
# run_shell
# ---------------------------------------------------------------------------
def _run_shell(ctx: ToolContext, cmd, cwd: str = "") -> str:
    if isinstance(cmd, str):
        return (
            '⚠️ SHELL_ARG_ERROR: `cmd` must be a JSON array of strings, not a plain string.\n\n'
            'Correct usage:\n'
            '  run_shell(cmd=["grep", "-r", "pattern", "path/"])\n'
            '  run_shell(cmd=["python", "-c", "print(1+1)"])\n\n'
            'Wrong usage:\n'
            '  run_shell(cmd="grep -r pattern path/")\n\n'
            'For reading files, prefer `repo_read` / `data_read`.\n'
            'For searching code, prefer `code_search`.'
        )

    if not isinstance(cmd, list):
        return "⚠️ SHELL_ARG_ERROR: cmd must be a list of strings."
    cmd = [str(x) for x in cmd]

    executable_name = pathlib.Path(cmd[0]).name.lower() if cmd else ""
    if executable_name not in _SHELL_INTERPRETERS:
        for arg in cmd:
            match = _ENV_REF_PATTERN.search(arg)
            if match:
                return (
                    f'⚠️ SHELL_ENV_ERROR: Found literal env reference "{match.group(0)}" in cmd array. '
                    "run_shell executes argv directly, so shell variables are not expanded. "
                    'Use ["sh", "-c", "..."] if you intentionally need shell expansion, '
                    "or read the environment variable inside the called program."
                )

    # Reject shell builtins (they are not executables)
    if cmd and cmd[0] in _SHELL_BUILTINS:
        if cmd[0] == "cd":
            return (
                '⚠️ SHELL_CMD_ERROR: "cd" is a shell builtin, not an executable. '
                'Use the "cwd" parameter instead: '
                'run_shell(cmd=["git", "log"], cwd="/target/dir")'
            )
        return (
            f'⚠️ SHELL_CMD_ERROR: "{cmd[0]}" is a shell builtin and cannot '
            'be executed directly via subprocess. '
            'Use ["sh", "-c", "your command"] if you need shell builtins.'
        )

    # Reject shell operators in cmd array (subprocess doesn't interpret them)
    found_ops = _SHELL_OPERATORS.intersection(cmd)
    if found_ops:
        op = sorted(found_ops)[0]
        return (
            f'⚠️ SHELL_CMD_ERROR: Shell operator "{op}" found in cmd array. '
            'Subprocess does not interpret shell syntax. '
            'Options: (1) Split into separate run_shell calls. '
            '(2) For pipes/chaining: ["sh", "-c", "cmd1 && cmd2"]'
        )

    work_dir = ctx.repo_dir
    if cwd and cwd.strip() not in ("", ".", "./"):
        candidate = (ctx.repo_dir / cwd).resolve()
        if candidate.exists() and candidate.is_dir():
            work_dir = candidate

    timeout_sec = _resolve_effective_timeout(_RUN_SHELL_DEFAULT_TIMEOUT_SEC)
    try:
        res = _tracked_subprocess_run(
            cmd, cwd=str(work_dir),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout_sec,
        )
        if res.returncode != 0:
            return _format_process_failure(
                "⚠️ SHELL_EXIT_ERROR",
                "command exited",
                res,
            )
        return f"exit_code=0\n{_format_process_output(res.stdout or '', res.stderr or '')}"
    except subprocess.TimeoutExpired:
        return (
            f"⚠️ TOOL_TIMEOUT (run_shell): command exceeded {timeout_sec}s. "
            "Subprocess tree was terminated."
        )
    except Exception as e:
        return f"⚠️ SHELL_ERROR: {e}"


# ---------------------------------------------------------------------------
# Claude Code CLI: auto-install
# ---------------------------------------------------------------------------
_NODE_DIR = pathlib.Path.home() / "Ouroboros" / "node"
_NODE_BIN = _NODE_DIR if IS_WINDOWS else _NODE_DIR / "bin"
_install_lock = threading.Lock()
_path_initialized = False


def _format_install_attempt(label: str, res: CompletedProcess, *, claude_found: bool) -> str:
    """Summarize one Claude Code install attempt."""
    suffix = "" if claude_found else " `claude` was still not found in PATH afterward."
    return (
        f"{label}: completed with {_describe_returncode(res.returncode)}.{suffix}\n\n"
        f"{_format_process_output(res.stdout or '', res.stderr or '')}"
    )


def _run_claude_install_attempt(cmd: List[str], *, timeout_sec: int, env: Dict[str, str]) -> CompletedProcess:
    """Run one Claude Code install command with shared output settings."""
    return _tracked_subprocess_run(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_sec,
    )


def _install_claude_cli_native(ctx: ToolContext, timeout_sec: int) -> List[str]:
    """Try current official install methods before falling back to npm."""
    if IS_WINDOWS:
        return []

    failures: List[str] = []
    env = {**os.environ, "PATH": _build_augmented_path()}

    if shutil.which("curl"):
        ctx.emit_progress_fn("Claude CLI not found. Trying the official installer...")
        try:
            res = _run_claude_install_attempt(
                ["sh", "-c", "curl -fsSL https://claude.ai/install.sh | bash"],
                timeout_sec=timeout_sec,
                env=env,
            )
            _ensure_path(force_refresh=True)
            if res.returncode == 0 and shutil.which("claude"):
                ctx.emit_progress_fn("Claude Code CLI installed via official installer.")
                return []
            failures.append(
                _format_install_attempt(
                    "Official install.sh",
                    res,
                    claude_found=bool(shutil.which("claude")),
                )
            )
        except subprocess.TimeoutExpired:
            failures.append(
                f"Official install.sh timed out after {timeout_sec}s and its process tree was terminated."
            )
        except Exception as e:
            failures.append(f"Official install.sh failed: {type(e).__name__}: {e}")
    else:
        failures.append("Official install.sh skipped: curl is not available.")

    if platform.system().lower() == "darwin" and shutil.which("brew"):
        ctx.emit_progress_fn("Falling back to Homebrew cask for Claude Code...")
        try:
            res = _run_claude_install_attempt(
                ["brew", "install", "--cask", "claude-code"],
                timeout_sec=timeout_sec,
                env=env,
            )
            _ensure_path(force_refresh=True)
            if res.returncode == 0 and shutil.which("claude"):
                ctx.emit_progress_fn("Claude Code CLI installed via Homebrew.")
                return []
            failures.append(
                _format_install_attempt(
                    "brew install --cask claude-code",
                    res,
                    claude_found=bool(shutil.which("claude")),
                )
            )
        except subprocess.TimeoutExpired:
            failures.append(
                f"brew install --cask claude-code timed out after {timeout_sec}s and its process tree was terminated."
            )
        except Exception as e:
            failures.append(f"brew install --cask claude-code failed: {type(e).__name__}: {e}")

    return failures


def _install_claude_cli_via_npm(timeout_sec: int) -> Optional[str]:
    """Install Claude Code with npm as a compatibility fallback."""
    npm_name = "npm.cmd" if IS_WINDOWS else "npm"
    npm = shutil.which(npm_name) or ""
    if not npm:
        node_bin = _NODE_BIN / ("node.exe" if IS_WINDOWS else "node")
        if not node_bin.exists():
            err = _install_node()
            if err:
                return f"⚠️ CLAUDE_CODE_INSTALL_ERROR: {err}"
            _ensure_path(force_refresh=True)

        npm = str(_NODE_BIN / npm_name)
        if not pathlib.Path(npm).exists():
            return "⚠️ CLAUDE_CODE_INSTALL_ERROR: npm not found after Node.js install."

    try:
        res = _tracked_subprocess_run(
            [npm, "install", "-g", "@anthropic-ai/claude-code"],
            env={**os.environ, "PATH": _build_augmented_path()},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return (
            f"⚠️ CLAUDE_CODE_INSTALL_ERROR: npm install timed out after {timeout_sec}s. "
            "Subprocess tree was terminated."
        )
    except Exception as e:
        return f"⚠️ CLAUDE_CODE_INSTALL_ERROR: npm install failed: {type(e).__name__}: {e}"

    if res.returncode != 0:
        return _format_process_failure(
            "⚠️ CLAUDE_CODE_INSTALL_ERROR",
            "npm fallback exited",
            res,
        )

    _ensure_path(force_refresh=True)
    return None


def _ensure_claude_cli(ctx: ToolContext) -> Tuple[Optional[str], bool]:
    """Ensure claude CLI is available. Auto-install if needed.

    Returns (error_string, freshly_installed).
    """
    _ensure_path()
    if shutil.which("claude"):
        return None, False

    with _install_lock:
        _ensure_path()
        if shutil.which("claude"):
            return None, False

        timeout_sec = _resolve_effective_timeout(_CLAUDE_CODE_DEFAULT_TIMEOUT_SEC)
        install_failures = _install_claude_cli_native(ctx, timeout_sec)
        _ensure_path(force_refresh=True)
        if shutil.which("claude"):
            return None, True

        ctx.emit_progress_fn("Native Claude Code install did not complete. Falling back to npm...")
        npm_error = _install_claude_cli_via_npm(timeout_sec)
        if npm_error:
            combined = install_failures + [npm_error]
            return (
                "⚠️ CLAUDE_CODE_INSTALL_ERROR: unable to install Claude Code.\n\n"
                + "\n\n".join(part for part in combined if part)
            ), False

        _ensure_path(force_refresh=True)
        if shutil.which("claude"):
            ctx.emit_progress_fn("Claude Code CLI installed successfully via npm fallback.")
            return None, True
        combined = install_failures + [
            "npm fallback completed but `claude` was still not found in PATH.",
        ]
        return (
            "⚠️ CLAUDE_CODE_INSTALL_ERROR: Claude Code CLI binary not found after installation attempts.\n\n"
            + "\n\n".join(part for part in combined if part)
        ), False


def _install_node() -> Optional[str]:
    """Download and extract Node.js LTS binary. Returns error string or None."""
    import urllib.request

    node_version = "v22.14.0"
    url, dir_name, archive_type = node_download_info(node_version)

    _NODE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = _NODE_DIR / ("node.zip" if archive_type == "zip" else "node.tar.gz")
    try:
        urllib.request.urlretrieve(url, archive_path)

        if archive_type == "zip":
            import zipfile
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(_NODE_DIR)
        else:
            import tarfile
            with tarfile.open(archive_path) as tf:
                tf.extractall(_NODE_DIR, filter="data")

        extracted = _NODE_DIR / dir_name
        if extracted.exists():
            for item in extracted.iterdir():
                dest = _NODE_DIR / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(dest))
            extracted.rmdir()
        archive_path.unlink(missing_ok=True)
        return None
    except Exception as e:
        archive_path.unlink(missing_ok=True)
        return f"Node.js download/install failed: {e}"


def _build_augmented_path() -> str:
    """Build a PATH string with node/local dirs prepended. Pure function, no side effects."""
    current = os.environ.get("PATH", "")
    parts = []
    for d in [
        str(_NODE_BIN),
        str(_NODE_DIR / "lib" / "node_modules" / ".bin"),
        str(pathlib.Path.home() / ".local" / "bin"),
    ]:
        if d not in current and (d == str(_NODE_BIN) or pathlib.Path(d).exists()):
            parts.append(d)
    if parts:
        return PATH_SEP.join(parts) + PATH_SEP + current
    return current


def _ensure_path(force_refresh: bool = False):
    """Set PATH once with node/local dirs. Idempotent — only mutates env on first call."""
    global _path_initialized
    if _path_initialized and not force_refresh:
        return
    os.environ["PATH"] = _build_augmented_path()
    _path_initialized = True


def _claude_version_timeout_sec() -> int:
    """Keep version probes short even when the global tool timeout is large."""
    return min(_resolve_effective_timeout(_CLAUDE_CODE_DEFAULT_TIMEOUT_SEC), 60)


def get_claude_code_cli_status() -> Dict[str, Any]:
    """Return the current Claude Code CLI availability and version details."""
    _ensure_path()
    claude_bin = shutil.which("claude")
    status: Dict[str, Any] = {
        "status": "missing",
        "installed": bool(claude_bin),
        "busy": False,
        "path": claude_bin or "",
        "version": "",
        "message": "Claude Code CLI is not installed.",
        "error": "",
    }
    if not claude_bin:
        return status

    version_timeout = _claude_version_timeout_sec()
    try:
        res = _tracked_subprocess_run(
            [claude_bin, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=version_timeout,
            env={**os.environ, "PATH": _build_augmented_path()},
        )
    except subprocess.TimeoutExpired:
        status.update({
            "status": "error",
            "message": f"`claude --version` timed out after {version_timeout}s.",
            "error": f"⚠️ CLAUDE_CODE_INSTALL_ERROR: `claude --version` timed out after {version_timeout}s.",
        })
        return status
    except Exception as e:
        status.update({
            "status": "error",
            "message": f"Claude Code version check failed: {type(e).__name__}: {e}",
            "error": f"⚠️ CLAUDE_CODE_INSTALL_ERROR: version check failed: {type(e).__name__}: {e}",
        })
        return status

    if res.returncode != 0:
        rendered = _format_process_failure(
            "⚠️ CLAUDE_CODE_INSTALL_ERROR",
            "version check exited",
            res,
        )
        status.update({
            "status": "error",
            "message": "Claude Code CLI is present but failed its version check.",
            "error": rendered,
        })
        return status

    version = (res.stdout or res.stderr or "").strip() or "version unknown"
    status.update({
        "status": "installed",
        "version": version,
        "message": f"Installed: {version}",
        "error": "",
    })
    return status


def ensure_claude_code_cli(progress_cb: Optional[Any] = None) -> Dict[str, Any]:
    """Install Claude Code CLI if needed and return a shared status payload."""
    progress_fn = progress_cb if callable(progress_cb) else (lambda _text: None)
    install_err, freshly_installed = _ensure_claude_cli(SimpleNamespace(emit_progress_fn=progress_fn))
    status = get_claude_code_cli_status()
    status["freshly_installed"] = bool(freshly_installed)
    if install_err:
        status.update({
            "status": "error",
            "message": "Claude Code CLI installation failed.",
            "error": install_err,
        })
        return status
    if status.get("status") == "error":
        return status
    version = status.get("version") or "version unknown"
    state = "installed" if freshly_installed else "already available"
    status["message"] = f"Claude Code CLI {state}: {version}"
    return status


# ---------------------------------------------------------------------------
# Claude Code CLI: run + parse
# ---------------------------------------------------------------------------
def _run_claude_cli(work_dir: str, prompt: str, env: dict,
                    model: str = "", budget: Optional[float] = None) -> CompletedProcess:
    """Run Claude CLI with permission-mode fallback."""
    claude_bin = shutil.which("claude")
    cmd = [
        claude_bin, "-p", prompt,
        "--output-format", "json",
        "--max-turns", "12",
        "--tools", "Read,Edit,Grep,Glob",
        "--no-session-persistence",
    ]
    if model:
        cmd += ["--model", model]
    if budget is not None:
        cmd += ["--max-budget-usd", str(budget)]

    perm_mode = os.environ.get("OUROBOROS_CLAUDE_CODE_PERMISSION_MODE", "bypassPermissions").strip()
    primary_cmd = cmd + ["--permission-mode", perm_mode]
    legacy_cmd = cmd + ["--dangerously-skip-permissions"]
    timeout_sec = _resolve_effective_timeout(_CLAUDE_CODE_DEFAULT_TIMEOUT_SEC)

    res = _tracked_subprocess_run(
        primary_cmd, cwd=work_dir,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=timeout_sec, env=env,
    )

    if res.returncode != 0:
        combined = ((res.stdout or "") + "\n" + (res.stderr or "")).lower()
        if "--permission-mode" in combined and any(
            m in combined for m in ("unknown option", "unknown argument", "unrecognized option", "unexpected argument")
        ):
            res = _tracked_subprocess_run(
                legacy_cmd, cwd=work_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=timeout_sec, env=env,
            )

    return res


def _parse_claude_payload(stdout: str) -> Optional[Dict[str, Any]]:
    """Parse Claude CLI JSON stdout if present."""
    try:
        payload = json.loads(stdout)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _should_retry_claude_first_run(stdout: str, freshly_installed: bool) -> bool:
    """Detect the transient zero-token auth-like failure seen after fresh installs."""
    if not freshly_installed:
        return False
    payload = _parse_claude_payload(stdout)
    if not payload or not payload.get("is_error"):
        return False

    result = str(payload.get("result", "")).lower()
    if "invalid api key" not in result:
        return False

    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    token_total = 0
    for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"):
        try:
            token_total += int(usage.get(key) or 0)
        except Exception:
            continue

    total_cost = float(payload.get("total_cost_usd") or 0)
    duration_api_ms = int(payload.get("duration_api_ms") or 0)
    return token_total == 0 and total_cost == 0 and duration_api_ms == 0


def _format_claude_code_error(res: CompletedProcess) -> str:
    """Render Claude CLI failures with a parsed summary when possible."""
    stdout = (res.stdout or "").strip()
    stderr = (res.stderr or "").strip()
    payload = _parse_claude_payload(stdout)
    summary = ""
    if payload:
        result = str(payload.get("result", "")).strip()
        if result:
            summary = f"\nCLI result: {result}"
    return (
        f"⚠️ CLAUDE_CODE_ERROR: {_describe_returncode(res.returncode)}"
        f"{summary}\n{_format_process_output(stdout, stderr)}"
    )


def _ensure_claude_cli_tool(ctx: ToolContext) -> str:
    """Ensure Claude Code CLI is installed and available on PATH."""
    status = ensure_claude_code_cli(progress_cb=ctx.emit_progress_fn)
    if status.get("status") == "error":
        return str(status.get("error") or "⚠️ CLAUDE_CODE_INSTALL_ERROR: installation failed.")
    if not status.get("installed"):
        return "⚠️ CLAUDE_CODE_INSTALL_ERROR: `claude` is still not available on PATH."
    version = str(status.get("version") or "version unknown")
    state = "installed" if status.get("freshly_installed") else "already available"
    return f"OK: Claude Code CLI {state}: {version}"


def _check_uncommitted_changes(repo_dir: pathlib.Path) -> str:
    """Check git status after edit, return warning string or empty string."""
    try:
        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if status_res.returncode == 0 and status_res.stdout.strip():
            diff_res = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if diff_res.returncode == 0 and diff_res.stdout.strip():
                return (
                    f"\n\n⚠️ UNCOMMITTED CHANGES detected after Claude Code edit:\n"
                    f"{diff_res.stdout.strip()}\n"
                    f"Remember to run git_status and repo_commit!"
                )
    except Exception as e:
        log.debug("Failed to check git status after claude_code_edit: %s", e, exc_info=True)
    return ""


def _parse_claude_output(stdout: str, ctx: ToolContext) -> str:
    """Parse JSON output and emit cost event, return result string."""
    try:
        payload = _parse_claude_payload(stdout)
        if payload is None:
            return stdout
        out: Dict[str, Any] = {
            "result": payload.get("result", ""),
            "session_id": payload.get("session_id"),
        }
        if isinstance(payload.get("total_cost_usd"), (int, float)):
            ctx.pending_events.append({
                "type": "llm_usage",
                "provider": "claude_code_cli",
                "model": os.environ.get("CLAUDE_CODE_MODEL", "opus"),
                "api_key_type": "anthropic",
                "model_category": "claude_code",
                "usage": {"cost": float(payload["total_cost_usd"])},
                "cost": float(payload["total_cost_usd"]),
                "source": "claude_code_edit",
                "ts": utc_now_iso(),
                "category": "task",
            })
        return json.dumps(out, ensure_ascii=False, indent=2)
    except Exception:
        log.debug("Failed to parse claude_code_edit JSON output", exc_info=True)
        return stdout


def _claude_code_edit(ctx: ToolContext, prompt: str, cwd: str = "",
                      budget: float = 1.0) -> str:
    """Delegate code edits to Claude Code CLI."""
    from ouroboros.tools.git import _acquire_git_lock, _release_git_lock

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "⚠️ CLAUDE_CODE_UNAVAILABLE: ANTHROPIC_API_KEY not set."

    work_dir = str(ctx.repo_dir)
    if cwd and cwd.strip() not in ("", ".", "./"):
        candidate = (ctx.repo_dir / cwd).resolve()
        if candidate.exists():
            work_dir = str(candidate)

    install_err, freshly_installed = _ensure_claude_cli(ctx)
    if install_err:
        return install_err

    ctx.emit_progress_fn("Delegating to Claude Code CLI...")

    model = os.environ.get("CLAUDE_CODE_MODEL", "opus").strip()

    lock = _acquire_git_lock(ctx)
    try:
        try:
            run_cmd(["git", "checkout", ctx.branch_dev], cwd=ctx.repo_dir)
        except Exception as e:
            return f"⚠️ GIT_ERROR (checkout): {e}"

        full_prompt = (
            f"STRICT: Only modify files inside {work_dir}. "
            f"Git branch: {ctx.branch_dev}. Do NOT commit or push.\n\n"
            f"{prompt}"
        )

        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = api_key
        try:
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                env.setdefault("IS_SANDBOX", "1")
        except Exception:
            log.debug("Failed to check geteuid for sandbox detection", exc_info=True)
            pass

        _ensure_path()
        env["PATH"] = os.environ["PATH"]

        res = _run_claude_cli(work_dir, full_prompt, env,
                              model=model, budget=budget)

        if res.returncode != 0 and _should_retry_claude_first_run(res.stdout or "", freshly_installed):
            ctx.emit_progress_fn("Claude CLI returned a transient first-run auth error. Retrying once...")
            time.sleep(2)
            res = _run_claude_cli(work_dir, full_prompt, env,
                                  model=model, budget=budget)

        stdout = (res.stdout or "").strip()
        if res.returncode != 0:
            return _format_claude_code_error(res)
        if not stdout:
            stdout = "OK: Claude Code completed with empty output."

        warning = _check_uncommitted_changes(ctx.repo_dir)
        if warning:
            stdout += warning

    except subprocess.TimeoutExpired:
        timeout_sec = _resolve_effective_timeout(_CLAUDE_CODE_DEFAULT_TIMEOUT_SEC)
        return f"⚠️ CLAUDE_CODE_TIMEOUT: exceeded {timeout_sec}s."
    except Exception as e:
        return f"⚠️ CLAUDE_CODE_FAILED: {type(e).__name__}: {e}"
    finally:
        _release_git_lock(lock)

    return _parse_claude_output(stdout, ctx)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("run_shell", {
            "name": "run_shell",
            "description": "Run a shell command (list of args) inside the repo. Returns stdout+stderr.",
            "parameters": {"type": "object", "properties": {
                "cmd": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string", "default": ""},
            }, "required": ["cmd"]},
        }, _run_shell, is_code_tool=True, timeout_sec=_RUN_SHELL_DEFAULT_TIMEOUT_SEC),
        ToolEntry("ensure_claude_cli", {
            "name": "ensure_claude_cli",
            "description": "Ensure Claude Code CLI is installed and available. Uses official native install methods first, then npm fallback.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }, _ensure_claude_cli_tool, timeout_sec=_CLAUDE_CODE_DEFAULT_TIMEOUT_SEC),
        ToolEntry("claude_code_edit", {
            "name": "claude_code_edit",
            "description": "Delegate code edits to Claude Code CLI. Preferred for multi-file changes and refactors. Follow with repo_commit.",
            "parameters": {"type": "object", "properties": {
                "prompt": {"type": "string"},
                "cwd": {"type": "string", "default": ""},
                "budget": {"type": "number",
                           "description": "Max USD for this Claude Code call. Default: 1.0"},
            }, "required": ["prompt"]},
        }, _claude_code_edit, is_code_tool=True, timeout_sec=_CLAUDE_CODE_DEFAULT_TIMEOUT_SEC),
    ]
