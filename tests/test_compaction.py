"""Tests for tool-history compaction protection (context_compaction.py)."""
from ouroboros.context_compaction import compact_tool_history, _COMPACTION_PROTECTED_TOOLS


def _make_messages(tool_name: str, result_content: str, num_rounds: int = 8):
    """Build a message list with num_rounds of tool calls, all using the same tool."""
    messages = [{"role": "system", "content": [{"type": "text", "text": "system"}]}]
    for i in range(num_rounds):
        tc_id = f"call_{i}"
        messages.append({
            "role": "assistant",
            "content": f"Round {i}",
            "tool_calls": [{
                "id": tc_id,
                "function": {"name": tool_name, "arguments": "{}"},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": result_content,
        })
    return messages


def _make_large_arg_messages(tool_name: str, num_rounds: int = 8):
    """Build messages whose old assistant tool-call payloads should compact."""
    messages = [{"role": "system", "content": [{"type": "text", "text": "system"}]}]
    large_args = '{"content": "' + ("x" * 1000) + '"}'
    for i in range(num_rounds):
        tc_id = f"call_{i}"
        messages.append({
            "role": "assistant",
            "content": f"Round {i}",
            "tool_calls": [{
                "id": tc_id,
                "function": {"name": tool_name, "arguments": large_args},
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": "ok",
        })
    return messages


def test_protected_tool_results_survive_compaction():
    """repo_commit results must not be truncated even in old rounds."""
    original_result = "OK: committed to ouroboros: v3.19.0 review feedback applied"
    msgs = _make_messages("repo_commit", original_result, num_rounds=10)
    compacted = compact_tool_history(msgs, keep_recent=3)

    commit_results = [
        m["content"] for m in compacted
        if m.get("role") == "tool" and m["content"] == original_result
    ]
    assert len(commit_results) == 10, "All repo_commit results must survive compaction"


def test_warning_results_survive_compaction():
    """Results starting with warning emoji must not be truncated."""
    warn_result = "\u26a0\ufe0f REVIEW_BLOCKED: tests failed, commit rejected. Fix errors first."
    msgs = _make_messages("run_shell", warn_result, num_rounds=10)
    compacted = compact_tool_history(msgs, keep_recent=3)

    warning_results = [
        m["content"] for m in compacted
        if m.get("role") == "tool" and m["content"] == warn_result
    ]
    assert len(warning_results) == 10, "Warning-prefixed results must survive compaction"


def test_old_assistant_tool_payloads_are_compacted():
    """Fallback compaction should compact oversized old assistant tool-call payloads."""
    msgs = _make_large_arg_messages("repo_write", num_rounds=10)
    compacted = compact_tool_history(msgs, keep_recent=3)

    compacted_assistants = [
        m for m in compacted
        if m.get("role") == "assistant"
        and m.get("tool_calls")
        and "<<CONTENT_OMITTED len=" in m["tool_calls"][0]["function"]["arguments"]
    ]
    assert len(compacted_assistants) >= 4, "Old oversized assistant tool-call payloads should be compacted"
