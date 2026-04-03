/**
 * Ouroboros Web UI — Main orchestrator.
 *
 * Self-editable: this file lives in REPO_DIR and can be modified by the agent.
 * Vanilla JS, no build step. Uses ES modules for page decomposition.
 *
 * Each page is a module in web/modules/ that exports an init function.
 * This file wires them together with shared state and navigation.
 */

import { createWS } from './modules/ws.js';
import { loadVersion, initMatrixRain } from './modules/utils.js';
import { initChat } from './modules/chat.js';
import { initDashboard } from './modules/dashboard.js';
import { initLogs } from './modules/logs.js';
import { initEvolution } from './modules/evolution.js';
import { initSettings } from './modules/settings.js';
import { initCosts } from './modules/costs.js';
import { initVersions } from './modules/versions.js';
import { initAbout } from './modules/about.js';

// ---------------------------------------------------------------------------
// Shared State
// ---------------------------------------------------------------------------
const state = {
    messages: [],
    logs: [],
    dashboard: {},
    activeFilters: { tools: true, llm: true, errors: true, tasks: true, system: true, consciousness: true },
    unreadCount: 0,
    activePage: 'chat',
};

// ---------------------------------------------------------------------------
// WebSocket (created but not yet connected — deferred until after init)
// ---------------------------------------------------------------------------
const ws = createWS();

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function showPage(name) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`page-${name}`)?.classList.add('active');
    document.querySelector(`.nav-btn[data-page="${name}"]`)?.classList.add('active');
    state.activePage = name;
    if (name === 'chat') {
        state.unreadCount = 0;
        updateUnreadBadge();
    }
}

function updateUnreadBadge() {
    const btn = document.querySelector('.nav-btn[data-page="chat"]');
    let badge = btn?.querySelector('.unread-badge');
    if (state.unreadCount > 0 && state.activePage !== 'chat') {
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'unread-badge';
            btn.appendChild(badge);
        }
        badge.textContent = state.unreadCount > 99 ? '99+' : state.unreadCount;
    } else if (badge) {
        badge.remove();
    }
}

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => showPage(btn.dataset.page));
});

// ---------------------------------------------------------------------------
// Initialize All Pages (registers WS listeners before connection opens)
// ---------------------------------------------------------------------------
const ctx = { ws, state, updateUnreadBadge };

initChat(ctx);
initDashboard(ctx);
initLogs(ctx);
initEvolution(ctx);
initSettings(ctx);
initCosts(ctx);
initVersions(ctx);
initAbout(ctx);

// ---------------------------------------------------------------------------
// Startup — connect WS only after all modules have registered their listeners
// ---------------------------------------------------------------------------
initMatrixRain();
loadVersion();
ws.connect();
