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
    assert "_reloadFallbackTimer" in source
    assert "_watchdogTimer" in source
    assert "_lastMessageAt" in source
    assert "_startWatchdog" in source


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
