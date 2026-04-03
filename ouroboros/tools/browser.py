"""
Browser automation tools via Playwright (sync API).

Provides browse_page (open URL, get content/screenshot)
and browser_action (click, fill, evaluate JS on current page).

Each BrowserState (in ToolContext) fully owns its Playwright lifecycle:
no module-level singletons, no cross-context sharing. Thread affinity
is tracked per-BrowserState via _thread_id.
"""

from __future__ import annotations

import base64
import logging
import subprocess
import sys
import threading
from typing import Any, Dict, List

try:
    from playwright_stealth import Stealth
    _HAS_STEALTH = True
except ImportError:
    _HAS_STEALTH = False

from ouroboros.tools.registry import ToolContext, ToolEntry

log = logging.getLogger(__name__)

_playwright_ready = False


def _ensure_playwright_installed():
    """Install Playwright and Chromium if not already available."""
    global _playwright_ready
    if _playwright_ready:
        return

    try:
        import playwright  # noqa: F401
    except ImportError:
        if getattr(sys, 'frozen', False):
            raise RuntimeError(
                "Browser tools require Playwright, which is not bundled. "
                "Install manually: pip3 install playwright && python3 -m playwright install chromium"
            )
        log.info("Playwright not found, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.executable_path
        log.info("Playwright chromium binary found")
    except Exception:
        if getattr(sys, 'frozen', False):
            raise RuntimeError(
                "Playwright chromium binary not found. "
                "Install manually: python3 -m playwright install chromium"
            )
        log.info("Installing Playwright chromium binary...")
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install-deps", "chromium"])

    _playwright_ready = True


def _ensure_browser(ctx: ToolContext):
    """Create or reuse browser for this context. All Playwright state lives
    in ctx.browser_state — no module-level globals."""
    bs = ctx.browser_state
    current_thread_id = threading.get_ident()

    if bs._thread_id is not None and bs._thread_id != current_thread_id:
        log.info("Thread switch detected (old=%s, new=%s). Tearing down browser for this context.",
                 bs._thread_id, current_thread_id)
        cleanup_browser(ctx)

    if bs.browser is not None:
        try:
            if bs.browser.is_connected():
                return bs.page
        except Exception:
            log.debug("Browser connection check failed", exc_info=True)
        cleanup_browser(ctx)

    _ensure_playwright_installed()

    if bs.pw_instance is None:
        from playwright.sync_api import sync_playwright
        bs.pw_instance = sync_playwright().start()
        bs._thread_id = current_thread_id
        log.info("Created Playwright instance in thread %s", current_thread_id)

    bs.browser = bs.pw_instance.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=site-per-process",
            "--window-size=1920,1080",
        ],
    )
    bs.page = bs.browser.new_page(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    )

    if _HAS_STEALTH:
        stealth = Stealth()
        stealth.apply_stealth_sync(bs.page)

    bs.page.set_default_timeout(30000)
    return bs.page


def cleanup_browser(ctx: ToolContext) -> None:
    """Full teardown: close page, browser, AND stop the Playwright instance.
    Called by agent.py in finally block and by recovery logic on errors."""
    bs = ctx.browser_state
    try:
        if bs.page is not None:
            bs.page.close()
    except Exception:
        log.debug("Failed to close browser page during cleanup", exc_info=True)
    try:
        if bs.browser is not None:
            bs.browser.close()
    except Exception:
        log.debug("Failed to close browser during cleanup", exc_info=True)
    try:
        if bs.pw_instance is not None:
            bs.pw_instance.stop()
    except Exception:
        log.debug("Failed to stop Playwright instance during cleanup", exc_info=True)
    bs.page = None
    bs.browser = None
    bs.pw_instance = None
    bs._thread_id = None


def _is_infrastructure_error(obj: Any) -> bool:
    """Detect browser infrastructure failure from either context state or an error object.

    Backward-compat: older tests call this with an exception and expect string-based
    detection of greenlet/thread/browser teardown failures.
    """
    if hasattr(obj, "browser_state"):
        bs = obj.browser_state
        if bs.browser is None or bs.pw_instance is None:
            return True
        try:
            if not bs.browser.is_connected():
                return True
        except Exception:
            return True
        if bs.page is not None:
            try:
                if bs.page.is_closed():
                    return True
            except Exception:
                return True
        return False

    msg = str(obj).lower()
    return any(token in msg for token in (
        "green thread",
        "different thread",
        "browser has been closed",
        "page has been closed",
        "connection closed",
    ))


_MARKDOWN_JS = """() => {
    const walk = (el) => {
        let out = '';
        for (const child of el.childNodes) {
            if (child.nodeType === 3) {
                const t = child.textContent.trim();
                if (t) out += t + ' ';
            } else if (child.nodeType === 1) {
                const tag = child.tagName;
                if (['SCRIPT','STYLE','NOSCRIPT'].includes(tag)) continue;
                if (['H1','H2','H3','H4','H5','H6'].includes(tag))
                    out += '\\n' + '#'.repeat(parseInt(tag[1])) + ' ';
                if (tag === 'P' || tag === 'DIV' || tag === 'BR') out += '\\n';
                if (tag === 'LI') out += '\\n- ';
                if (tag === 'A') out += '[';
                out += walk(child);
                if (tag === 'A') out += '](' + (child.href||'') + ')';
            }
        }
        return out;
    };
    return walk(document.body);
}"""


