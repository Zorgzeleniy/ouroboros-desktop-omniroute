export function initCosts({ ws, state }) {
    const page = document.createElement('div');
    page.id = 'page-costs';
    page.className = 'page';
    page.innerHTML = `
        <div class="page-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
            <h2>Costs</h2>
            <div class="spacer"></div>
            <button class="btn btn-default btn-sm" id="btn-refresh-costs">Refresh</button>
        </div>
        <div class="costs-scroll" style="overflow-y:auto;flex:1;padding:16px 20px">
            <div class="stat-grid" style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:24px">
                <div class="stat-card"><div class="stat-label">Total Spent</div><div class="stat-value" id="cost-total">$0.00</div></div>
                <div class="stat-card"><div class="stat-label">Total Calls</div><div class="stat-value" id="cost-calls">0</div></div>
                <div class="stat-card"><div class="stat-label">Top Model</div><div class="stat-value" id="cost-top-model" style="font-size:12px">-</div></div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
                <div>
                    <h3 style="font-size:14px;color:var(--text-secondary);margin:0 0 8px">By Model</h3>
                    <table class="cost-table" id="cost-by-model"><thead><tr><th>Model</th><th>Calls</th><th>Cost</th><th></th></tr></thead><tbody></tbody></table>
                </div>
                <div>
                    <h3 style="font-size:14px;color:var(--text-secondary);margin:0 0 8px">By API Key</h3>
                    <table class="cost-table" id="cost-by-key"><thead><tr><th>Key</th><th>Calls</th><th>Cost</th><th></th></tr></thead><tbody></tbody></table>
                </div>
                <div>
                    <h3 style="font-size:14px;color:var(--text-secondary);margin:0 0 8px">By Model Category</h3>
                    <table class="cost-table" id="cost-by-model-cat"><thead><tr><th>Category</th><th>Calls</th><th>Cost</th><th></th></tr></thead><tbody></tbody></table>
                </div>
                <div>
                    <h3 style="font-size:14px;color:var(--text-secondary);margin:0 0 8px">By Task Category</h3>
                    <table class="cost-table" id="cost-by-task-cat"><thead><tr><th>Category</th><th>Calls</th><th>Cost</th><th></th></tr></thead><tbody></tbody></table>
                </div>
            </div>
        </div>
    `;
    document.getElementById('content').appendChild(page);

    function renderBreakdownTable(tableId, data, totalCost) {
        const tbody = document.querySelector('#' + tableId + ' tbody');
        tbody.innerHTML = '';
        for (const [name, info] of Object.entries(data)) {
            const pct = totalCost > 0 ? (info.cost / totalCost * 100) : 0;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-size:12px;max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${name}">${name}</td>
                <td style="text-align:right">${info.calls}</td>
                <td style="text-align:right">$${info.cost.toFixed(3)}</td>
                <td style="width:60px"><div style="background:var(--accent);height:6px;border-radius:3px;width:${Math.min(100,pct)}%;opacity:0.7"></div></td>
            `;
            tbody.appendChild(tr);
        }
        if (Object.keys(data).length === 0) {
            const tr = document.createElement('tr');
            tr.innerHTML = '<td colspan="4" style="color:var(--text-muted);text-align:center">No data</td>';
            tbody.appendChild(tr);
        }
    }

    async function loadCosts() {
        try {
            const resp = await fetch('/api/cost-breakdown');
            const d = await resp.json();
            document.getElementById('cost-total').textContent = '$' + (d.total_cost || 0).toFixed(2);
            document.getElementById('cost-calls').textContent = d.total_calls || 0;
            const models = Object.entries(d.by_model || {});
            document.getElementById('cost-top-model').textContent = models.length > 0 ? models[0][0] : '-';
            renderBreakdownTable('cost-by-model', d.by_model || {}, d.total_cost);
            renderBreakdownTable('cost-by-key', d.by_api_key || {}, d.total_cost);
            renderBreakdownTable('cost-by-model-cat', d.by_model_category || {}, d.total_cost);
            renderBreakdownTable('cost-by-task-cat', d.by_task_category || {}, d.total_cost);
        } catch {}
    }

    document.getElementById('btn-refresh-costs').addEventListener('click', loadCosts);

    const obs = new MutationObserver(() => {
        if (page.classList.contains('active')) loadCosts();
    });
    obs.observe(page, { attributes: true, attributeFilter: ['class'] });
}
