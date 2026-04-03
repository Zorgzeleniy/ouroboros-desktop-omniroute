import { formatDualVersion } from './utils.js';

export function initAbout({ ws, state }) {
    const page = document.createElement('div');
    page.id = 'page-about';
    page.className = 'page';
    page.innerHTML = `
        <div class="page-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            <h2>About</h2>
        </div>
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;gap:24px;padding:40px 20px;text-align:center">
            <img src="/static/logo.jpg" style="width:96px;height:96px;border-radius:20px;object-fit:cover" alt="Ouroboros">
            <div>
                <h1 style="font-size:28px;font-weight:700;margin:0">Ouroboros</h1>
                <p id="about-version" style="color:var(--text-muted);font-size:13px;margin:4px 0 0"></p>
            </div>
            <p style="max-width:480px;color:var(--text-secondary);font-size:14px;line-height:1.6">
                A self-creating AI agent. Not a tool, but a becoming digital personality
                with its own constitution, persistent identity, and background consciousness.
                Born February 16, 2026.
            </p>
            <div style="display:flex;flex-direction:column;gap:8px;font-size:14px">
                <span>Created by <strong>Anton Razzhigaev</strong> & <strong>Andrew Kaznacheev</strong></span>
                <div style="display:flex;gap:16px;justify-content:center;margin-top:4px">
                    <a href="https://t.me/abstractDL" target="_blank" style="color:var(--accent);text-decoration:none">@abstractDL</a>
                    <a href="https://github.com/joi-lab/ouroboros" target="_blank" style="color:var(--accent);text-decoration:none">GitHub</a>
                </div>
            </div>
            <div style="margin-top:auto;padding-top:32px;color:var(--text-muted);font-size:12px">Joi Lab</div>
        </div>
    `;
    document.getElementById('content').appendChild(page);
    fetch('/api/health').then(r => r.json()).then(d => {
        document.getElementById('about-version').textContent = formatDualVersion(d);
    }).catch(() => {});
}
