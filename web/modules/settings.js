export function initSettings({ ws, state }) {
    function renderSecretInput(id, placeholder = '') {
        return `
            <div class="secret-input-wrap">
                <input id="${id}" type="password" placeholder="${placeholder}">
                <button class="secret-toggle-btn" type="button" data-secret-toggle data-target="${id}" aria-label="Show value" aria-pressed="false">
                    <svg class="secret-toggle-icon secret-toggle-icon-show" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z"></path>
                        <circle cx="12" cy="12" r="3"></circle>
                    </svg>
                    <svg class="secret-toggle-icon secret-toggle-icon-hide" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path d="M3 3l18 18"></path>
                        <path d="M10.6 10.7a3 3 0 0 0 4.2 4.2"></path>
                        <path d="M9.4 5.2A10.7 10.7 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3 3.7"></path>
                        <path d="M6.6 6.7A17.3 17.3 0 0 0 2 12s3.5 7 10 7a10.8 10.8 0 0 0 5.4-1.5"></path>
                    </svg>
                </button>
            </div>
        `;
    }

    const page = document.createElement('div');
    page.id = 'page-settings';
    page.className = 'page';
    page.innerHTML = `
        <div class="page-header">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2"><circle cx="12" cy="12" r="3"/></svg>
            <h2>Settings</h2>
        </div>
        <div class="settings-scroll">
            <div class="settings-shell">
                <div class="settings-tabbar" role="tablist" aria-label="Settings sections">
                    <button class="settings-tab active" data-settings-tab="api-keys" role="tab" aria-selected="true">AI Providers</button>
                    <button class="settings-tab" data-settings-tab="local-model" role="tab" aria-selected="false">Local Model</button>
                    <button class="settings-tab" data-settings-tab="models" role="tab" aria-selected="false">Models</button>
                    <button class="settings-tab" data-settings-tab="reasoning-effort" role="tab" aria-selected="false">Reasoning Effort</button>
                    <button class="settings-tab" data-settings-tab="commit-review" role="tab" aria-selected="false">Commit Review</button>
                    <button class="settings-tab" data-settings-tab="runtime" role="tab" aria-selected="false">Runtime</button>
                    <button class="settings-tab" data-settings-tab="github" role="tab" aria-selected="false">GitHub (optional)</button>
                    <button class="settings-tab" data-settings-tab="general" role="tab" aria-selected="false">General</button>
                </div>

                <div class="settings-panel active" data-settings-panel="api-keys" role="tabpanel">
                    <div class="settings-card">
                        <div class="settings-card-header">
                            <div>
                                <h3>AI Providers</h3>
                                <p>Configure official and compatible providers independently, with separate backend slots for each.</p>
                            </div>
                        </div>
                        <div class="provider-list">
                            <section class="provider-card expanded" data-provider-card>
                                <button class="provider-header" type="button" data-provider-toggle aria-expanded="true">
                                    <span class="provider-title-wrap">
                                        <span class="provider-logo-chip"><img class="provider-logo-image" src="/static/providers/cloudru.svg" alt="Cloud.ru"></span>
                                        <span class="provider-title">Cloud.ru Foundation Models</span>
                                    </span>
                                    <span class="provider-chevron">⌃</span>
                                </button>
                                <div class="provider-body">
                                    <div class="form-row">
                                        <div class="form-field provider-field-wide">
                                            <label>API Key</label>
                                            ${renderSecretInput('s-cloudru-key', 'cloudru-api-key')}
                                            <div class="settings-note">Uses the default Cloud.ru Foundation Models OpenAI-compatible endpoint.</div>
                                        </div>
                                    </div>
                                </div>
                            </section>

                            <section class="provider-card" data-provider-card>
                                <button class="provider-header" type="button" data-provider-toggle aria-expanded="false">
                                    <span class="provider-title-wrap">
                                        <span class="provider-badge">◎</span>
                                        <span class="provider-title">OpenAI</span>
                                    </span>
                                    <span class="provider-chevron">⌄</span>
                                </button>
                                <div class="provider-body" hidden>
                                    <div class="form-row">
                                        <div class="form-field provider-field-wide">
                                            <label>API Key</label>
                                            ${renderSecretInput('s-openai-official', 'sk-proj-...')}
                                            <div class="settings-note">Uses the default OpenAI endpoint. Base URL is fixed and not editable here.</div>
                                        </div>
                                    </div>
                                </div>
                            </section>

                            <section class="provider-card" data-provider-card>
                                <button class="provider-header" type="button" data-provider-toggle aria-expanded="false">
                                    <span class="provider-title-wrap">
                                        <span class="provider-badge">&lt;/&gt;</span>
                                        <span class="provider-title">OpenAI Compatible</span>
                                    </span>
                                    <span class="provider-chevron">⌄</span>
                                </button>
                                <div class="provider-body" hidden>
                                    <div class="form-row">
                                        <div class="form-field provider-field-wide">
                                            <label>API Key</label>
                                            ${renderSecretInput('s-openai-compatible-key', 'api-key-for-compatible-endpoint')}
                                        </div>
                                    </div>
                                    <div class="form-row">
                                        <div class="form-field provider-field-wide">
                                            <label>Base URL</label>
                                            <input id="s-openai-compatible-base-url" placeholder="https://api.openai.com/v1 or compatible endpoint">
                                            <div class="settings-note">Examples: local gateways, OpenAI-compatible proxies, hosted compatible APIs.</div>
                                        </div>
                                    </div>
                                </div>
                            </section>

                            <section class="provider-card" data-provider-card>
                                <button class="provider-header" type="button" data-provider-toggle aria-expanded="false">
                                    <span class="provider-title-wrap">
                                        <span class="provider-logo-chip"><img class="provider-logo-image" src="/static/providers/anthropic.svg" alt="Anthropic"></span>
                                        <span class="provider-title">Anthropic</span>
                                    </span>
                                    <span class="provider-chevron">⌄</span>
                                </button>
                                <div class="provider-body" hidden>
                                    <div class="form-row">
                                        <div class="form-field provider-field-wide">
                                            <label>API Key</label>
                                            ${renderSecretInput('s-anthropic', 'sk-ant-...')}
                                        </div>
                                    </div>
                                </div>
                            </section>

                            <section class="provider-card" data-provider-card>
                                <button class="provider-header" type="button" data-provider-toggle aria-expanded="false">
                                    <span class="provider-title-wrap">
                                        <span class="provider-logo-chip"><img class="provider-logo-image" src="/static/providers/openrouter.svg" alt="OpenRouter"></span>
                                        <span class="provider-title">OpenRouter</span>
                                    </span>
                                    <span class="provider-chevron">⌄</span>
                                </button>
                                <div class="provider-body" hidden>
                                    <div class="form-row">
                                        <div class="form-field provider-field-wide">
                                            <label>API Key</label>
                                            ${renderSecretInput('s-openrouter', 'sk-or-...')}
                                        </div>
                                    </div>
                                </div>
                            </section>
                        </div>
                        <div class="settings-panel-actions">
                            <button class="btn btn-save" data-settings-save>Save Settings</button>
                            <button class="btn btn-danger" data-settings-reset>Reset All Data</button>
                        </div>
                        <div class="settings-status" style="display:none"></div>
                    </div>
                </div>

                <div class="settings-panel" data-settings-panel="local-model" role="tabpanel" hidden>
                    <div class="settings-card">
                        <div class="settings-card-header">
                            <div>
                                <h3>Local Model</h3>
                                <p>Configure the GGUF runtime and manage its lifecycle from this panel.</p>
                            </div>
                        </div>
                        <div class="form-row">
                            <div class="form-field"><label>Model Source</label><input id="s-local-source" placeholder="bartowski/Llama-3.3-70B-Instruct-GGUF or /path/to/model.gguf" style="width:400px"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-field"><label>GGUF Filename (for HF repos)</label><input id="s-local-filename" placeholder="Llama-3.3-70B-Instruct-Q4_K_M.gguf" style="width:400px"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-field"><label>Port</label><input id="s-local-port" type="number" value="8766" style="width:100px"></div>
                            <div class="form-field"><label>GPU Layers (-1 = all)</label><input id="s-local-gpu-layers" type="number" value="-1" style="width:100px"></div>
                            <div class="form-field"><label>Context Length</label><input id="s-local-ctx" type="number" value="16384" style="width:120px" placeholder="16384"></div>
                            <div class="form-field"><label>Chat Format</label><input id="s-local-chat-format" value="" placeholder="auto-detect" style="width:200px"></div>
                        </div>
                        <div class="form-row settings-inline-actions">
                            <button class="btn btn-primary" id="btn-local-start">Start</button>
                            <button class="btn btn-primary" id="btn-local-stop" style="opacity:0.5">Stop</button>
                            <button class="btn btn-primary" id="btn-local-test" style="opacity:0.5">Test Tool Calling</button>
                        </div>
                        <div id="local-model-status" class="settings-note">Status: Offline</div>
                        <div id="local-model-test-result" style="margin-top:4px;font-size:12px;color:var(--text-muted);display:none"></div>
                        <div class="settings-panel-actions">
                            <button class="btn btn-save" data-settings-save>Save Settings</button>
                            <button class="btn btn-danger" data-settings-reset>Reset All Data</button>
                        </div>
                        <div class="settings-status" style="display:none"></div>
                    </div>
                </div>

                <div class="settings-panel" data-settings-panel="models" role="tabpanel" hidden>
                    <div class="settings-card">
                        <div class="settings-card-header">
                            <div>
                                <h3>Models</h3>
                                <p>Choose default model lanes and decide which of them should route through your local runtime.</p>
                            </div>
                        </div>
                        <div class="settings-note" style="margin:0 0 12px 0">
                            These fields are cloud model IDs. Enable <code>Local</code> to route that lane through the GGUF server configured above.
                        </div>
                        <div class="form-row" style="align-items:flex-end">
                            <div class="form-field"><label>Main Model</label><input id="s-model" value="anthropic/claude-opus-4.6" style="width:250px"></div>
                            <label class="local-toggle">
                                <input type="checkbox" id="s-local-main">
                                <span class="local-toggle-switch" aria-hidden="true"></span>
                                <span class="local-toggle-text">Local</span>
                            </label>
                        </div>
                        <div class="form-row" style="align-items:flex-end">
                            <div class="form-field"><label>Code Model</label><input id="s-model-code" value="anthropic/claude-opus-4.6" style="width:250px"></div>
                            <label class="local-toggle">
                                <input type="checkbox" id="s-local-code">
                                <span class="local-toggle-switch" aria-hidden="true"></span>
                                <span class="local-toggle-text">Local</span>
                            </label>
                        </div>
                        <div class="form-row" style="align-items:flex-end">
                            <div class="form-field"><label>Light Model</label><input id="s-model-light" value="anthropic/claude-sonnet-4.6" style="width:250px"></div>
                            <label class="local-toggle">
                                <input type="checkbox" id="s-local-light">
                                <span class="local-toggle-switch" aria-hidden="true"></span>
                                <span class="local-toggle-text">Local</span>
                            </label>
                        </div>
                        <div class="form-row" style="align-items:flex-end">
                            <div class="form-field"><label>Fallback Model</label><input id="s-model-fallback" value="anthropic/claude-sonnet-4.6" style="width:250px"></div>
                            <label class="local-toggle">
                                <input type="checkbox" id="s-local-fallback">
                                <span class="local-toggle-switch" aria-hidden="true"></span>
                                <span class="local-toggle-text">Local</span>
                            </label>
                        </div>
                        <div class="form-row">
                            <div class="form-field"><label>Claude Code Model</label><input id="s-claude-code-model" value="opus" placeholder="sonnet, opus, or full name" style="width:250px"></div>
                        </div>
                        <div class="settings-panel-actions">
                            <button class="btn btn-save" data-settings-save>Save Settings</button>
                            <button class="btn btn-danger" data-settings-reset>Reset All Data</button>
                        </div>
                        <div class="settings-status" style="display:none"></div>
                    </div>
                </div>

                <div class="settings-panel" data-settings-panel="reasoning-effort" role="tabpanel" hidden>
                    <div class="settings-card">
                        <div class="settings-card-header">
                            <div>
                                <h3>Reasoning Effort</h3>
                                <p>Control how much thinking budget each task lane gets before it responds.</p>
                            </div>
                        </div>
                        <div class="settings-note" style="margin-bottom:12px">Per-task-type reasoning effort. Controls how deeply the model thinks before responding.</div>
                        <div class="form-row">
                            <div class="form-field">
                                <label>Task / Chat</label>
                                <select id="s-effort-task" style="width:120px">
                                    <option value="none">none</option>
                                    <option value="low">low</option>
                                    <option value="medium" selected>medium</option>
                                    <option value="high">high</option>
                                </select>
                            </div>
                            <div class="form-field">
                                <label>Evolution</label>
                                <select id="s-effort-evolution" style="width:120px">
                                    <option value="none">none</option>
                                    <option value="low">low</option>
                                    <option value="medium">medium</option>
                                    <option value="high" selected>high</option>
                                </select>
                            </div>
                            <div class="form-field">
                                <label>Review</label>
                                <select id="s-effort-review" style="width:120px">
                                    <option value="none">none</option>
                                    <option value="low">low</option>
                                    <option value="medium" selected>medium</option>
                                    <option value="high">high</option>
                                </select>
                            </div>
                            <div class="form-field">
                                <label>Consciousness</label>
                                <select id="s-effort-consciousness" style="width:120px">
                                    <option value="none">none</option>
                                    <option value="low" selected>low</option>
                                    <option value="medium">medium</option>
                                    <option value="high">high</option>
                                </select>
                            </div>
                        </div>
                        <div class="settings-panel-actions">
                            <button class="btn btn-save" data-settings-save>Save Settings</button>
                            <button class="btn btn-danger" data-settings-reset>Reset All Data</button>
                        </div>
                        <div class="settings-status" style="display:none"></div>
                    </div>
                </div>

                <div class="settings-panel" data-settings-panel="commit-review" role="tabpanel" hidden>
                    <div class="settings-card">
                        <div class="settings-card-header">
                            <div>
                                <h3>Commit Review</h3>
                                <p>Set the review quorum and decide whether findings are advisory or blocking.</p>
                            </div>
                        </div>
                        <div class="form-row">
                            <div class="form-field" style="flex:1">
                                <label>Pre-commit Review Models</label>
                                <input id="s-review-models" placeholder="model1,model2,model3" style="width:100%">
                                <div class="settings-note">Comma-separated OpenRouter model IDs used for pre-commit review. Minimum 2 required for quorum.</div>
                            </div>
                        </div>
                        <div class="form-row">
                            <div class="form-field">
                                <label>Review Enforcement</label>
                                <select id="s-review-enforcement" style="width:160px">
                                    <option value="advisory">Advisory</option>
                                    <option value="blocking">Blocking</option>
                                </select>
                                <div class="settings-note">Review always runs. Advisory surfaces warnings but allows commit; Blocking preserves the current hard gate.</div>
                            </div>
                        </div>
                        <div class="settings-panel-actions">
                            <button class="btn btn-save" data-settings-save>Save Settings</button>
                            <button class="btn btn-danger" data-settings-reset>Reset All Data</button>
                        </div>
                        <div class="settings-status" style="display:none"></div>
                    </div>
                </div>

                <div class="settings-panel" data-settings-panel="runtime" role="tabpanel" hidden>
                    <div class="settings-card">
                        <div class="settings-card-header">
                            <div>
                                <h3>Runtime</h3>
                                <p>Tune workers, budgets, and timeout behavior without scrolling through the entire page.</p>
                            </div>
                        </div>
                        <div class="form-row">
                            <div class="form-field"><label>Max Workers</label><input id="s-workers" type="number" min="1" max="10" value="5" style="width:100px"></div>
                            <div class="form-field"><label>Total Budget ($)</label><input id="s-budget" type="number" min="1" value="10" style="width:120px"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-field"><label>Soft Timeout (s)</label><input id="s-soft-timeout" type="number" value="600" style="width:120px"></div>
                            <div class="form-field"><label>Hard Timeout (s)</label><input id="s-hard-timeout" type="number" value="1800" style="width:120px"></div>
                        </div>
                        <div class="form-row">
                            <div class="form-field"><label>Tool Timeout (s)</label><input id="s-tool-timeout" type="number" value="120" style="width:120px"></div>
                        </div>
                        <div class="settings-panel-actions">
                            <button class="btn btn-save" data-settings-save>Save Settings</button>
                            <button class="btn btn-danger" data-settings-reset>Reset All Data</button>
                        </div>
                        <div class="settings-status" style="display:none"></div>
                    </div>
                </div>

                <div class="settings-panel" data-settings-panel="github" role="tabpanel" hidden>
                    <div class="settings-card">
                        <div class="settings-card-header">
                            <div>
                                <h3>GitHub (optional)</h3>
                                <p>Add repository context for optional GitHub-powered flows without cluttering the core runtime settings.</p>
                            </div>
                        </div>
                        <div class="form-row"><div class="form-field"><label>GitHub Token</label>${renderSecretInput('s-gh-token', 'ghp_...')}</div></div>
                        <div class="form-row"><div class="form-field"><label>GitHub Repo</label><input id="s-gh-repo" placeholder="owner/repo-name"></div></div>
                        <div class="settings-panel-actions">
                            <button class="btn btn-save" data-settings-save>Save Settings</button>
                            <button class="btn btn-danger" data-settings-reset>Reset All Data</button>
                        </div>
                        <div class="settings-status" style="display:none"></div>
                    </div>
                </div>

                <div class="settings-panel" data-settings-panel="general" role="tabpanel" hidden>
                    <div class="settings-card">
                        <div class="settings-card-header">
                            <div>
                                <h3>General</h3>
                                <p>Shared runtime controls that do not belong to a model provider.</p>
                            </div>
                        </div>
                        <div class="form-row">
                            <div class="form-field provider-field-wide">
                                <label>Network Password (optional)</label>
                                ${renderSecretInput('s-network-password', 'Set only if you want auth for remote access')}
                                <div class="settings-note">Localhost requests bypass this password. Non-localhost access requires it only when you set it.</div>
                            </div>
                        </div>
                        <div class="settings-panel-actions">
                            <button class="btn btn-save" data-settings-save>Save Settings</button>
                            <button class="btn btn-danger" data-settings-reset>Reset All Data</button>
                        </div>
                        <div class="settings-status" style="display:none"></div>
                    </div>
                </div>
            </div>
        </div>
    `;
    document.getElementById('content').appendChild(page);

    const settingsTabs = Array.from(page.querySelectorAll('[data-settings-tab]'));
    const settingsPanels = Array.from(page.querySelectorAll('[data-settings-panel]'));

    function setActiveSettingsTab(tabId) {
        settingsTabs.forEach((tab) => {
            const active = tab.dataset.settingsTab === tabId;
            tab.classList.toggle('active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        settingsPanels.forEach((panel) => {
            const active = panel.dataset.settingsPanel === tabId;
            panel.classList.toggle('active', active);
            panel.hidden = !active;
        });
    }

    settingsTabs.forEach((tab) => {
        tab.addEventListener('click', () => setActiveSettingsTab(tab.dataset.settingsTab));
    });

    const secretInputIds = ['s-openrouter', 's-openai-official', 's-openai-compatible-key', 's-cloudru-key', 's-anthropic', 's-network-password', 's-gh-token'];
    secretInputIds.forEach((id) => {
        const input = document.getElementById(id);
        input.addEventListener('focus', () => {
            if (input.value.includes('...')) input.value = '';
        });
    });

    page.querySelectorAll('[data-secret-toggle]').forEach((button) => {
        button.addEventListener('click', () => {
            const targetId = button.dataset.target;
            const input = document.getElementById(targetId);
            if (!input) return;
            const show = input.type === 'password';
            input.type = show ? 'text' : 'password';
            button.setAttribute('aria-pressed', show ? 'true' : 'false');
            button.setAttribute('aria-label', show ? 'Hide value' : 'Show value');
        });
    });

    page.querySelectorAll('[data-provider-toggle]').forEach((button) => {
        button.addEventListener('click', () => {
            const card = button.closest('[data-provider-card]');
            const body = card.querySelector('.provider-body');
            const expanded = button.getAttribute('aria-expanded') === 'true';
            button.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            card.classList.toggle('expanded', !expanded);
            body.hidden = expanded;
            const chevron = button.querySelector('.provider-chevron');
            if (chevron) chevron.textContent = expanded ? '⌄' : '⌃';
        });
    });

    function applySettings(s) {
        if (s.OPENROUTER_API_KEY) document.getElementById('s-openrouter').value = s.OPENROUTER_API_KEY;
        const legacyCompatibleBaseUrl = (s.OPENAI_BASE_URL || '').trim();
        const hasDedicatedCompatibleSlot = Boolean(
            (s.OPENAI_COMPATIBLE_API_KEY || '').trim() || (s.OPENAI_COMPATIBLE_BASE_URL || '').trim()
        );
        document.getElementById('s-openai-official').value = hasDedicatedCompatibleSlot
            ? (s.OPENAI_API_KEY || '')
            : (legacyCompatibleBaseUrl ? '' : (s.OPENAI_API_KEY || ''));
        document.getElementById('s-openai-compatible-key').value = hasDedicatedCompatibleSlot
            ? (s.OPENAI_COMPATIBLE_API_KEY || '')
            : (legacyCompatibleBaseUrl ? (s.OPENAI_API_KEY || '') : '');
        document.getElementById('s-openai-compatible-base-url').value = hasDedicatedCompatibleSlot
            ? (s.OPENAI_COMPATIBLE_BASE_URL || '')
            : legacyCompatibleBaseUrl;
        if (s.CLOUDRU_FOUNDATION_MODELS_API_KEY) document.getElementById('s-cloudru-key').value = s.CLOUDRU_FOUNDATION_MODELS_API_KEY;
        if (s.ANTHROPIC_API_KEY) document.getElementById('s-anthropic').value = s.ANTHROPIC_API_KEY;
        if (s.OUROBOROS_NETWORK_PASSWORD) document.getElementById('s-network-password').value = s.OUROBOROS_NETWORK_PASSWORD;
        if (s.OUROBOROS_MODEL) document.getElementById('s-model').value = s.OUROBOROS_MODEL;
        if (s.OUROBOROS_MODEL_CODE) document.getElementById('s-model-code').value = s.OUROBOROS_MODEL_CODE;
        if (s.OUROBOROS_MODEL_LIGHT) document.getElementById('s-model-light').value = s.OUROBOROS_MODEL_LIGHT;
        if (s.OUROBOROS_MODEL_FALLBACK) document.getElementById('s-model-fallback').value = s.OUROBOROS_MODEL_FALLBACK;
        if (s.CLAUDE_CODE_MODEL) document.getElementById('s-claude-code-model').value = s.CLAUDE_CODE_MODEL;
        const effortTask = s.OUROBOROS_EFFORT_TASK || s.OUROBOROS_INITIAL_REASONING_EFFORT || 'medium';
        document.getElementById('s-effort-task').value = effortTask;
        document.getElementById('s-effort-evolution').value = s.OUROBOROS_EFFORT_EVOLUTION || 'high';
        document.getElementById('s-effort-review').value = s.OUROBOROS_EFFORT_REVIEW || 'medium';
        document.getElementById('s-effort-consciousness').value = s.OUROBOROS_EFFORT_CONSCIOUSNESS || 'low';
        if (s.OUROBOROS_REVIEW_MODELS) document.getElementById('s-review-models').value = s.OUROBOROS_REVIEW_MODELS;
        document.getElementById('s-review-enforcement').value = s.OUROBOROS_REVIEW_ENFORCEMENT || 'advisory';
        if (s.OUROBOROS_MAX_WORKERS) document.getElementById('s-workers').value = s.OUROBOROS_MAX_WORKERS;
        if (s.TOTAL_BUDGET) document.getElementById('s-budget').value = s.TOTAL_BUDGET;
        if (s.OUROBOROS_SOFT_TIMEOUT_SEC) document.getElementById('s-soft-timeout').value = s.OUROBOROS_SOFT_TIMEOUT_SEC;
        if (s.OUROBOROS_HARD_TIMEOUT_SEC) document.getElementById('s-hard-timeout').value = s.OUROBOROS_HARD_TIMEOUT_SEC;
        if (s.OUROBOROS_TOOL_TIMEOUT_SEC) document.getElementById('s-tool-timeout').value = s.OUROBOROS_TOOL_TIMEOUT_SEC;
        if (s.GITHUB_TOKEN) document.getElementById('s-gh-token').value = s.GITHUB_TOKEN;
        if (s.GITHUB_REPO) document.getElementById('s-gh-repo').value = s.GITHUB_REPO;
        if (s.LOCAL_MODEL_SOURCE) document.getElementById('s-local-source').value = s.LOCAL_MODEL_SOURCE;
        if (s.LOCAL_MODEL_FILENAME) document.getElementById('s-local-filename').value = s.LOCAL_MODEL_FILENAME;
        if (s.LOCAL_MODEL_PORT) document.getElementById('s-local-port').value = s.LOCAL_MODEL_PORT;
        if (s.LOCAL_MODEL_N_GPU_LAYERS != null) document.getElementById('s-local-gpu-layers').value = s.LOCAL_MODEL_N_GPU_LAYERS;
        if (s.LOCAL_MODEL_CONTEXT_LENGTH) document.getElementById('s-local-ctx').value = s.LOCAL_MODEL_CONTEXT_LENGTH;
        if (s.LOCAL_MODEL_CHAT_FORMAT) document.getElementById('s-local-chat-format').value = s.LOCAL_MODEL_CHAT_FORMAT;
        document.getElementById('s-local-main').checked = s.USE_LOCAL_MAIN === true || s.USE_LOCAL_MAIN === 'True';
        document.getElementById('s-local-code').checked = s.USE_LOCAL_CODE === true || s.USE_LOCAL_CODE === 'True';
        document.getElementById('s-local-light').checked = s.USE_LOCAL_LIGHT === true || s.USE_LOCAL_LIGHT === 'True';
        document.getElementById('s-local-fallback').checked = s.USE_LOCAL_FALLBACK === true || s.USE_LOCAL_FALLBACK === 'True';
    }

    async function loadSettings() {
        const resp = await fetch('/api/settings');
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
        applySettings(data);
    }

    loadSettings().catch(() => {});

    let localStatusInterval = null;
    function updateLocalStatus() {
        if (state.activePage !== 'settings') return; // Don't poll if page is hidden
        fetch('/api/local-model/status').then(r => r.json()).then(d => {
            const el = document.getElementById('local-model-status');
            const isReady = d.status === 'ready';
            let text = 'Status: ' + (d.status || 'offline').charAt(0).toUpperCase() + (d.status || 'offline').slice(1);
            if (d.status === 'ready' && d.context_length) text += ` (ctx: ${d.context_length})`;
            if (d.status === 'downloading' && d.download_progress) text += ` ${Math.round(d.download_progress * 100)}%`;
            if (d.error) text += ' \u2014 ' + d.error;
            el.textContent = text;
            el.style.color = isReady ? 'var(--green)' : d.status === 'error' ? 'var(--red)' : 'var(--text-secondary)';
            document.getElementById('btn-local-stop').style.opacity = isReady ? '1' : '0.5';
            document.getElementById('btn-local-test').style.opacity = isReady ? '1' : '0.5';
            ['s-local-main', 's-local-code', 's-local-light', 's-local-fallback'].forEach(id => {
                const cb = document.getElementById(id);
                const label = cb.closest('.local-toggle');
                if (cb.checked && !isReady) {
                    label.title = 'Local server is not running \u2014 requests will fail until started';
                    label.style.color = 'var(--amber)';
                } else {
                    label.title = '';
                    label.style.color = '';
                }
            });
        }).catch(() => {});
    }
    updateLocalStatus();
    localStatusInterval = setInterval(updateLocalStatus, 3000);

    document.getElementById('btn-local-start').addEventListener('click', async () => {
        const source = document.getElementById('s-local-source').value.trim();
        if (!source) { alert('Enter a model source (HuggingFace repo ID or local path)'); return; }
        const body = {
            source,
            filename: document.getElementById('s-local-filename').value.trim(),
            port: parseInt(document.getElementById('s-local-port').value) || 8766,
            n_gpu_layers: parseInt(document.getElementById('s-local-gpu-layers').value),
            n_ctx: parseInt(document.getElementById('s-local-ctx').value) || 16384,
            chat_format: document.getElementById('s-local-chat-format').value.trim(),
        };
        try {
            const resp = await fetch('/api/local-model/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
            const data = await resp.json();
            if (data.error) alert('Error: ' + data.error);
            else updateLocalStatus();
        } catch (e) { alert('Failed: ' + e.message); }
    });

    document.getElementById('btn-local-stop').addEventListener('click', async () => {
        try {
            await fetch('/api/local-model/stop', { method: 'POST' });
            updateLocalStatus();
        } catch (e) { alert('Failed: ' + e.message); }
    });

    document.getElementById('btn-local-test').addEventListener('click', async () => {
        const el = document.getElementById('local-model-test-result');
        el.style.display = 'block';
        el.textContent = 'Running tests...';
        el.style.color = 'var(--text-muted)';
        try {
            const resp = await fetch('/api/local-model/test', { method: 'POST' });
            const r = await resp.json();
            if (r.error) { el.textContent = 'Error: ' + r.error; el.style.color = 'var(--red)'; return; }
            let lines = [];
            lines.push((r.chat_ok ? '\u2713' : '\u2717') + ' Basic chat' + (r.tokens_per_sec ? ` (${r.tokens_per_sec} tok/s)` : ''));
            lines.push((r.tool_call_ok ? '\u2713' : '\u2717') + ' Tool calling');
            if (r.details && !r.success) lines.push(r.details);
            el.textContent = lines.join('\n');
            el.style.whiteSpace = 'pre-wrap';
            el.style.color = r.success ? 'var(--green)' : 'var(--amber)';
        } catch (e) { el.textContent = 'Test failed: ' + e.message; el.style.color = 'var(--red)'; }
    });

    async function saveSettings() {
        const body = {
            OUROBOROS_MODEL: document.getElementById('s-model').value,
            OUROBOROS_MODEL_CODE: document.getElementById('s-model-code').value,
            OUROBOROS_MODEL_LIGHT: document.getElementById('s-model-light').value,
            OUROBOROS_MODEL_FALLBACK: document.getElementById('s-model-fallback').value,
            CLAUDE_CODE_MODEL: document.getElementById('s-claude-code-model').value || 'opus',
            OUROBOROS_EFFORT_TASK: document.getElementById('s-effort-task').value,
            OUROBOROS_EFFORT_EVOLUTION: document.getElementById('s-effort-evolution').value,
            OUROBOROS_EFFORT_REVIEW: document.getElementById('s-effort-review').value,
            OUROBOROS_EFFORT_CONSCIOUSNESS: document.getElementById('s-effort-consciousness').value,
            OUROBOROS_REVIEW_MODELS: document.getElementById('s-review-models').value.trim(),
            OUROBOROS_REVIEW_ENFORCEMENT: document.getElementById('s-review-enforcement').value,
            OUROBOROS_MAX_WORKERS: parseInt(document.getElementById('s-workers').value) || 5,
            TOTAL_BUDGET: parseFloat(document.getElementById('s-budget').value) || 10,
            OUROBOROS_SOFT_TIMEOUT_SEC: parseInt(document.getElementById('s-soft-timeout').value) || 600,
            OUROBOROS_HARD_TIMEOUT_SEC: parseInt(document.getElementById('s-hard-timeout').value) || 1800,
            OUROBOROS_TOOL_TIMEOUT_SEC: parseInt(document.getElementById('s-tool-timeout').value) || 120,
            GITHUB_REPO: document.getElementById('s-gh-repo').value,
            LOCAL_MODEL_SOURCE: document.getElementById('s-local-source').value,
            LOCAL_MODEL_FILENAME: document.getElementById('s-local-filename').value,
            LOCAL_MODEL_PORT: parseInt(document.getElementById('s-local-port').value) || 8766,
            LOCAL_MODEL_N_GPU_LAYERS: parseInt(document.getElementById('s-local-gpu-layers').value),
            LOCAL_MODEL_CONTEXT_LENGTH: parseInt(document.getElementById('s-local-ctx').value) || 16384,
            LOCAL_MODEL_CHAT_FORMAT: document.getElementById('s-local-chat-format').value,
            USE_LOCAL_MAIN: document.getElementById('s-local-main').checked,
            USE_LOCAL_CODE: document.getElementById('s-local-code').checked,
            USE_LOCAL_LIGHT: document.getElementById('s-local-light').checked,
            USE_LOCAL_FALLBACK: document.getElementById('s-local-fallback').checked,
            OPENAI_BASE_URL: '',
            OPENAI_COMPATIBLE_BASE_URL: document.getElementById('s-openai-compatible-base-url').value.trim(),
            CLOUDRU_FOUNDATION_MODELS_BASE_URL: 'https://foundation-models.api.cloud.ru/v1',
        };
        const orKey = document.getElementById('s-openrouter').value;
        if (orKey && !orKey.includes('...')) body.OPENROUTER_API_KEY = orKey;
        const openAiOfficialKey = document.getElementById('s-openai-official').value;
        if (openAiOfficialKey && !openAiOfficialKey.includes('...')) body.OPENAI_API_KEY = openAiOfficialKey;
        const openAiCompatibleKey = document.getElementById('s-openai-compatible-key').value;
        if (openAiCompatibleKey && !openAiCompatibleKey.includes('...')) {
            body.OPENAI_COMPATIBLE_API_KEY = openAiCompatibleKey;
        }
        const cloudruKey = document.getElementById('s-cloudru-key').value;
        if (cloudruKey && !cloudruKey.includes('...')) body.CLOUDRU_FOUNDATION_MODELS_API_KEY = cloudruKey;
        const antKey = document.getElementById('s-anthropic').value;
        if (antKey && !antKey.includes('...')) body.ANTHROPIC_API_KEY = antKey;
        const networkPassword = document.getElementById('s-network-password').value;
        if (networkPassword && !networkPassword.includes('...')) body.OUROBOROS_NETWORK_PASSWORD = networkPassword;
        const ghToken = document.getElementById('s-gh-token').value;
        if (ghToken && !ghToken.includes('...')) body.GITHUB_TOKEN = ghToken;

        try {
            const resp = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
            await loadSettings();
            const message = data.warnings && data.warnings.length
                ? ('Settings saved with warnings: ' + data.warnings.join(' | '))
                : 'Settings saved. Budget changes take effect immediately.';
            const color = data.warnings && data.warnings.length ? 'var(--amber)' : 'var(--green)';
            page.querySelectorAll('.settings-status').forEach((status) => {
                status.textContent = message;
                status.style.color = color;
                status.style.display = 'block';
            });
            setTimeout(() => {
                page.querySelectorAll('.settings-status').forEach((status) => {
                    status.style.display = 'none';
                });
            }, 4000);
        } catch (e) {
            alert('Failed to save: ' + e.message);
        }
    }

    async function resetAllData() {
        if (!confirm('This will delete all runtime data (state, memory, logs, settings) and restart.\nThe repo (agent code) will be preserved.\nYou will need to re-enter your API key.\n\nContinue?')) return;
        try {
            const res = await fetch('/api/reset', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'ok') {
                alert('Deleted: ' + (data.deleted.join(', ') || 'nothing') + '\nRestarting...');
            } else {
                alert('Error: ' + (data.error || 'unknown'));
            }
        } catch (e) {
            alert('Reset failed: ' + e.message);
        }
    }

    page.querySelectorAll('[data-settings-save]').forEach((button) => {
        button.addEventListener('click', saveSettings);
    });

    page.querySelectorAll('[data-settings-reset]').forEach((button) => {
        button.addEventListener('click', resetAllData);
    });

}
