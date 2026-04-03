import { escapeHtml } from './utils.js';

export function initVersions({ ws, state }) {
    const page = document.createElement('div');
    page.id = 'page-versions';
    page.className = 'page';
    page.innerHTML = `
        <div class="page-header">
            <h2>Version Management</h2>
            <div style="display:flex;gap:8px">
                <button class="btn btn-primary" id="btn-promote">Promote to Stable</button>
                <button class="btn" id="btn-refresh-versions">Refresh</button>
            </div>
        </div>
        <div id="ver-current" style="margin-bottom:16px;font-size:13px;color:var(--text-secondary)"></div>
        <div style="display:flex;gap:24px;flex:1;overflow:hidden">
            <div style="flex:1;display:flex;flex-direction:column;overflow:hidden">
                <h3 style="margin-bottom:8px;font-size:14px;color:var(--text-secondary)">Recent Commits</h3>
                <div id="ver-commits" class="log-scroll" style="flex:1;overflow-y:auto"></div>
            </div>
            <div style="flex:1;display:flex;flex-direction:column;overflow:hidden">
                <h3 style="margin-bottom:8px;font-size:14px;color:var(--text-secondary)">Tags</h3>
                <div id="ver-tags" class="log-scroll" style="flex:1;overflow-y:auto"></div>
            </div>
        </div>
    `;
    document.getElementById('content').appendChild(page);

    const commitsDiv = document.getElementById('ver-commits');
    const tagsDiv = document.getElementById('ver-tags');
    const currentDiv = document.getElementById('ver-current');

    function renderRow(item, labelText, targetId) {
        const row = document.createElement('div');
        row.className = 'log-entry';
        row.style.display = 'flex';
        row.style.alignItems = 'center';
        row.style.gap = '8px';
        const date = (item.date || '').slice(0, 16).replace('T', ' ');
        const msg = escapeHtml((item.message || '').slice(0, 60));
        row.innerHTML = `
            <span class="log-type tools" style="min-width:70px;text-align:center">${escapeHtml(labelText)}</span>
            <span class="log-ts">${date}</span>
            <span class="log-msg" style="flex:1">${msg}</span>
            <button class="btn btn-danger" style="padding:2px 8px;font-size:11px" data-target="${escapeHtml(targetId)}">Restore</button>
        `;
        row.querySelector('button').addEventListener('click', () => rollback(targetId));
        return row;
    }

    async function loadVersions() {
        try {
            const resp = await fetch('/api/git/log');
            const data = await resp.json();
            currentDiv.textContent = `Branch: ${data.branch || '?'} @ ${data.sha || '?'}`;

            commitsDiv.innerHTML = '';
            (data.commits || []).forEach(c => {
                commitsDiv.appendChild(renderRow(c, c.short_sha || c.sha?.slice(0, 8), c.sha));
            });
            if (!data.commits?.length) commitsDiv.innerHTML = '<div style="color:var(--text-muted);padding:12px">No commits found</div>';

            tagsDiv.innerHTML = '';
            (data.tags || []).forEach(t => {
                tagsDiv.appendChild(renderRow(t, t.tag, t.tag));
            });
            if (!data.tags?.length) tagsDiv.innerHTML = '<div style="color:var(--text-muted);padding:12px">No tags found</div>';
        } catch (e) {
            commitsDiv.innerHTML = `<div style="color:var(--red);padding:12px">Failed to load: ${e.message}</div>`;
        }
    }

    async function rollback(target) {
        if (!confirm(`Roll back to ${target}?\n\nA rescue snapshot of the current state will be saved. The server will restart.`)) return;
        try {
            const resp = await fetch('/api/git/rollback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target }),
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                alert('Rollback successful: ' + data.message + '\n\nServer is restarting...');
            } else {
                alert('Rollback failed: ' + (data.error || 'unknown error'));
            }
        } catch (e) {
            alert('Rollback failed: ' + e.message);
        }
    }

    document.getElementById('btn-promote').addEventListener('click', async () => {
        if (!confirm('Promote current ouroboros branch to ouroboros-stable?')) return;
        try {
            const resp = await fetch('/api/git/promote', { method: 'POST' });
            const data = await resp.json();
            alert(data.status === 'ok' ? data.message : 'Error: ' + (data.error || 'unknown'));
        } catch (e) {
            alert('Failed: ' + e.message);
        }
    });

    document.getElementById('btn-refresh-versions').addEventListener('click', loadVersions);
    loadVersions();
}
