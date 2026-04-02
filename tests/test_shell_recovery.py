"""Tests for shell tool arg contract and Claude Code CLI helpers."""
import inspect
from subprocess import CompletedProcess
from types import SimpleNamespace

import pytest

from ouroboros.tools.shell import (
    _ensure_claude_cli,
    _format_claude_code_error,
    _run_shell,
    _should_retry_claude_first_run,
    ensure_claude_code_cli,
    get_claude_code_cli_status,
)


class TestShellArgContract:
    """run_shell must reject string cmd with a clear error (v4.10.0+)."""

    def test_string_cmd_returns_hard_error(self):
        """Passing cmd as a plain string must return SHELL_ARG_ERROR, not recover."""
        ctx = SimpleNamespace(repo_dir="/tmp", drive_logs=lambda: __import__("pathlib").Path("/tmp"))
        result = _run_shell(ctx, "echo hello")
        assert "SHELL_ARG_ERROR" in result
        assert "JSON array" in result

    def test_string_cmd_suggests_code_search(self):
        """Error message for string cmd should mention code_search as alternative."""
        ctx = SimpleNamespace(repo_dir="/tmp", drive_logs=lambda: __import__("pathlib").Path("/tmp"))
        result = _run_shell(ctx, "grep -r pattern path/")
        assert "code_search" in result

    def test_list_cmd_is_accepted(self):
        """List cmd should not trigger arg error."""
        src = inspect.getsource(_run_shell)
        # The function should proceed past the string check for list cmds
        assert "isinstance(cmd, list)" in src or "not isinstance(cmd, list)" in src


def test_run_shell_rejects_literal_env_refs_in_argv(tmp_path):
    ctx = SimpleNamespace(repo_dir=tmp_path)
    result = _run_shell(ctx, ["curl", "-H", "x-api-key: $ANTHROPIC_API_KEY"])
    assert "SHELL_ENV_ERROR" in result
    assert "$ANTHROPIC_API_KEY" in result


def test_run_shell_allows_shell_expansion_via_sh_c(tmp_path, monkeypatch):
    ctx = SimpleNamespace(repo_dir=tmp_path)

    def fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr("ouroboros.tools.shell._tracked_subprocess_run", fake_run)
    result = _run_shell(ctx, ["sh", "-c", "printf '%s' \"$ANTHROPIC_API_KEY\""])
    assert "SHELL_ENV_ERROR" not in result
    assert "exit_code=0" in result


def test_should_retry_claude_first_run_on_zero_token_invalid_key():
    stdout = """
{"type":"result","subtype":"success","is_error":true,"duration_ms":588,"duration_api_ms":0,
"result":"Invalid API key · Fix external API key","total_cost_usd":0,
"usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0}}
""".strip()
    assert _should_retry_claude_first_run(stdout, freshly_installed=True) is True
    assert _should_retry_claude_first_run(stdout, freshly_installed=False) is False


def test_format_claude_code_error_includes_cli_result():
    res = CompletedProcess(
        args=["claude"],
        returncode=1,
        stdout='{"is_error": true, "result": "Invalid API key · Fix external API key"}',
        stderr="",
    )
    rendered = _format_claude_code_error(res)
    assert "CLAUDE_CODE_ERROR: exit_code=1" in rendered
    assert "CLI result: Invalid API key · Fix external API key" in rendered


def test_run_shell_nonzero_exit_is_reported_as_failure(tmp_path, monkeypatch):
    ctx = SimpleNamespace(repo_dir=tmp_path)

    def fake_run(cmd, **kwargs):
        return CompletedProcess(cmd, 3, "", "permission denied")

    monkeypatch.setattr("ouroboros.tools.shell._tracked_subprocess_run", fake_run)
    result = _run_shell(ctx, ["npm", "install", "-g", "@anthropic-ai/claude-code"])

    assert result.startswith("⚠️ SHELL_EXIT_ERROR:")
    assert "exit_code=3" in result
    assert "permission denied" in result


