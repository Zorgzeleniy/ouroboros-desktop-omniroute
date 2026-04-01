"""Regression checks for restart/reconnect client behavior."""

import os
import pathlib

REPO = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_ws_has_error_handler_and_reconnect_timer():
    source = _read("web/modules/ws.js")
    assert "socket.onerror" in source
    assert "_scheduleReconnect" in source
    assert "_scheduleUiRecovery" in source
    assert "_uiRecoveryTimer" in source
    assert "_watchdogTimer" in source
    assert "_lastMessageAt" in source
    assert "_startWatchdog" in source
    assert "window.location.replace" in source
    assert "location.reload()" not in source


def test_ws_queues_outbound_messages_when_disconnected():
    source = _read("web/modules/ws.js")
    assert "_pendingMessages" in source
    assert "status: 'queued'" in source
    assert "outbound_sent" in source


def test_chat_marks_pending_messages_until_reconnect():
    source = _read("web/modules/chat.js")
    assert "pendingUserBubbles" in source
    assert "Queued until reconnect" in source
    assert "result?.status === 'queued'" in source


def test_chat_resyncs_history_after_reconnect():
    source = _read("web/modules/chat.js")
    assert "async function syncHistory" in source
    assert "/api/chat/history?limit=1000" in source
    assert "cache: 'no-store'" in source
    assert "syncHistory({ includeUser: !historyLoaded })" in source
    assert "const expectedDisconnect = socketState !== WebSocket.OPEN" in source
    assert "if (expectedDisconnect && err instanceof TypeError)" in source


def test_server_enables_ws_ping_and_heartbeat():
    server_source = _read("server.py")
    helper_source = _read("ouroboros/server_runtime.py")
    assert "ws_heartbeat_loop" in server_source or "ws_heartbeat_loop" in helper_source
    assert '"type": "heartbeat"' in server_source or '"type": "heartbeat"' in helper_source
    assert "ws_ping_interval=20" in server_source
    assert "ws_ping_timeout=20" in server_source


def test_index_includes_reconnect_overlay():
    source = _read("web/index.html")
    assert 'id="reconnect-overlay"' in source


def test_index_page_disables_cache():
    server_source = _read("server.py")
    helper_source = _read("ouroboros/server_web.py")
    assert "cache-control" in server_source.lower() or "cache-control" in helper_source.lower()


def test_find_free_port_waits_for_preferred_port():
    """find_free_port should retry the preferred port before falling back."""
    import socket
    import threading
    from ouroboros.server_entrypoint import find_free_port

    # Grab any available port for isolation
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        preferred = s.getsockname()[1]

    # Block the preferred port with a listener that releases after a short delay
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", preferred))
    blocker.listen(1)

    def _release():
        import time
        time.sleep(1.0)
        blocker.close()

    threading.Thread(target=_release, daemon=True).start()

    # With wait_retries=6 × 0.5s = 3s budget, it should get the preferred port
    result = find_free_port("127.0.0.1", preferred, wait_retries=6, wait_interval=0.5)
    assert result == preferred, f"Expected preferred port {preferred}, got {result}"


def test_find_free_port_falls_back_when_stuck():
    """find_free_port should fall back to a nearby port if preferred stays busy."""
    import socket
    from ouroboros.server_entrypoint import find_free_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        preferred = s.getsockname()[1]

    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", preferred))
    blocker.listen(1)

    try:
        # Very short wait — should give up and use fallback
        result = find_free_port("127.0.0.1", preferred, max_tries=10,
                                wait_retries=2, wait_interval=0.05)
        assert result != preferred, f"Should have fallen back, but got preferred {preferred}"
    finally:
        blocker.close()


def test_restart_watchdog_waits_for_uvicorn_exit():
    source = _read("server.py")
    assert "_uvicorn_exited = threading.Event()" in source
    assert "_uvicorn_exited.wait(timeout=force_exit_timeout_sec)" in source
    assert "_uvicorn_exited.set()" in source
