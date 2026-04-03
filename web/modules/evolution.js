export function initEvolution({ ws, state }) {
    const page = document.createElement('div');
    page.id = 'page-evolution';
    page.className = 'page';
    page.innerHTML = `
        <div class="page-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            <h2>Evolution</h2>
            <div class="spacer"></div>
            <span id="evo-status" class="status-badge">Loading...</span>
        </div>
        <div class="evolution-container">
            <div class="evo-chart-wrap">
                <canvas id="evo-chart"></canvas>
            </div>
            <div id="evo-tags-list" class="evo-tags-list"></div>
        </div>
    `;
    document.getElementById('content').appendChild(page);

    let evoChart = null;

    const COLORS = {
        code_lines: '#60a5fa',
        bible_kb:   '#f97316',
        system_kb:  '#a78bfa',
        identity_kb:'#34d399',
        scratchpad_kb: '#fbbf24',
        memory_kb:  '#fb7185',
    };
    const LABELS = {
        code_lines: 'Code (lines)',
        bible_kb:   'BIBLE.md (KB)',
        system_kb:  'SYSTEM.md (KB)',
        identity_kb:'identity.md (KB)',
        scratchpad_kb: 'Scratchpad (KB)',
        memory_kb:  'Memory (KB)',
    };

    async function loadEvolution() {
        const badge = document.getElementById('evo-status');
        try {
            const resp = await fetch('/api/evolution-data');
            if (!resp.ok) throw new Error('API error ' + resp.status);
            const data = await resp.json();
            const points = data.points || [];
            if (points.length === 0) {
                badge.textContent = 'No data';
                badge.className = 'status-badge offline';
                return;
            }
            badge.textContent = points.length + ' tags';
            badge.className = 'status-badge online';
            renderChart(points);
            renderTagsList(points);
        } catch (err) {
            console.error('Evolution load error:', err);
            badge.textContent = 'Error';
            badge.className = 'status-badge offline';
        }
    }

    function renderChart(points) {
        const labels = points.map(p => p.tag);
        const datasets = Object.keys(COLORS).map(key => ({
            label: LABELS[key],
            data: points.map(p => p[key] ?? null),
            borderColor: COLORS[key],
            backgroundColor: COLORS[key] + '22',
            borderWidth: 2,
            pointRadius: 4,
            pointHoverRadius: 6,
            tension: 0.3,
            fill: false,
            yAxisID: key === 'code_lines' ? 'y' : 'y1',
        }));
        const ctx = document.getElementById('evo-chart').getContext('2d');
        if (evoChart) evoChart.destroy();
        evoChart = new Chart(ctx, {
            type: 'line',
            data: { labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            color: '#94a3b8',
                            usePointStyle: true,
                            pointStyle: 'circle',
                            padding: 16,
                            font: { size: 12, family: 'JetBrains Mono, monospace' },
                        },

                    },
                    tooltip: {
                        backgroundColor: '#1e293b',
                        titleColor: '#e2e8f0',
                        bodyColor: '#94a3b8',
                        borderColor: '#334155',
                        borderWidth: 1,
                        titleFont: { family: 'JetBrains Mono, monospace', size: 12 },
                        bodyFont: { family: 'JetBrains Mono, monospace', size: 11 },
                        callbacks: {
                            title: function(items) {
                                if (!items.length) return '';
                                const p = points[items[0].dataIndex];
                                return p.tag + ' (' + new Date(p.date).toLocaleDateString() + ')';
                            },
                            label: function(ctx) {
                                const val = ctx.parsed.y;
                                if (val === null || val === undefined) return null;
                                const key = Object.keys(COLORS)[ctx.datasetIndex];
                                if (key === 'code_lines') return ' ' + ctx.dataset.label + ': ' + val.toLocaleString() + ' lines';
                                return ' ' + ctx.dataset.label + ': ' + val.toFixed(1) + ' KB';
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        ticks: { color: '#64748b', font: { size: 10, family: 'JetBrains Mono, monospace' }, maxRotation: 45 },
                        grid: { color: '#1e293b' },
                    },
                    y: {
                        type: 'linear',
                        position: 'left',
                        title: { display: true, text: 'Lines of Code', color: '#60a5fa', font: { size: 11 } },
                        ticks: { color: '#60a5fa', font: { size: 10 } },
                        grid: { color: '#1e293b' },
                    },
                    y1: {
                        type: 'linear',
                        position: 'right',
                        title: { display: true, text: 'Size (KB)', color: '#94a3b8', font: { size: 11 } },
                        ticks: { color: '#94a3b8', font: { size: 10 } },
                        grid: { drawOnChartArea: false },
                    },
                },
            },
        });
    }

    function renderTagsList(points) {
        const container = document.getElementById('evo-tags-list');
        const rows = points.map(p => {
            const d = new Date(p.date);
            const dateStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
            return `<tr>
                <td><code>${p.tag}</code></td>
                <td>${dateStr}</td>
                <td>${(p.code_lines || 0).toLocaleString()}</td>
                <td>${(p.bible_kb || 0).toFixed(1)}</td>
                <td>${(p.system_kb || 0).toFixed(1)}</td>
                <td>${(p.identity_kb || 0).toFixed(1)}</td>
                <td>${(p.scratchpad_kb || 0).toFixed(1)}</td>
                <td>${(p.memory_kb || 0).toFixed(1)}</td>
            </tr>`;
        }).reverse().join('');
        container.innerHTML = `
            <table class="cost-table">
                <thead><tr>
                    <th>Tag</th><th>Date</th><th>Code Lines</th>
                    <th>BIBLE (KB)</th><th>SYSTEM (KB)</th>
                    <th>Identity (KB)</th><th>Scratchpad (KB)</th><th>Memory (KB)</th>
                </tr></thead>
                <tbody>${rows}</tbody>
            </table>
        `;
    }

    loadEvolution();
}
