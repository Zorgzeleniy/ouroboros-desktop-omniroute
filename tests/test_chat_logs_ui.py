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
    assert "const taskUiStates = new Map();" in source
    assert "summarizeChatLiveEvent" in source
    assert "Show details" in source
    assert "if (msg.is_progress) {" in source
    assert "updateLiveCardFromProgressMessage(msg);" in source
    assert "appendTaskSummaryToLiveCard(msg);" in source
    assert "if (explicitTaskId) finishLiveCard(explicitTaskId);" in source
    assert "ws.on('log', (msg) => {" in source
    assert "updateLiveCardFromLogEvent(msg.data);" in source
    assert "if (msg.is_progress) {" in source
    assert "hideTypingIndicatorOnly();" in source
    assert "function hasActiveLiveCard()" in source
    assert "state.activePage !== 'chat'" in source
    assert "function isNearBottom(threshold = 96)" in source
    assert "if (node.parentNode === messagesDiv) {" in source
    assert "if (shouldStick) messagesDiv.scrollTop = messagesDiv.scrollHeight;" in source
    assert "function markTaskToolCall(taskId, count = 1, minimumOnly = false)" in source
    assert "taskState.forceCard || taskState.toolCalls > 1 || shouldAlwaysShowTaskCard(taskState.taskId)" in source
    assert "function forceTaskCard(taskId)" in source
    assert "function markAssistantReply(taskId = '')" in source
    assert "function isTerminalTaskPhase(phase = '') {" in source
    assert "taskState.completed = true;" in source
    assert "scheduleTaskUiCleanup(taskState, 30000);" in source
    assert "if (taskState.completed && !isTerminalTaskPhase(summary.phase || '')) {" in source
    assert "if (record.finished && !isTerminalTaskPhase(nextPhase)) {" in source
    assert "const taskId = msg.task_id || '';" in source
    assert "const taskState = getTaskUiState(taskId, true);" in source
    assert "if (taskState.completed) continue;" in source
    assert "const wasFinished = record.finished;" in source
    assert "const justFinished = record.finished && !wasFinished;" in source
    assert "if (justFinished) {" in source
    assert "if (!wasFinished) {" in source
    assert "function setLiveCardExpanded(record, expanded) {" in source
    assert "record.root.dataset.expanded = expanded ? '1' : '0';" in source
    assert "function syncLiveCardLayout(record) {" in source
    assert "record.root.style.minHeight = `${Math.max(summaryHeight + timelineHeight, 0)}px`;" in source


def test_live_card_recovery_keeps_step_failures_non_terminal():
    chat_source = _read("web/modules/chat.js")
    log_source = _read("web/modules/log_events.js")

    assert "return phase === 'done';" in chat_source
    assert "if (phase === 'warn') return 'Notice';" in chat_source
    assert "record.finished = isTerminalTaskPhase(nextPhase);" in chat_source
    assert "const activePhase = ['error', 'timeout'].includes(phase) ? phase : 'done';" in chat_source
    assert "function extractCommandText(args) {" in log_source
    assert "evt.status === 'non_zero_exit'" in log_source
    assert "phase: 'warn'" in log_source
    assert "A command returned" in log_source
    assert "commandText.full || errorResult.full" in log_source


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
    assert re.search(r"\.chat-live-line-body\s*\{[^}]*font-size:\s*\d+px;", css, re.S)


def test_dashboard_and_chat_only_poll_state_when_active():
    chat_source = _read("web/modules/chat.js")
    dash_source = _read("web/modules/dashboard.js")

    assert "state.activePage !== 'chat'" in chat_source
    assert "state.activePage !== 'dashboard'" in dash_source
    assert "cache: 'no-store'" in dash_source
    assert "Dashboard unavailable:" in dash_source


def test_live_card_has_inline_typing_dots_and_pulsing_phase_badge():
    css = _read("web/style.css")
    chat_source = _read("web/modules/chat.js")

    # Inline typing dots in live card summary
    assert ".chat-live-typing {" in css
    assert ".chat-live-typing span {" in css
    assert 'animation: typing-bounce' in css
    assert '.chat-live-card[data-finished="1"] .chat-live-typing {' in css

    # Active phase badge should pulse
    assert "animation: thinking-pulse" in css
    assert '.chat-live-card:not([data-finished="1"]) .chat-live-phase.working' in css

    # JS: typing visibility helpers exist
    assert "function setLiveCardTypingVisible(record, visible) {" in chat_source
    assert "inlineTypingEl: root.querySelector('[data-live-typing]')" in chat_source
    assert "setLiveCardTypingVisible(record, false);" in chat_source
    assert "setLiveCardTypingVisible(record, true);" in chat_source

    # HTML template has the typing element
    assert "data-live-typing" in chat_source


def test_live_card_timeline_body_renders_markdown():
    """Live card timeline body must use renderMarkdown, not escapeHtml."""
    source = _read("web/modules/chat.js")
    # The body div inside the timeline must use renderMarkdown so that
    # markdown formatting (bold, lists, etc.) is rendered correctly.
    assert "renderMarkdown(displayBody)" in source
    # escapeHtml must NOT be used for displayBody in the timeline
    assert "escapeHtml(displayBody)" not in source


def test_live_card_timeline_headline_renders_markdown_for_progress():
    """working/thinking phase lines must render their headline with renderMarkdown."""
    source = _read("web/modules/chat.js")
    # isProgressLine must check the actual phase values emitted by summarizeChatLiveEvent
    assert "isProgressLine" in source
    assert "isProgressLine ? renderMarkdown(displayHeadline)" in source
    # Must use 'working' and 'thinking' — NOT the dead 'progress'/'thought' names
    assert "item.phase === 'working' || item.phase === 'thinking'" in source
    assert "item.phase === 'progress' || item.phase === 'thought'" not in source


def test_chat_history_replays_task_summaries_into_live_cards():
    history_source = _read("ouroboros/server_history_api.py")
    chat_source = _read("web/modules/chat.js")

    assert '"task_id": str(entry.get("task_id", ""))' in history_source
    assert "const taskId = msg.task_id || '';" in chat_source
    assert "appendTaskSummaryToLiveCard(msg);" in chat_source
    assert "taskId," in chat_source
    assert "if (role !== 'user' && !opts.isProgress && opts.taskId) {" in chat_source


def test_chat_history_forces_live_card_for_historical_task_summaries():
    """Historical task_summary messages must force the live card visible.

    After a restart taskState.toolCalls is 0, so revealBufferedCardIfNeeded
    would silently skip the card unless forceCard is set before the call.
    """
    source = _read("web/modules/chat.js")
    # forceCard must be set to true immediately before appendTaskSummaryToLiveCard
    # in the syncHistory loop
    assert "taskState.forceCard = true;" in source
    # The force must happen inside the task_summary branch of syncHistory
    idx_force = source.index("taskState.forceCard = true;")
    idx_append = source.index("appendTaskSummaryToLiveCard(msg);")
    assert idx_force < idx_append, "forceCard must be set before appendTaskSummaryToLiveCard"