def _extract_page_output(page: Any, output: str, ctx: ToolContext) -> str:
    """Extract page content in the requested format."""
    if output == "screenshot":
        data = page.screenshot(type="png", full_page=False)
        b64 = base64.b64encode(data).decode()
        ctx.browser_state.last_screenshot_b64 = b64
        return (
            f"Screenshot captured ({len(b64)} bytes base64). "
            f"Call send_photo(image_base64='__last_screenshot__') to deliver it to the user."
        )
    elif output == "html":
        html = page.content()
        return html[:50000] + ("... [truncated]" if len(html) > 50000 else "")
    elif output == "markdown":
        text = page.evaluate(_MARKDOWN_JS)
        return text[:30000] + ("... [truncated]" if len(text) > 30000 else "")
    else:  # text
        text = page.inner_text("body")
        return text[:30000] + ("... [truncated]" if len(text) > 30000 else "")


def _browse_page(ctx: ToolContext, url: str, output: str = "text",
                 wait_for: str = "", timeout: int = 30000,
                 viewport: str = "") -> str:
    try:
        page = _ensure_browser(ctx)
        if viewport:
            _apply_viewport(page, viewport)
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        if wait_for:
            page.wait_for_selector(wait_for, timeout=timeout)
        return _extract_page_output(page, output, ctx)
    except Exception as e:
        if _is_infrastructure_error(ctx):
            log.warning("Browser infrastructure error: %s. Cleaning up and retrying...", e)
            cleanup_browser(ctx)
            page = _ensure_browser(ctx)
            if viewport:
                _apply_viewport(page, viewport)
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout)
            return _extract_page_output(page, output, ctx)
        raise


def _apply_viewport(page: Any, viewport: str) -> None:
    """Parse a 'WxH' string and resize the browser viewport."""
    try:
        parts = viewport.lower().split("x")
        w, h = int(parts[0]), int(parts[1])
        page.set_viewport_size({"width": max(320, w), "height": max(480, h)})
    except (ValueError, IndexError):
        log.warning("Invalid viewport '%s', expected WxH (e.g. '375x812')", viewport)


def _browser_action(ctx: ToolContext, action: str, selector: str = "",
                    value: str = "", timeout: int = 5000) -> str:
    def _do_action():
        page = _ensure_browser(ctx)

        if action == "click":
            if not selector:
                return "Error: selector required for click"
            page.click(selector, timeout=timeout)
            page.wait_for_timeout(500)
            return f"Clicked: {selector}"
        elif action == "fill":
            if not selector:
                return "Error: selector required for fill"
            page.fill(selector, value, timeout=timeout)
            return f"Filled {selector} with: {value}"
        elif action == "select":
            if not selector:
                return "Error: selector required for select"
            page.select_option(selector, value, timeout=timeout)
            return f"Selected {value} in {selector}"
        elif action == "screenshot":
            data = page.screenshot(type="png", full_page=False)
            b64 = base64.b64encode(data).decode()
            ctx.browser_state.last_screenshot_b64 = b64
            return (
                f"Screenshot captured ({len(b64)} bytes base64). "
                f"Call send_photo(image_base64='__last_screenshot__') to deliver it to the user."
            )
        elif action == "evaluate":
            if not value:
                return "Error: value (JS code) required for evaluate"
            result = page.evaluate(value)
            out = str(result)
            return out[:20000] + ("... [truncated]" if len(out) > 20000 else "")
        elif action == "scroll":
            direction = value or "down"
            if direction == "down":
                page.evaluate("window.scrollBy(0, 600)")
            elif direction == "up":
                page.evaluate("window.scrollBy(0, -600)")
            elif direction == "top":
                page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return f"Scrolled {direction}"
        else:
            return f"Unknown action: {action}. Use: click, fill, select, screenshot, evaluate, scroll"

    try:
        return _do_action()
    except Exception as e:
        if _is_infrastructure_error(ctx):
            log.warning("Browser infrastructure error: %s. Cleaning up and retrying...", e)
            cleanup_browser(ctx)
            return _do_action()
        raise


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry(
            name="browse_page",
            schema={
                "name": "browse_page",
                "description": (
                    "Open a URL in headless browser. Returns page content as text, "
                    "html, markdown, or screenshot (base64 PNG). "
                    "Browser persists across calls within a task. "
                    "For screenshots: use send_photo tool to deliver the image to the user. "
                    "Use viewport to test mobile layouts (e.g. '375x812')."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL to open"},
                        "output": {
                            "type": "string",
                            "enum": ["text", "html", "markdown", "screenshot"],
                            "description": "Output format (default: text)",
                        },
                        "wait_for": {
                            "type": "string",
                            "description": "CSS selector to wait for before extraction",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Page load timeout in ms (default: 30000)",
                        },
                        "viewport": {
                            "type": "string",
                            "description": "Viewport size as WxH (e.g. '375x812' for mobile, '1920x1080' for desktop). Default: current viewport.",
                        },
                    },
                    "required": ["url"],
                },
            },
            handler=_browse_page,
            timeout_sec=180,
        ),
        ToolEntry(
            name="browser_action",
            schema={
                "name": "browser_action",
                "description": (
                    "Perform action on current browser page. Actions: "
                    "click (selector), fill (selector + value), select (selector + value), "
                    "screenshot (base64 PNG), evaluate (JS code in value), "
                    "scroll (value: up/down/top/bottom)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["click", "fill", "select", "screenshot", "evaluate", "scroll"],
                            "description": "Action to perform",
                        },
                        "selector": {
                            "type": "string",
                            "description": "CSS selector for click/fill/select",
                        },
                        "value": {
                            "type": "string",
                            "description": "Value for fill/select, JS for evaluate, direction for scroll",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Action timeout in ms (default: 5000)",
                        },
                    },
                    "required": ["action"],
                },
            },
            handler=_browser_action,
            timeout_sec=180,
        ),
    ]
