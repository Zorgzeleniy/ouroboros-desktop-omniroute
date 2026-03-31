"""Regression checks for chat live-card and grouped logs UI."""

import os
import pathlib
import re

REPO = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_chat_progress_updates_route_into_live_card():
    source = _read("web/modules/chat.js")

    assert "const liveCardRecords = new Map();" in source
    assert "summarizeChatLiveEvent" in source
    assert "Show details" in source
    assert "if (msg.is_progress) {" in source
    assert "updateLiveCardFromProgressMessage(msg);" in source
    assert "appendTaskSummaryToLiveCard(msg);" in source
    assert "finishLiveCard(msg.task_id || activeLiveGroupId);" in source
    assert "ws.on('log', (msg) => {" in source
    assert "updateLiveCardFromLogEvent(msg.data);" in source
    assert "if (msg.is_progress) {" in source
    assert "hideTypingIndicatorOnly();" in source
    assert "function hasActiveLiveCard()" in source
    assert "state.activePage !== 'chat'" in source
    assert "const wasFinished = record.finished;" in source
    assert "const justFinished = record.finished && !wasFinished;" in source
    assert "if (justFinished) {" in source
    assert "if (!wasFinished) {" in source
    assert "function setLiveCardExpanded(record, expanded) {" in source
    assert "record.root.dataset.expanded = expanded ? '1' : '0';" in source
    assert "function syncLiveCardLayout(record) {" in source
    assert "record.root.style.minHeight = `${Math.max(summaryHeight + timelineHeight, 0)}px`;" in source


def test_logs_use_shared_log_event_helpers_and_group_task_cards():
    logs_source = _read("web/modules/logs.js")
    shared_source = _read("web/modules/log_events.js")

    assert "from './log_events.js'" in logs_source
    assert "isGroupedTaskEvent(evt)" in logs_source
    assert "createTaskGroupCard" in logs_source
    assert "renderTaskTimeline" in logs_source
    assert "export function summarizeLogEvent" in shared_source
    assert "export function summarizeChatLiveEvent" in shared_source
    assert "export function isGroupedTaskEvent" in shared_source
    assert "export function getLogTaskGroupId" in shared_source


def test_styles_cover_chat_header_controls_and_grouped_cards():
    css = _read("web/style.css")

    assert "--accent-light:" in css
    assert ".chat-header-actions {" in css
    assert ".chat-header-btn {" in css
    assert ".chat-live-card {" in css
    assert '.chat-live-card[data-finished="1"] {' in css
    assert ".chat-live-timeline {" in css
    assert ".chat-live-toggle {" in css
    assert ".chat-live-summary-button {" in css
    assert '.chat-live-card[data-expanded="1"] .chat-live-chevron {' in css
    assert '.chat-live-card[data-expanded="1"] .chat-live-timeline {' in css
    assert ".log-task-card {" in css
    assert ".log-task-timeline {" in css
    assert re.search(r"\.chat-live-title\s*\{[^}]*font-weight:\s*400;", css, re.S)
    assert re.search(r"\.chat-live-line-title\s*\{[^}]*font-weight:\s*400;", css, re.S)
    assert re.search(r"\.chat-live-line-body\s*\{[^}]*font-size:\s*15px;", css, re.S)


def test_dashboard_and_chat_only_poll_state_when_active():
    chat_source = _read("web/modules/chat.js")
    dash_source = _read("web/modules/dashboard.js")

    assert "state.activePage !== 'chat'" in chat_source
    assert "state.activePage !== 'dashboard'" in dash_source
    assert "cache: 'no-store'" in dash_source


def test_chat_history_replays_task_summaries_into_live_cards():
    history_source = _read("ouroboros/server_history_api.py")
    chat_source = _read("web/modules/chat.js")

    assert '"task_id": str(entry.get("task_id", ""))' in history_source
    assert "appendTaskSummaryToLiveCard(msg);" in chat_source
    assert "taskId: msg.task_id || ''" in chat_source
