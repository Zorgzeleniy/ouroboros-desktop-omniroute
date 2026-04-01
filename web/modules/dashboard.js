export function initDashboard({ ws, state }) {
    const page = document.createElement('div');
    page.id = 'page-dashboard';
    page.className = 'page';
    page.innerHTML = `
        <div class="page-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
            <h2>Dashboard</h2>
        </div>
        <div class="dashboard-scroll">
            <h2 id="dash-title" style="font-size:24px;font-weight:700;margin-bottom:16px">Ouroboros</h2>
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="label">Uptime</div>
                    <div class="value" id="dash-uptime">0s</div>
                </div>
                <div class="stat-card">
                    <div class="label">Workers</div>
                    <div class="value" id="dash-workers">...</div>
                    <div class="progress-bar"><div class="fill" id="dash-workers-bar" style="width:0;background:var(--accent)"></div></div>
                </div>
                <div class="stat-card">
                    <div class="label">Budget</div>
                    <div class="value" id="dash-budget">...</div>
                    <div class="progress-bar"><div class="fill" id="dash-budget-bar" style="width:0;background:var(--amber)"></div></div>
                </div>
                <div class="stat-card">
                    <div class="label">Branch</div>
                    <div class="value" id="dash-branch" style="color:var(--green)">ouroboros</div>
                </div>
            </div>
            <div class="divider"></div>
            <div class="section-title">Controls</div>
            <div class="controls-row">
                <div class="toggle-wrapper">
                    <button class="toggle" id="toggle-evo"></button>
                    <span class="toggle-label">Evolution Mode</span>
                </div>
                <div class="toggle-wrapper">
                    <button class="toggle" id="toggle-bg"></button>
                    <span class="toggle-label">Background Consciousness</span>
                </div>
            </div>
            <div class="controls-row">
                <button class="btn btn-default" id="btn-review">Force Review</button>
                <button class="btn btn-primary" id="btn-restart">Restart Agent</button>
                <button class="btn btn-danger" id="btn-panic">Panic Stop</button>
            </div>
            <div class="dashboard-runtime-status">
                <div id="dash-evolution-detail" class="dashboard-runtime-note">Evolution state will appear here.</div>
                <div id="dash-bg-detail" class="dashboard-runtime-note">Background consciousness state will appear here.</div>
            </div>
        </div>
    `;
    document.getElementById('content').appendChild(page);

    document.getElementById('toggle-evo').addEventListener('click', function() {
        this.classList.toggle('on');
        ws.send({ type: 'command', cmd: `/evolve ${this.classList.contains('on') ? 'start' : 'stop'}` });
    });
    document.getElementById('toggle-bg').addEventListener('click', function() {
        this.classList.toggle('on');
        ws.send({ type: 'command', cmd: `/bg ${this.classList.contains('on') ? 'start' : 'stop'}` });
    });
    document.getElementById('btn-review').addEventListener('click', () => ws.send({ type: 'command', cmd: '/review' }));
    document.getElementById('btn-restart').addEventListener('click', () => ws.send({ type: 'command', cmd: '/restart' }));
    document.getElementById('btn-panic').addEventListener('click', () => {
        if (confirm('Kill all workers immediately?')) {
            ws.send({ type: 'command', cmd: '/panic' });
        }
    });

    // Poll dashboard state
    async function updateDashboard(force = false) {
        if (!force && state.activePage !== 'dashboard') return;
        try {
            const resp = await fetch('/api/state', { cache: 'no-store' });
            const data = await resp.json();
            const uptime = data.uptime || 0;
            const h = Math.floor(uptime / 3600);
            const m = Math.floor((uptime % 3600) / 60);
            const s = uptime % 60;
            document.getElementById('dash-uptime').textContent =
                h ? `${h}h ${m}m ${s}s` : m ? `${m}m ${s}s` : `${s}s`;

            document.getElementById('dash-workers').textContent =
                `${data.workers_alive || 0} / ${data.workers_total || 0} active`;
            const wPct = data.workers_total > 0 ? (data.workers_alive / data.workers_total * 100) : 0;
            document.getElementById('dash-workers-bar').style.width = `${wPct}%`;

            const spent = data.spent_usd || 0;
            const limit = data.budget_limit || 10;
            document.getElementById('dash-budget').textContent = `$${spent.toFixed(2)} / $${limit.toFixed(2)}`;
            document.getElementById('dash-budget-bar').style.width = `${Math.min(100, data.budget_pct || 0)}%`;

            document.getElementById('dash-branch').textContent =
                `${data.branch || 'ouroboros'}${data.sha ? '@' + data.sha : ''}`;

            if (data.evolution_enabled) document.getElementById('toggle-evo').classList.add('on');
            else document.getElementById('toggle-evo').classList.remove('on');
            if (data.bg_consciousness_enabled) document.getElementById('toggle-bg').classList.add('on');
            else document.getElementById('toggle-bg').classList.remove('on');

            document.getElementById('dash-evolution-detail').textContent =
                data?.evolution_state?.detail || 'Evolution mode is off.';
            document.getElementById('dash-bg-detail').textContent =
                data?.bg_consciousness_state?.detail || 'Background consciousness is off.';
        } catch (error) {
            const message = error?.message ? `Dashboard unavailable: ${error.message}` : 'Dashboard unavailable.';
            document.getElementById('dash-evolution-detail').textContent = message;
            document.getElementById('dash-bg-detail').textContent = 'Waiting for /api/state recovery.';
        }
    }

    updateDashboard(true);
    setInterval(updateDashboard, 3000);
}
