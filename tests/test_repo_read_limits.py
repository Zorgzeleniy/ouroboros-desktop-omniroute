"""Tests for repo_read slicing and per-tool truncation limits."""

from unittest.mock import MagicMock


def _make_ctx(tmp_path):
    from ouroboros.tools.registry import ToolContext
    ctx = MagicMock(spec=ToolContext)
    ctx.repo_dir = tmp_path
    def _repo_path(p):
        import ouroboros.utils as u
        return tmp_path / u.safe_relpath(p)
    ctx.repo_path.side_effect = _repo_path
    return ctx


def test_repo_read_full_file_has_header(tmp_path):
    from ouroboros.tools.core import _repo_read
    f = tmp_path / "hello.py"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    ctx = _make_ctx(tmp_path)
    result = _repo_read(ctx, "hello.py")
    assert result.startswith("# hello.py — lines 1–3 of 3\n")


def test_repo_read_max_lines_slice(tmp_path):
    from ouroboros.tools.core import _repo_read
    f = tmp_path / "big.py"
    f.write_text("\n".join(f"line{i}" for i in range(1, 101)) + "\n", encoding="utf-8")
    ctx = _make_ctx(tmp_path)
    result = _repo_read(ctx, "big.py", max_lines=10)
    assert result.startswith("# big.py — lines 1–10 of 100\n")
    assert "line11" not in result


def test_data_read_memory_file_never_truncated():
    from ouroboros.loop_tool_execution import _truncate_tool_result
    big = "m" * 70000
    result = _truncate_tool_result(big, "data_read", {"path": "memory/scratchpad.md"})
    assert result == big


def test_repo_read_prompt_file_never_truncated():
    from ouroboros.loop_tool_execution import _truncate_tool_result
    big = "p" * 90000
    result = _truncate_tool_result(big, "repo_read", {"path": "prompts/SYSTEM.md"})
    assert result == big


def test_repo_commit_results_never_truncated():
    from ouroboros.loop_tool_execution import _truncate_tool_result
    big = "r" * 90000
    assert _truncate_tool_result(big, "repo_commit") == big
    assert _truncate_tool_result(big, "repo_write_commit") == big
    assert _truncate_tool_result(big, "multi_model_review") == big


def test_self_check_returns_bool_and_interval_15():
    from ouroboros.loop import _maybe_inject_self_check
    messages = []
    usage = {"cost": 0}
    progress_calls = []
    assert _maybe_inject_self_check(14, 200, messages, usage, progress_calls.append) is False
    assert _maybe_inject_self_check(15, 200, messages, usage, progress_calls.append) is True
    assert "CHECKPOINT" in messages[0]["content"]


def test_advisory_pre_review_results_never_truncated():
    """advisory_pre_review results must not be truncated (full JSON needed)."""
    from ouroboros.loop_tool_execution import _truncate_tool_result
    big = "a" * 90000
    assert _truncate_tool_result(big, "advisory_pre_review") == big


def test_review_status_results_never_truncated():
    """review_status results must not be truncated (full JSON needed)."""
    from ouroboros.loop_tool_execution import _truncate_tool_result
    big = "b" * 90000
    assert _truncate_tool_result(big, "review_status") == big
