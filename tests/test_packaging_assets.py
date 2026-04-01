"""Regression checks for packaging asset completeness."""

import os
import pathlib

REPO = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_spec_bundles_assets_and_icon():
    source = _read("Ouroboros.spec")
    assert "('assets', 'assets')" in source
    assert "icon='assets/icon.icns'" in source


def test_launcher_does_not_exclude_assets_on_bootstrap():
    launcher_source = _read("launcher.py")
    bootstrap_source = _read("ouroboros/launcher_bootstrap.py")
    assert '"python-standalone", "assets"' not in launcher_source
    assert "from ouroboros.launcher_bootstrap import" in launcher_source
    assert "MANAGED_BUNDLE_PATHS = (" in bootstrap_source
    assert '"server.py"' in bootstrap_source
    assert '"web"' in bootstrap_source
    assert '"webview"' in bootstrap_source
    assert '"assets"' in bootstrap_source
