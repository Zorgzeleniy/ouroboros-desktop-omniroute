import pathlib
import types

import ouroboros.agent_startup_checks as startup_mod
import ouroboros.world_profiler as world_profiler
from ouroboros.memory import Memory


def test_check_version_sync_ignores_non_release_tag(tmp_path, monkeypatch):
    (tmp_path / "VERSION").write_text("4.7.0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('version = "4.7.0"\n', encoding="utf-8")
    (tmp_path / "README.md").write_text("**Version:** 4.7.0\n", encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "ARCHITECTURE.md").write_text("# Ouroboros v4.7.0\n", encoding="utf-8")

    env = types.SimpleNamespace(
        repo_dir=tmp_path,
        repo_path=lambda rel: tmp_path / rel,
    )

    monkeypatch.setattr(
        startup_mod.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout="v4.6.0-test1\n"),
    )

    result, issues = startup_mod.check_version_sync(env)

    assert issues == 0
    assert result["status"] == "ok"
    assert result["latest_tag"] == "4.6.0-test1"
    assert result["tag_sync"] == "ignored_non_release_tag"


def test_memory_ensure_files_generates_world_profile(tmp_path, monkeypatch):
    calls = []

    def fake_generate(output_path: str):
        calls.append(output_path)
        pathlib.Path(output_path).write_text("# WORLD\n", encoding="utf-8")

    monkeypatch.setattr(world_profiler, "generate_world_profile", fake_generate)

    memory = Memory(drive_root=tmp_path, repo_dir=tmp_path)
    memory.ensure_files()
    memory.ensure_files()

    assert calls == [str(memory.world_path())]
    assert memory.world_path().read_text(encoding="utf-8") == "# WORLD\n"


def test_check_uncommitted_changes_skips_auto_rescue_outside_launcher(monkeypatch, tmp_path):
    env = types.SimpleNamespace(
        repo_dir=tmp_path,
        repo_path=lambda rel: tmp_path / rel,
        launcher_managed=False,
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return types.SimpleNamespace(returncode=0, stdout=" M server.py\n")
        raise AssertionError(cmd)

    monkeypatch.delenv("OUROBOROS_MANAGED_BY_LAUNCHER", raising=False)
    monkeypatch.setattr(startup_mod.subprocess, "run", fake_run)

    result, issues = startup_mod.check_uncommitted_changes(env)

    assert issues == 1
    assert result["status"] == "warning"
    assert result["auto_committed"] is False
    assert result["auto_rescue_skipped"] == "not_launcher_managed"
    assert calls == [["git", "status", "--porcelain"]]


def test_check_uncommitted_changes_auto_rescue_when_launcher_managed(monkeypatch, tmp_path):
    env = types.SimpleNamespace(
        repo_dir=tmp_path,
        repo_path=lambda rel: tmp_path / rel,
        branch_dev="ouroboros",
        launcher_managed=True,
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return types.SimpleNamespace(returncode=0, stdout=" M server.py\n")
        if cmd[:2] == ["git", "add"]:
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["git", "commit"]:
            return types.SimpleNamespace(returncode=0, stdout="[ouroboros abc123] auto-rescue\n", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(startup_mod.subprocess, "run", fake_run)

    result, issues = startup_mod.check_uncommitted_changes(env)

    assert issues == 1
    assert result["status"] == "warning"
    assert result["auto_committed"] is True
    assert [cmd[:2] for cmd in calls] == [["git", "status"], ["git", "add"], ["git", "commit"]]
