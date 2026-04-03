import { escapeHtml } from './utils.js';

export function initLogs({ ws, state }) {
    const categories = {
        tools: { label: 'Tools', color: 'var(--blue)' },
        llm: { label: 'LLM', color: 'var(--accent)' },
        errors: { label: 'Errors', color: 'var(--red)' },
        tasks: { label: 'Tasks', color: 'var(--amber)' },
        system: { label: 'System', color: 'var(--text-muted)' },
        consciousness: { label: 'Consciousness', color: 'var(--accent)' },
    };

    const page = document.createElement('div');
    page.id = 'page-logs';
    page.className = 'page';
    page.innerHTML = `
        <div class="page-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
            <h2>Logs</h2>
            <div class="spacer"></div>
            <button class="btn btn-default" id="btn-clear-logs">Clear</button>
        </div>
        <div class="logs-filters" id="log-filters"></div>
        <div id="log-entries"></div>
    `;
    document.getElementById('content').appendChild(page);

    const filtersDiv = document.getElementById('log-filters');
    Object.entries(categories).forEach(([key, cat]) => {
        const chip = document.createElement('button');
        chip.className = `filter-chip ${state.activeFilters[key] ? 'active' : ''}`;
        chip.textContent = cat.label;
        chip.addEventListener('click', () => {
            state.activeFilters[key] = !state.activeFilters[key];
            chip.classList.toggle('active');
            logEntries.querySelectorAll('.log-entry').forEach(el => {
                const entryCat = el.dataset.category;
                if (entryCat) {
                    el.style.display = state.activeFilters[entryCat] ? '' : 'none';
                }
            });
        });
        filtersDiv.appendChild(chip);
    });

    const logEntries = document.getElementById('log-entries');
    const MAX_LOGS = 500;
    const duplicateWindowMs = 5000;
    const duplicateState = new Map();

    function categorizeEvent(evt) {
        const t = evt.type || evt.event || '';
        if (evt.is_progress) {
            return evt.task_id === 'bg-consciousness' ? 'consciousness' : 'tasks';
        }
        if (t.includes('error') || t.includes('crash') || t.includes('fail')) return 'errors';
        if (t.includes('llm') || t.includes('model')) return 'llm';
        if (t.includes('tool') || evt.tool) return 'tools';
        if (t.includes('task') || t.includes('evolution') || t.includes('review')) return 'tasks';
        if (t.includes('consciousness') || t.includes('bg_')) return 'consciousness';
        return 'system';
    }

    function normalizeTs(isoStr) {
        if (!isoStr) return '';
        try {
            const d = new Date(isoStr);
            if (Number.isNaN(d.getTime())) return '';
            return d.toLocaleTimeString([], { hour12: false });
        } catch {
            return '';
        }
    }

    function shortText(text, maxLen = 180) {
        const s = String(text || '').replace(/\s+/g, ' ').trim();
        if (!s) return '';
        return s.length > maxLen ? s.slice(0, maxLen - 3) + '...' : s;
    }

    function formatMoney(v) {
        const num = Number(v);
        if (!Number.isFinite(num) || num <= 0) return '';
        return `$${num.toFixed(4)}`;
    }

    function formatDuration(sec) {
        const num = Number(sec);
        if (!Number.isFinite(num) || num < 0) return '';
        if (num >= 60) {
            const mins = Math.floor(num / 60);
            const rem = Math.round(num % 60);
            return `${mins}m ${rem}s`;
        }
        return `${num < 10 ? num.toFixed(1) : Math.round(num)}s`;
    }

    function formatTokens(evt) {
        const prompt = Number(evt.prompt_tokens || 0);
        const completion = Number(evt.completion_tokens || 0);
        if (!prompt && !completion) return '';
        return `${prompt}\u2192${completion} tok`;
    }

    function compactJson(value, maxLen = 220) {
        if (value == null) return '';
        let txt = '';
        try {
            txt = JSON.stringify(value);
        } catch {
            txt = String(value);
        }
        return shortText(txt, maxLen);
    }

    function describeStartupChecks(checks) {
        if (!checks || typeof checks !== 'object') return '';
        const parts = [];
        for (const [key, value] of Object.entries(checks)) {
            if (value && typeof value === 'object' && value.status) {
                parts.push(`${key}:${value.status}`);
            }
        }
        return shortText(parts.join(' | '), 240);
    }

    function summarizeEvent(evt) {
        const t = evt.type || evt.event || 'unknown';
        const base = {
            typeLabel: t,
            phase: '',
            headline: '',
            body: '',
            meta: [],
        };

        if (evt.is_progress || t === 'send_message') {
            return {
                ...base,
                phase: evt.task_id === 'bg-consciousness' ? 'thought' : 'progress',
                headline: shortText(String(evt.content || evt.text || '').replace(/^💬\s*/, ''), 240) || 'Progress update',
                meta: [evt.task_id === 'bg-consciousness' ? 'background' : 'task'].filter(Boolean),
            };
        }

        if (t === 'task_started') {
            return {
                ...base,
                phase: 'start',
                headline: `Started ${evt.task_type || 'task'}`,
                body: shortText(evt.task_text, 220),
                meta: [evt.task_id ? `task=${evt.task_id}` : '', evt.direct_chat ? 'chat' : 'queued'].filter(Boolean),
            };
        }

        if (t === 'task_received') {
            const task = evt.task || {};
            return {
                ...base,
                phase: 'queued',
                headline: `Received ${task.type || 'task'}`,
                body: shortText(task.text, 220),
                meta: [task.id ? `task=${task.id}` : '', task.text_len ? `${task.text_len} chars` : ''].filter(Boolean),
            };
        }

        if (t === 'context_building_started') {
            return {
                ...base,
                phase: 'context',
                headline: 'Building context',
                meta: [evt.task_id ? `task=${evt.task_id}` : '', evt.task_type || ''].filter(Boolean),
            };
        }

        if (t === 'context_building_finished') {
            return {
                ...base,
                phase: 'ready',
                headline: 'Context ready',
                meta: [
                    evt.task_id ? `task=${evt.task_id}` : '',
                    evt.message_count != null ? `${evt.message_count} msgs` : '',
                    Number.isFinite(Number(evt.budget_remaining_usd)) ? `$${Number(evt.budget_remaining_usd).toFixed(2)} left` : '',
                ].filter(Boolean),
            };
        }

        if (t === 'task_heartbeat') {
            return {
                ...base,
                phase: evt.phase || 'alive',
                headline: 'Still working',
                meta: [
                    evt.task_id ? `task=${evt.task_id}` : '',
                    evt.task_type || '',
                    formatDuration(evt.runtime_sec),
                ].filter(Boolean),
            };
        }

        if (t === 'llm_round_started') {
            return {
                ...base,
                phase: 'calling',
                headline: `Calling ${evt.model || 'model'}`,
                meta: [
                    evt.task_id ? `task=${evt.task_id}` : '',
                    evt.round ? `r${evt.round}` : '',
                    evt.attempt ? `try ${evt.attempt}` : '',
                    evt.reasoning_effort || '',
                    evt.use_local ? 'local' : '',
                ].filter(Boolean),
            };
        }

        if (t === 'llm_round_finished' || t === 'llm_round') {
            return {
                ...base,
                phase: 'done',
                headline: `LLM round ${evt.round || ''} finished`.trim(),
                meta: [
                    evt.task_id ? `task=${evt.task_id}` : '',
                    evt.model || '',
                    formatTokens(evt),
                    formatMoney(evt.cost_usd || evt.cost),
                    evt.response_kind === 'tool_calls' ? `${evt.tool_call_count || 0} tool calls` : evt.response_kind || '',
                ].filter(Boolean),
            };
        }

        if (t === 'llm_round_empty' || t === 'llm_empty_response') {
            return {
                ...base,
                phase: 'empty',
                headline: `Model returned empty response`,
                meta: [evt.task_id ? `task=${evt.task_id}` : '', evt.model || '', evt.round ? `r${evt.round}` : ''].filter(Boolean),
            };
        }

        if (t === 'llm_round_error' || t === 'llm_api_error') {
            return {
                ...base,
                phase: 'error',
                headline: 'LLM call failed',
                body: shortText(evt.error, 260),
                meta: [evt.task_id ? `task=${evt.task_id}` : '', evt.model || '', evt.round ? `r${evt.round}` : ''].filter(Boolean),
            };
        }

        if (t === 'llm_usage') {
            return {
                ...base,
                phase: 'usage',
                headline: 'LLM usage recorded',
                meta: [
                    evt.task_id ? `task=${evt.task_id}` : '',
                    evt.model || '',
                    formatTokens(evt),
                    formatMoney(evt.cost_usd || evt.cost),
                    evt.category || '',
                ].filter(Boolean),
            };
        }

        if (t === 'tool_call_started') {
            return {
                ...base,
                phase: 'start',
                headline: `Running ${evt.tool || 'tool'}`,
                body: compactJson(evt.args, 260),
                meta: [evt.task_id ? `task=${evt.task_id}` : '', evt.timeout_sec ? `timeout ${evt.timeout_sec}s` : ''].filter(Boolean),
            };
        }

        if (t === 'tool_call_finished') {
            return {
                ...base,
                phase: evt.is_error ? 'error' : 'done',
                headline: `${evt.tool || 'tool'} ${evt.is_error ? 'failed' : 'finished'}`,
                body: shortText(evt.result_preview, 260),
                meta: [evt.task_id ? `task=${evt.task_id}` : '', formatDuration(evt.duration_sec)].filter(Boolean),
            };
        }

        if (t === 'tool_call_timeout' || t === 'tool_timeout') {
            return {
                ...base,
                phase: 'timeout',
                headline: `${evt.tool || 'tool'} timed out`,
                body: compactJson(evt.args, 220),
                meta: [evt.task_id ? `task=${evt.task_id}` : '', evt.timeout_sec ? `limit ${evt.timeout_sec}s` : '', formatDuration(evt.duration_sec)].filter(Boolean),
            };
        }

        if (t === 'tool_call' || evt.tool) {
            return {
                ...base,
                phase: 'result',
                headline: `${evt.tool || 'tool'} result`,
                body: shortText(evt.result_preview || compactJson(evt.args, 220), 260),
                meta: [evt.task_id ? `task=${evt.task_id}` : ''].filter(Boolean),
            };
        }

        if (t === 'task_metrics_event' || t === 'task_eval') {
            return {
                ...base,
                phase: 'metrics',
                headline: 'Task metrics',
                meta: [
                    evt.task_id ? `task=${evt.task_id}` : '',
                    evt.task_type || '',
                    formatDuration(evt.duration_sec),
                    evt.tool_calls != null ? `${evt.tool_calls} tools` : '',
                    evt.tool_errors ? `${evt.tool_errors} errors` : '',
                    evt.response_len ? `${evt.response_len} chars` : '',
                ].filter(Boolean),
            };
        }

        if (t === 'task_done') {
            return {
                ...base,
                phase: 'done',
                headline: `Finished ${evt.task_type || 'task'}`,
                meta: [
                    evt.task_id ? `task=${evt.task_id}` : '',
                    formatMoney(evt.cost_usd || evt.cost),
                    evt.total_rounds ? `${evt.total_rounds} rounds` : '',
                    formatTokens(evt),
                ].filter(Boolean),
            };
        }

        if (t === 'startup_verification') {
            return {
                ...base,
                phase: Number(evt.issues_count || 0) > 0 ? 'warn' : 'ok',
                headline: 'Startup verification',
                body: describeStartupChecks(evt.checks),
                meta: [
                    evt.git_sha ? String(evt.git_sha).slice(0, 8) : '',
                    `${evt.issues_count || 0} issues`,
                ].filter(Boolean),
            };
        }

        if (t === 'worker_spawn_start') {
            return {
                ...base,
                phase: 'start',
                headline: `Spawning ${evt.count || '?'} workers`,
                meta: [evt.start_method || ''].filter(Boolean),
            };
        }

        if (t === 'worker_sha_verify') {
            return {
                ...base,
                phase: evt.ok ? 'ok' : 'warn',
                headline: evt.ok ? 'Worker SHA verified' : 'Worker SHA mismatch',
                meta: [
                    evt.expected_sha ? `exp ${String(evt.expected_sha).slice(0, 8)}` : '',
                    evt.observed_sha ? `got ${String(evt.observed_sha).slice(0, 8)}` : '',
                    evt.worker_pid ? `pid ${evt.worker_pid}` : '',
                ].filter(Boolean),
            };
        }

        if (t === 'worker_boot') {
            return {
                ...base,
                phase: 'boot',
                headline: 'Worker booted',
                meta: [
                    evt.pid ? `pid ${evt.pid}` : '',
                    evt.git_sha ? String(evt.git_sha).slice(0, 8) : '',
                ].filter(Boolean),
            };
        }

        if (t === 'deps_sync_ok') {
            return {
                ...base,
                phase: 'ok',
                headline: 'Dependencies in sync',
                meta: [evt.reason || '', shortText(evt.source, 60)].filter(Boolean),
            };
        }

        if (t === 'reset_unsynced_rescued_then_reset') {
            return {
                ...base,
                phase: 'warn',
                headline: 'Recovered dirty worktree before restart',
                meta: [
                    evt.reason || '',
                    evt.dirty_count != null ? `${evt.dirty_count} dirty` : '',
                    evt.unpushed_count != null ? `${evt.unpushed_count} unpushed` : '',
                ].filter(Boolean),
            };
        }

        if (t.includes('error') || t.includes('crash') || t.includes('fail')) {
            return {
                ...base,
                phase: 'error',
                headline: t,
                body: shortText(evt.error || evt.result_preview || evt.text || '', 260),
                meta: [evt.task_id ? `task=${evt.task_id}` : '', evt.tool ? `tool=${evt.tool}` : ''].filter(Boolean),
            };
        }

        return {
            ...base,
            phase: 'info',
            headline: shortText(t, 120),
            body: shortText(
                evt.text || evt.error || evt.result_preview || compactJson(evt.args || evt.task || evt.checks, 260),
                260,
            ),
            meta: [
                evt.task_id ? `task=${evt.task_id}` : '',
                evt.model || '',
                formatMoney(evt.cost_usd || evt.cost),
            ].filter(Boolean),
        };
    }

    function duplicateKey(evt) {
        const t = evt.type || evt.event || '';
        if (t === 'startup_verification') return `${t}:${evt.git_sha || ''}:${evt.issues_count || 0}`;
        if (t === 'worker_sha_verify') return `${t}:${evt.expected_sha || ''}:${evt.observed_sha || ''}:${evt.ok ? 1 : 0}`;
        if (t === 'deps_sync_ok') return `${t}:${evt.reason || ''}:${evt.source || ''}`;
        return '';
    }

    function prettyRaw(evt) {
        try {
            return JSON.stringify(evt, null, 2);
        } catch {
            return String(evt);
        }
    }

    function updateVisibility(entry) {
        entry.style.display = state.activeFilters[entry.dataset.category] ? '' : 'none';
    }

    function addLogEntry(evt) {
        const view = summarizeEvent(evt);
        if (!view) return;
        const cat = categorizeEvent(evt);
        const dedupeKey = duplicateKey(evt);
        const now = (() => {
            const parsed = evt.ts ? Date.parse(evt.ts) : NaN;
            return Number.isFinite(parsed) ? parsed : Date.now();
        })();

        if (dedupeKey) {
            let last = duplicateState.get(dedupeKey);
            if (last && !logEntries.contains(last.entry)) {
                duplicateState.delete(dedupeKey);
                last = null;
            }
            if (last && now - last.ts <= duplicateWindowMs) {
                last.count += 1;
                last.ts = now;
                const repeatEl = last.entry.querySelector('.log-repeat');
                if (repeatEl) {
                    repeatEl.textContent = `x${last.count}`;
                    repeatEl.style.display = '';
                }
                return;
            }
    }

        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.dataset.category = cat;
        const raw = prettyRaw(evt);
        const metaHtml = view.meta.length
            ? `<div class="log-meta">${view.meta.map(item => `<span class="log-pill">${escapeHtml(item)}</span>`).join('')}</div>`
            : '';
        const bodyHtml = view.body
            ? `<div class="log-body">${escapeHtml(view.body)}</div>`
            : '';
        entry.innerHTML = `
            <div class="log-main">
                <span class="log-ts">${escapeHtml(normalizeTs(evt.ts))}</span>
                <span class="log-type ${cat}">${escapeHtml(view.typeLabel)}</span>
                <span class="log-phase ${escapeHtml(view.phase || 'info')}">${escapeHtml(view.phase || 'info')}</span>
                <span class="log-headline">${escapeHtml(view.headline || 'Event')}</span>
                <span class="log-repeat" style="display:none"></span>
            </div>
            ${metaHtml}
            ${bodyHtml}
            <div class="log-actions">
                <button class="log-raw-toggle" type="button">Raw</button>
            </div>
            <pre class="log-raw" hidden>${escapeHtml(raw)}</pre>
        `;
        const rawToggle = entry.querySelector('.log-raw-toggle');
        const rawEl = entry.querySelector('.log-raw');
        rawToggle.addEventListener('click', () => {
            const isHidden = rawEl.hasAttribute('hidden');
            if (isHidden) {
                rawEl.removeAttribute('hidden');
                rawToggle.textContent = 'Hide raw';
            } else {
                rawEl.setAttribute('hidden', '');
                rawToggle.textContent = 'Raw';
            }
        });
        updateVisibility(entry);
        logEntries.appendChild(entry);

        if (dedupeKey) {
            duplicateState.set(dedupeKey, { entry, ts: now, count: 1 });
        }

        while (logEntries.children.length > MAX_LOGS) {
            logEntries.removeChild(logEntries.firstChild);
        }
        if (state.activeFilters[cat]) logEntries.scrollTop = logEntries.scrollHeight;
    }

    ws.on('log', (msg) => {
        if (msg.data) addLogEntry(msg.data);
    });

    document.getElementById('btn-clear-logs').addEventListener('click', () => {
        logEntries.innerHTML = '';
    });
}
