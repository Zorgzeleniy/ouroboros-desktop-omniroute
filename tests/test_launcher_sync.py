import importlib
import types

import ouroboros.launcher_bootstrap as bootstrap_module


def _reload_bootstrap():
    return importlib.reload(bootstrap_module)


def _make_context(bundle_dir, repo_dir):
    return bootstrap_module.BootstrapContext(
        bundle_dir=bundle_dir,
        repo_dir=repo_dir,
        data_dir=repo_dir.parent / "data",
        settings_path=repo_dir.parent / "settings.json",
        embedded_python="python3",
        app_version="4.7.0",
        hidden_run=lambda *args, **kwargs: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        save_settings=lambda settings: None,
        log=types.SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None, error=lambda *args, **kwargs: None),
    )


def test_sync_bundle_managed_paths_copies_only_whitelisted_entries(monkeypatch, tmp_path):
    bootstrap = _reload_bootstrap()
    bundle_dir = tmp_path / "bundle"
    repo_dir = tmp_path / "repo"
    bundle_dir.mkdir()
    repo_dir.mkdir()

    (bundle_dir / "server.py").write_text("new-server\n", encoding="utf-8")
    (bundle_dir / "web").mkdir()
    (bundle_dir / "web" / "index.html").write_text("web\n", encoding="utf-8")
    (bundle_dir / "Foundation").mkdir()
    (bundle_dir / "Foundation" / "ignored.txt").write_text("native\n", encoding="utf-8")
    (repo_dir / "server.py").write_text("old-server\n", encoding="utf-8")

    ctx = _make_context(bundle_dir, repo_dir)

    bootstrap.sync_bundle_managed_paths(ctx, overwrite_existing=False)

    assert (repo_dir / "server.py").read_text(encoding="utf-8") == "old-server\n"
    assert (repo_dir / "web" / "index.html").read_text(encoding="utf-8") == "web\n"
    assert not (repo_dir / "Foundation").exists()


def test_sync_bundle_managed_paths_overwrites_existing_managed_files(monkeypatch, tmp_path):
    bootstrap = _reload_bootstrap()
    bundle_dir = tmp_path / "bundle"
    repo_dir = tmp_path / "repo"
    bundle_dir.mkdir()
    repo_dir.mkdir()

    (bundle_dir / "server.py").write_text("new-server\n", encoding="utf-8")
    (repo_dir / "server.py").write_text("old-server\n", encoding="utf-8")

    ctx = _make_context(bundle_dir, repo_dir)

    bootstrap.sync_bundle_managed_paths(ctx, overwrite_existing=True)

    assert (repo_dir / "server.py").read_text(encoding="utf-8") == "new-server\n"


def test_sync_existing_repo_runs_full_sync_only_for_clean_version_mismatch(monkeypatch, tmp_path):
    bootstrap = _reload_bootstrap()
    bundle_dir = tmp_path / "bundle"
    repo_dir = tmp_path / "repo"
    bundle_dir.mkdir()
    repo_dir.mkdir()

    calls = []
    ctx = _make_context(bundle_dir, repo_dir)
    monkeypatch.setattr(bootstrap, "sync_core_files", lambda context: calls.append("core"))
    monkeypatch.setattr(bootstrap, "sync_bundle_managed_paths", lambda context, overwrite_existing: calls.append(("managed", overwrite_existing)))
    monkeypatch.setattr(
        bootstrap,
        "read_version_file",
        lambda root: "4.7.0" if root == bundle_dir else ("4.5.0" if root == repo_dir else ""),
    )
    monkeypatch.setattr(bootstrap, "repo_has_pending_changes", lambda context: calls.append("dirty") or False)
    monkeypatch.setattr(bootstrap, "create_bundle_backup_branch", lambda context, version: calls.append(("backup", version)) or "bundle-backup/test")
    monkeypatch.setattr(bootstrap, "commit_bundle_sync", lambda context, old, new: calls.append(("commit", old, new)))
    monkeypatch.setattr(bootstrap, "commit_synced_files", lambda context: calls.append("commit-safety"))

    bootstrap.sync_existing_repo_from_bundle(ctx)

    assert calls == [
        "dirty",
        ("backup", "4.5.0"),
        "core",
        ("managed", False),
        ("managed", True),
        ("commit", "4.5.0", "4.7.0"),
    ]


def test_sync_existing_repo_avoids_full_overwrite_when_repo_is_dirty(monkeypatch, tmp_path):
    bootstrap = _reload_bootstrap()
    bundle_dir = tmp_path / "bundle"
    repo_dir = tmp_path / "repo"
    bundle_dir.mkdir()
    repo_dir.mkdir()

    calls = []
    ctx = _make_context(bundle_dir, repo_dir)
    monkeypatch.setattr(bootstrap, "sync_core_files", lambda context: calls.append("core"))
    monkeypatch.setattr(bootstrap, "sync_bundle_managed_paths", lambda context, overwrite_existing: calls.append(("managed", overwrite_existing)))
    monkeypatch.setattr(
        bootstrap,
        "read_version_file",
        lambda root: "4.7.0" if root == bundle_dir else ("4.5.0" if root == repo_dir else ""),
    )
    monkeypatch.setattr(bootstrap, "repo_has_pending_changes", lambda context: calls.append("dirty") or True)
    monkeypatch.setattr(bootstrap, "create_bundle_backup_branch", lambda context, version: calls.append(("backup", version)))
    monkeypatch.setattr(bootstrap, "commit_bundle_sync", lambda context, old, new: calls.append(("commit", old, new)))
    monkeypatch.setattr(bootstrap, "commit_synced_files", lambda context: calls.append("commit-safety"))

    bootstrap.sync_existing_repo_from_bundle(ctx)

    assert calls == [
        "dirty",
        "core",
        ("managed", False),
        "commit-safety",
    ]


def test_sync_existing_repo_avoids_full_overwrite_when_backup_creation_fails(monkeypatch, tmp_path):
    bootstrap = _reload_bootstrap()
    bundle_dir = tmp_path / "bundle"
    repo_dir = tmp_path / "repo"
    bundle_dir.mkdir()
    repo_dir.mkdir()

    calls = []
    ctx = _make_context(bundle_dir, repo_dir)
    monkeypatch.setattr(bootstrap, "sync_core_files", lambda context: calls.append("core"))
    monkeypatch.setattr(bootstrap, "sync_bundle_managed_paths", lambda context, overwrite_existing: calls.append(("managed", overwrite_existing)))
    monkeypatch.setattr(
        bootstrap,
        "read_version_file",
        lambda root: "4.7.0" if root == bundle_dir else ("4.5.0" if root == repo_dir else ""),
    )
    monkeypatch.setattr(bootstrap, "repo_has_pending_changes", lambda context: calls.append("dirty") or False)
    monkeypatch.setattr(bootstrap, "create_bundle_backup_branch", lambda context, version: calls.append(("backup", version)) or "")
    monkeypatch.setattr(bootstrap, "commit_bundle_sync", lambda context, old, new: calls.append(("commit", old, new)))
    monkeypatch.setattr(bootstrap, "commit_synced_files", lambda context: calls.append("commit-safety"))

    bootstrap.sync_existing_repo_from_bundle(ctx)

    assert calls == [
        "dirty",
        ("backup", "4.5.0"),
        "core",
        ("managed", False),
        "commit-safety",
    ]
