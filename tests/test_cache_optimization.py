"""Tests for multipart prompt caching layout."""

import pathlib
import tempfile


def _make_env_and_memory(tmpdir: pathlib.Path):
    from ouroboros.agent import Env
    from ouroboros.memory import Memory

    repo_dir = tmpdir / "repo"
    drive_root = tmpdir / "drive"
    repo_dir.mkdir(parents=True, exist_ok=True)
    drive_root.mkdir(parents=True, exist_ok=True)
    for subdir in ["drive/state", "drive/memory", "drive/memory/knowledge", "drive/logs", "repo/docs", "repo/prompts"]:
        (tmpdir / subdir).mkdir(parents=True, exist_ok=True)
    (repo_dir / "prompts" / "SYSTEM.md").write_text("You are Ouroboros.")
    (repo_dir / "BIBLE.md").write_text("# Principle 0: Agency")
    (repo_dir / "docs" / "ARCHITECTURE.md").write_text("# Ouroboros v1.2.3 — Architecture")
    (repo_dir / "docs" / "DEVELOPMENT.md").write_text("# DEVELOPMENT.md")
    (repo_dir / "README.md").write_text("version-1.2.3")
    (repo_dir / "docs" / "CHECKLISTS.md").write_text("## Repo Commit Checklist")
    (drive_root / "state" / "state.json").write_text('{"spent_usd": 0}')
    (drive_root / "memory" / "scratchpad.md").write_text("scratch")
    (drive_root / "memory" / "identity.md").write_text("identity")
    env = Env(repo_dir=repo_dir, drive_root=drive_root)
    memory = Memory(drive_root=drive_root, repo_dir=repo_dir)
    return env, memory


def test_build_llm_messages_returns_three_system_blocks():
    from ouroboros.context import build_llm_messages
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    env, memory = _make_env_and_memory(tmpdir)
    messages, _ = build_llm_messages(env=env, memory=memory, task={"id": "t1", "type": "task", "text": "hi"})
    system_msg = messages[0]
    assert system_msg["role"] == "system"
    assert isinstance(system_msg["content"], list)
    assert len(system_msg["content"]) == 3
    assert "cache_control" in system_msg["content"][0]
    assert "cache_control" in system_msg["content"][1]
    assert "cache_control" not in system_msg["content"][2]
