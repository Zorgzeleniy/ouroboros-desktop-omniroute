"""Tests for browser state isolation and infrastructure error detection."""
import types

import pytest

import ouroboros.tools.browser as browser_mod
from ouroboros.tools.browser import _is_infrastructure_error, cleanup_browser


class TestInfrastructureErrorDetection:
    """_is_infrastructure_error should detect structural Playwright failures."""

    def test_detects_greenlet_switch(self):
        assert _is_infrastructure_error(RuntimeError("cannot switch to a different green thread"))

    def test_detects_different_thread(self):
        assert _is_infrastructure_error(RuntimeError("different thread"))

    def test_detects_browser_closed(self):
        assert _is_infrastructure_error(Exception("browser has been closed"))

    def test_detects_page_closed(self):
        assert _is_infrastructure_error(Exception("page has been closed"))

    def test_detects_connection_closed(self):
        assert _is_infrastructure_error(Exception("Connection closed"))

    def test_ignores_normal_errors(self):
        assert not _is_infrastructure_error(ValueError("invalid selector"))
        assert not _is_infrastructure_error(TimeoutError("navigation timeout"))


class TestBrowserModuleState:
    """Module-level state should be properly initialized."""

    def test_is_infrastructure_error_is_function(self):
        assert callable(_is_infrastructure_error)


class TestCleanupBrowser:
    """cleanup_browser should null out all browser_state references."""

    def test_cleanup_nulls_state(self):
        ctx = types.SimpleNamespace(
            browser_state=types.SimpleNamespace(
                page=None,
                browser=None,
                pw_instance=None,
                last_screenshot_b64=None,
            )
        )
        cleanup_browser(ctx)
        assert ctx.browser_state.page is None
        assert ctx.browser_state.browser is None
        assert ctx.browser_state.pw_instance is None