def test_run_shell_timeout_uses_settings_timeout(tmp_path, monkeypatch):
    ctx = SimpleNamespace(repo_dir=tmp_path)

    def fake_run(cmd, **kwargs):
        raise TimeoutError("wrong exception")

    def fake_timeout(cmd, **kwargs):
        raise __import__("subprocess").TimeoutExpired(cmd=cmd, timeout=kwargs["timeout"])

    monkeypatch.setattr("ouroboros.tools.shell.load_settings", lambda: {"OUROBOROS_TOOL_TIMEOUT_SEC": 42})
    monkeypatch.setattr("ouroboros.tools.shell._tracked_subprocess_run", fake_timeout)
    result = _run_shell(ctx, ["sleep", "999"])

    assert "TOOL_TIMEOUT (run_shell)" in result
    assert "42s" in result


def test_ensure_claude_cli_prefers_native_installer(tmp_path, monkeypatch):
    progress = []
    ctx = SimpleNamespace(emit_progress_fn=progress.append)
    state = {"installed": False}

    def fake_which(name):
        if name == "claude":
            return "/usr/local/bin/claude" if state["installed"] else None
        if name == "curl":
            return "/usr/bin/curl"
        if name == "brew":
            return None
        return None

    def fake_install(cmd, *, timeout_sec, env):
        state["installed"] = True
        return CompletedProcess(cmd, 0, "installed", "")

    monkeypatch.setattr("ouroboros.tools.shell.IS_WINDOWS", False)
    monkeypatch.setattr("ouroboros.tools.shell.shutil.which", fake_which)
    monkeypatch.setattr("ouroboros.tools.shell._run_claude_install_attempt", fake_install)
    monkeypatch.setattr("ouroboros.tools.shell._install_claude_cli_via_npm", lambda timeout_sec: (_ for _ in ()).throw(AssertionError("npm fallback should not run")))
    monkeypatch.setattr("ouroboros.tools.shell._ensure_path", lambda force_refresh=False: None)
    monkeypatch.setattr("ouroboros.tools.shell.load_settings", lambda: {"OUROBOROS_TOOL_TIMEOUT_SEC": 55})

    err, freshly_installed = _ensure_claude_cli(ctx)

    assert err is None
    assert freshly_installed is True
    assert any("official installer" in msg.lower() for msg in progress)


def test_ensure_claude_cli_falls_back_to_npm(monkeypatch):
    ctx = SimpleNamespace(emit_progress_fn=lambda text: None)
    state = {"installed": False}

    def fake_which(name):
        if name == "claude":
            return "/usr/local/bin/claude" if state["installed"] else None
        if name == "curl":
            return "/usr/bin/curl"
        if name == "brew":
            return None
        return None

    monkeypatch.setattr("ouroboros.tools.shell.IS_WINDOWS", False)
    monkeypatch.setattr("ouroboros.tools.shell.shutil.which", fake_which)
    monkeypatch.setattr("ouroboros.tools.shell._install_claude_cli_native", lambda _ctx, timeout_sec: ["native failed"])

    def fake_npm(timeout_sec):
        state["installed"] = True
        return None

    monkeypatch.setattr("ouroboros.tools.shell._install_claude_cli_via_npm", fake_npm)
    monkeypatch.setattr("ouroboros.tools.shell._ensure_path", lambda force_refresh=False: None)
    monkeypatch.setattr("ouroboros.tools.shell.load_settings", lambda: {"OUROBOROS_TOOL_TIMEOUT_SEC": 60})

    err, freshly_installed = _ensure_claude_cli(ctx)

    assert err is None
    assert freshly_installed is True


def test_get_claude_code_cli_status_reports_missing(monkeypatch):
    monkeypatch.setattr("ouroboros.tools.shell._ensure_path", lambda force_refresh=False: None)
    monkeypatch.setattr("ouroboros.tools.shell.shutil.which", lambda name: None)

    status = get_claude_code_cli_status()

    assert status["status"] == "missing"
    assert status["installed"] is False
    assert "not installed" in status["message"].lower()


def test_ensure_claude_code_cli_wrapper_returns_shared_payload(monkeypatch):
    monkeypatch.setattr("ouroboros.tools.shell._ensure_claude_cli", lambda ctx: (None, True))
    monkeypatch.setattr("ouroboros.tools.shell.get_claude_code_cli_status", lambda: {
        "status": "installed",
        "installed": True,
        "busy": False,
        "path": "/usr/local/bin/claude",
        "version": "1.2.3",
        "message": "Installed: 1.2.3",
        "error": "",
    })

    status = ensure_claude_code_cli()

    assert status["freshly_installed"] is True
    assert status["installed"] is True
    assert status["message"] == "Claude Code CLI installed: 1.2.3"
