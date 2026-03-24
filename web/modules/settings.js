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
                    <button class="settings-tab" data-settings-tab="models" role="tab" aria-selected="false">AI Models</button>
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
                                <p>Set up your provider keys.</p>
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

                <div class="settings-panel" data-settings-panel="models" role="tabpanel" hidden>
                    <div class="settings-card">
                        <div class="settings-card-header">
                            <div>
                                <h3>AI Models</h3>
                                <p>Choose your default models and local routing.</p>
                            </div>
                        </div>
                        <section class="settings-subsection settings-subsection-emphasis">
                            <div class="settings-subsection-header">
                                <div>
                                    <h4>Models</h4>
                                    <p>Pick a model for each lane.</p>
                                </div>
                            </div>
                            <div class="settings-note" style="margin:0 0 12px 0">
                                Search, pick from configured providers, or keep a custom model ID.
                            </div>
                            <div class="models-catalog-toolbar">
                                <div id="models-catalog-status" class="settings-note models-catalog-status">
                                    Loading model catalog...
                                </div>
                                <button class="btn btn-default models-refresh-btn" id="btn-models-refresh" type="button">Refresh catalog</button>
                            </div>
                            <div class="form-row" style="align-items:flex-end">
                                <div class="form-field">
                                    <label>Main Model</label>
                                    <div class="model-combobox" data-model-field="s-model">
                                        <input id="s-model-display" class="model-combobox-input" placeholder="Type to search or enter a custom model" autocomplete="off" style="width:320px">
                                        <input id="s-model" type="hidden">
                                        <div id="s-model-menu" class="model-combobox-menu" hidden></div>
                                    </div>
                                </div>
                                <label class="local-toggle">
                                    <input type="checkbox" id="s-local-main">
                                    <span class="local-toggle-switch" aria-hidden="true"></span>
                                    <span class="local-toggle-text">Local</span>
                                </label>
                            </div>
                            <div class="settings-note model-select-note" id="s-model-note"></div>
                            <div class="form-row" style="align-items:flex-end">
                                <div class="form-field">
                                    <label>Code Model</label>
                                    <div class="model-combobox" data-model-field="s-model-code">
                                        <input id="s-model-code-display" class="model-combobox-input" placeholder="Type to search or enter a custom model" autocomplete="off" style="width:320px">
                                        <input id="s-model-code" type="hidden">
                                        <div id="s-model-code-menu" class="model-combobox-menu" hidden></div>
                                    </div>
                                </div>
                                <label class="local-toggle">
                                    <input type="checkbox" id="s-local-code">
                                    <span class="local-toggle-switch" aria-hidden="true"></span>
                                    <span class="local-toggle-text">Local</span>
                                </label>
                            </div>
                            <div class="settings-note model-select-note" id="s-model-code-note"></div>
                            <div class="form-row" style="align-items:flex-end">
                                <div class="form-field">
                                    <label>Light Model</label>
                                    <div class="model-combobox" data-model-field="s-model-light">
                                        <input id="s-model-light-display" class="model-combobox-input" placeholder="Type to search or enter a custom model" autocomplete="off" style="width:320px">
                                        <input id="s-model-light" type="hidden">
                                        <div id="s-model-light-menu" class="model-combobox-menu" hidden></div>
                                    </div>
                                </div>
                                <label class="local-toggle">
                                    <input type="checkbox" id="s-local-light">
                                    <span class="local-toggle-switch" aria-hidden="true"></span>
                                    <span class="local-toggle-text">Local</span>
                                </label>
                            </div>
                            <div class="settings-note model-select-note" id="s-model-light-note"></div>
                            <div class="form-row" style="align-items:flex-end">
                                <div class="form-field">
                                    <label>Fallback Model</label>
                                    <div class="model-combobox" data-model-field="s-model-fallback">
                                        <input id="s-model-fallback-display" class="model-combobox-input" placeholder="Type to search or enter a custom model" autocomplete="off" style="width:320px">
                                        <input id="s-model-fallback" type="hidden">
                                        <div id="s-model-fallback-menu" class="model-combobox-menu" hidden></div>
                                    </div>
                                </div>
                                <label class="local-toggle">
                                    <input type="checkbox" id="s-local-fallback">
                                    <span class="local-toggle-switch" aria-hidden="true"></span>
                                    <span class="local-toggle-text">Local</span>
                                </label>
                            </div>
                            <div class="settings-note model-select-note" id="s-model-fallback-note"></div>
                            <div class="form-row">
                                <div class="form-field"><label>Claude Code Model</label><input id="s-claude-code-model" value="opus" placeholder="sonnet, opus, or full name" style="width:250px"></div>
                            </div>
                        </section>

                        <div class="settings-subsection-divider" aria-hidden="true"></div>

                        <section class="settings-subsection">
                            <div class="settings-subsection-header">
                                <div>
                                    <h4>Local Model Runtime</h4>
                                    <p>Run and manage your local GGUF model.</p>
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
                        </section>

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
                                <p>Set thinking depth by task type.</p>
                            </div>
                        </div>
                        <div class="settings-note" style="margin-bottom:12px">Higher effort is slower but usually more thorough.</div>
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
                                <p>Choose how pre-commit review behaves.</p>
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
                                <p>Adjust workers, budget, and timeouts.</p>
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
                                <p>Connect a repo for optional GitHub flows.</p>
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
                                <p>Small app-wide settings.</p>
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
        <div id="settings-modal" class="settings-modal" hidden>
            <div class="settings-modal-backdrop" data-settings-modal-close="backdrop"></div>
            <div class="settings-modal-card" role="dialog" aria-modal="true" aria-labelledby="settings-modal-title">
                <div class="settings-modal-title" id="settings-modal-title"></div>
                <div class="settings-modal-message" id="settings-modal-message"></div>
                <div class="settings-modal-actions">
                    <button type="button" class="btn btn-default" id="settings-modal-cancel">Cancel</button>
                    <button type="button" class="btn btn-danger" id="settings-modal-confirm">Reset All Data</button>
                </div>
            </div>
        </div>
    `;
    document.getElementById('content').appendChild(page);

    const settingsTabs = Array.from(page.querySelectorAll('[data-settings-tab]'));
    const settingsPanels = Array.from(page.querySelectorAll('[data-settings-panel]'));
    const settingsModalEl = page.querySelector('#settings-modal');
    const settingsModalTitleEl = page.querySelector('#settings-modal-title');
    const settingsModalMessageEl = page.querySelector('#settings-modal-message');
    const settingsModalCancelBtn = page.querySelector('#settings-modal-cancel');
    const settingsModalConfirmBtn = page.querySelector('#settings-modal-confirm');
    let settingsModalResolve = null;

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

    function closeSettingsModal(result) {
        settingsModalEl.hidden = true;
        const resolver = settingsModalResolve;
        settingsModalResolve = null;
        if (resolver) resolver(result);
    }

    function showSettingsModal({
        title,
        message,
        confirmLabel = 'OK',
        cancelLabel = 'Cancel',
        hideCancel = false,
        confirmClassName = 'btn btn-primary',
    }) {
        settingsModalTitleEl.textContent = title || '';
        settingsModalMessageEl.textContent = message || '';
        settingsModalConfirmBtn.textContent = confirmLabel;
        settingsModalConfirmBtn.className = confirmClassName;
        settingsModalCancelBtn.textContent = cancelLabel;
        settingsModalCancelBtn.hidden = hideCancel;
        settingsModalEl.hidden = false;
        queueMicrotask(() => {
            (hideCancel ? settingsModalConfirmBtn : settingsModalCancelBtn).focus();
        });
        return new Promise((resolve) => {
            settingsModalResolve = resolve;
        });
    }

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

    settingsModalCancelBtn.addEventListener('click', () => {
        closeSettingsModal({ confirmed: false });
    });

    settingsModalConfirmBtn.addEventListener('click', () => {
        closeSettingsModal({ confirmed: true });
    });

    settingsModalEl.addEventListener('click', (event) => {
        const target = event.target instanceof HTMLElement ? event.target : null;
        if (target?.dataset.settingsModalClose === 'backdrop') {
            closeSettingsModal({ confirmed: false });
        }
    });

    settingsModalEl.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            closeSettingsModal({ confirmed: false });
        }
        if (event.key === 'Enter' && event.target !== settingsModalCancelBtn) {
            event.preventDefault();
            closeSettingsModal({ confirmed: true });
        }
    });

    const DEFAULT_MODEL_VALUES = {
        's-model': 'anthropic/claude-opus-4.6',
        's-model-code': 'anthropic/claude-opus-4.6',
        's-model-light': 'anthropic/claude-sonnet-4.6',
        's-model-fallback': 'anthropic/claude-sonnet-4.6',
    };
    const MODEL_NOTE_IDS = {
        's-model': 's-model-note',
        's-model-code': 's-model-code-note',
        's-model-light': 's-model-light-note',
        's-model-fallback': 's-model-fallback-note',
    };
    const MODEL_DISPLAY_IDS = {
        's-model': 's-model-display',
        's-model-code': 's-model-code-display',
        's-model-light': 's-model-light-display',
        's-model-fallback': 's-model-fallback-display',
    };
    const MODEL_MENU_IDS = {
        's-model': 's-model-menu',
        's-model-code': 's-model-code-menu',
        's-model-light': 's-model-light-menu',
        's-model-fallback': 's-model-fallback-menu',
    };
    let modelCatalog = [];
    let modelCatalogByValue = new Map();
    let configuredModelProviders = [];

    function getModelCatalogEmptyLabel() {
        return 'Set a valid provider key in AI Providers to load models';
    }

    function getModelFieldElements(fieldId) {
        return {
            hiddenInput: document.getElementById(fieldId),
            displayInput: document.getElementById(MODEL_DISPLAY_IDS[fieldId]),
            menu: document.getElementById(MODEL_MENU_IDS[fieldId]),
        };
    }

    function getConfiguredProvidersLabel() {
        return configuredModelProviders.length
            ? configuredModelProviders.join(', ')
            : 'configured providers';
    }

    function getModelCatalogEntry(value) {
        return modelCatalogByValue.get(String(value || '').trim()) || null;
    }

    function findCatalogEntryFromTypedValue(value) {
        const normalized = String(value || '').trim().toLowerCase();
        if (!normalized) return null;

        const exactIdMatches = modelCatalog.filter((model) => String(model.id || '').trim().toLowerCase() === normalized);
        if (exactIdMatches.length === 1) return exactIdMatches[0];

        const exactLabelMatches = modelCatalog.filter((model) => String(model.label || '').trim().toLowerCase() === normalized);
        if (exactLabelMatches.length === 1) return exactLabelMatches[0];

        const exactNameMatches = modelCatalog.filter((model) => String(model.name || '').trim().toLowerCase() === normalized);
        if (exactNameMatches.length === 1) return exactNameMatches[0];

        return null;
    }

    function updateModelSelectNote(selectId, currentValue) {
        const note = document.getElementById(MODEL_NOTE_IDS[selectId]);
        if (!note) return;

        const value = String(currentValue || '').trim();
        const filteredCount = getFilteredModelCatalog(selectId).length;
        if (!value) {
            if (!modelCatalog.length) {
                note.textContent = getModelCatalogEmptyLabel() + '.';
            } else if (!filteredCount) {
                note.textContent = 'No models match your search.';
            } else {
                note.textContent = `Choose a model from ${getConfiguredProvidersLabel()} or leave a custom value.`;
            }
            return;
        }

        const selectedModel = getModelCatalogEntry(value);
        if (selectedModel) {
            const sourceNote = selectedModel.source && selectedModel.source !== selectedModel.provider
                ? ` via ${selectedModel.source}`
                : '';
            note.textContent = `Provider: ${selectedModel.provider}${sourceNote}. Model ID: ${selectedModel.id}`;
            return;
        }

        note.textContent = `Custom model ID will be saved as entered: ${value}`;
    }

    function getFilteredModelCatalog(fieldId) {
        const { displayInput, hiddenInput } = getModelFieldElements(fieldId);
        if (!displayInput) return modelCatalog;
        const selectedEntry = getModelCatalogEntry(hiddenInput?.value || '');
        const searchValue = String(displayInput.dataset.query || '')
            .trim()
            .toLowerCase();
        if (!searchValue) return modelCatalog;

        if (selectedEntry && displayInput.value === selectedEntry.label) {
            return modelCatalog;
        }

        return modelCatalog.filter((model) => {
            const haystack = [
                model.provider || '',
                model.name || '',
                model.id || '',
                model.label || '',
            ].join(' ').toLowerCase();
            return haystack.includes(searchValue);
        });
    }

    function renderModelMenu(fieldId, keepOpen = false) {
        const { hiddenInput, displayInput, menu } = getModelFieldElements(fieldId);
        if (!displayInput || !menu || !hiddenInput) return;

        const nextValue = String(hiddenInput.value || '').trim();
        const filteredCatalog = getFilteredModelCatalog(fieldId);
        menu.innerHTML = '';

        if (!modelCatalog.length) {
            const empty = document.createElement('div');
            empty.className = 'model-combobox-empty';
            empty.textContent = getModelCatalogEmptyLabel();
            menu.appendChild(empty);
        } else if (!filteredCatalog.length) {
            const empty = document.createElement('div');
            empty.className = 'model-combobox-empty';
            empty.textContent = 'No models match your search.';
            menu.appendChild(empty);
        }

        const groupedModels = new Map();
        for (const model of filteredCatalog) {
            const provider = model.provider || 'Other';
            if (!groupedModels.has(provider)) groupedModels.set(provider, []);
            groupedModels.get(provider).push(model);
        }

        for (const [provider, models] of groupedModels.entries()) {
            const group = document.createElement('div');
            group.className = 'model-combobox-group';

            const heading = document.createElement('div');
            heading.className = 'model-combobox-group-label';
            heading.textContent = provider;
            group.appendChild(heading);

            for (const model of models) {
                const option = document.createElement('button');
                option.type = 'button';
                option.className = 'model-combobox-option';
                option.dataset.value = model.value;
                option.innerHTML = `
                    <span class="model-combobox-option-title">${model.name || model.id}</span>
                    <span class="model-combobox-option-id">${model.id}</span>
                `;
                option.addEventListener('click', () => {
                    setModelFieldValue(fieldId, model.value);
                    closeModelMenu(fieldId);
                });
                group.appendChild(option);
            }
            menu.appendChild(group);
        }

        if (nextValue && !getModelCatalogEntry(nextValue)) {
            const custom = document.createElement('div');
            custom.className = 'model-combobox-empty';
            custom.textContent = `Custom value: ${nextValue}`;
            menu.appendChild(custom);
        }

        menu.hidden = !keepOpen;
        displayInput.setAttribute('aria-expanded', keepOpen ? 'true' : 'false');
        updateModelSelectNote(fieldId, nextValue);
    }

    function closeModelMenu(fieldId) {
        const { displayInput, menu } = getModelFieldElements(fieldId);
        if (menu) menu.hidden = true;
        if (displayInput) displayInput.setAttribute('aria-expanded', 'false');
    }

    function setModelFieldValue(fieldId, actualValue) {
        const { hiddenInput, displayInput } = getModelFieldElements(fieldId);
        if (!hiddenInput || !displayInput) return;

        const nextValue = String(actualValue || '').trim();
        const selectedModel = getModelCatalogEntry(nextValue);
        hiddenInput.value = nextValue;
        displayInput.dataset.query = '';

        if (selectedModel) {
            displayInput.value = selectedModel.label;
            displayInput.dataset.selectedValue = selectedModel.value;
        } else {
            displayInput.value = nextValue;
            displayInput.dataset.selectedValue = '';
        }

        updateModelSelectNote(fieldId, nextValue);
    }

    async function loadModelCatalog(preserveValues = true) {
        const status = document.getElementById('models-catalog-status');
        const currentValues = preserveValues ? {
            model: document.getElementById('s-model')?.value || '',
            code: document.getElementById('s-model-code')?.value || '',
            light: document.getElementById('s-model-light')?.value || '',
            fallback: document.getElementById('s-model-fallback')?.value || '',
        } : null;

        try {
            if (status) {
                status.textContent = 'Loading model catalog...';
                status.style.color = 'var(--text-secondary)';
            }
            const resp = await fetch('/api/model-catalog');
            const data = await resp.json().catch(() => ({}));
            modelCatalog = Array.isArray(data.models) ? data.models : [];
            modelCatalogByValue = new Map(modelCatalog.map((model) => [model.value, model]));
            configuredModelProviders = Array.isArray(data.configured_providers) ? data.configured_providers : [];
            if (status) {
                if (!resp.ok || data.error) {
                    status.textContent = data.error || `Failed to load model catalog (HTTP ${resp.status})`;
                    status.style.color = 'var(--amber)';
                } else if (!modelCatalog.length) {
                    status.textContent = data.configured
                        ? `No models returned by ${getConfiguredProvidersLabel()}.`
                        : getModelCatalogEmptyLabel() + '.';
                    status.style.color = 'var(--text-secondary)';
                } else {
                    status.textContent = `Loaded ${modelCatalog.length} models from ${getConfiguredProvidersLabel()}.`;
                    status.style.color = 'var(--green)';
                }
            }
        } catch (e) {
            modelCatalog = [];
            modelCatalogByValue = new Map();
            configuredModelProviders = [];
            if (status) {
                status.textContent = `Failed to load model catalog: ${e.message}`;
                status.style.color = 'var(--amber)';
            }
        }

        setModelFieldValue('s-model', currentValues?.model || DEFAULT_MODEL_VALUES['s-model']);
        setModelFieldValue('s-model-code', currentValues?.code || DEFAULT_MODEL_VALUES['s-model-code']);
        setModelFieldValue('s-model-light', currentValues?.light || DEFAULT_MODEL_VALUES['s-model-light']);
        setModelFieldValue('s-model-fallback', currentValues?.fallback || DEFAULT_MODEL_VALUES['s-model-fallback']);

        Object.keys(DEFAULT_MODEL_VALUES).forEach((fieldId) => {
            renderModelMenu(fieldId, false);
        });
    }

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
        setModelFieldValue('s-model', s.OUROBOROS_MODEL || DEFAULT_MODEL_VALUES['s-model']);
        setModelFieldValue('s-model-code', s.OUROBOROS_MODEL_CODE || DEFAULT_MODEL_VALUES['s-model-code']);
        setModelFieldValue('s-model-light', s.OUROBOROS_MODEL_LIGHT || DEFAULT_MODEL_VALUES['s-model-light']);
        setModelFieldValue('s-model-fallback', s.OUROBOROS_MODEL_FALLBACK || DEFAULT_MODEL_VALUES['s-model-fallback']);
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
        await loadModelCatalog();
    }

    loadSettings().catch(() => {});

    Object.keys(DEFAULT_MODEL_VALUES).forEach((fieldId) => {
        const { hiddenInput, displayInput } = getModelFieldElements(fieldId);
        if (!hiddenInput || !displayInput) return;

        displayInput.setAttribute('role', 'combobox');
        displayInput.setAttribute('aria-expanded', 'false');
        displayInput.setAttribute('aria-autocomplete', 'list');
        displayInput.setAttribute('aria-controls', MODEL_MENU_IDS[fieldId]);

        displayInput.addEventListener('focus', () => {
            renderModelMenu(fieldId, true);
        });

        displayInput.addEventListener('input', () => {
            const typedValue = displayInput.value.trim();
            displayInput.dataset.query = typedValue;
            const matchedModel = findCatalogEntryFromTypedValue(typedValue);
            hiddenInput.value = matchedModel ? matchedModel.value : typedValue;
            renderModelMenu(fieldId, true);
        });

        displayInput.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                closeModelMenu(fieldId);
            }
        });

        displayInput.addEventListener('blur', () => {
            const typedValue = displayInput.value.trim();
            const matchedModel = findCatalogEntryFromTypedValue(typedValue);
            if (matchedModel) {
                setModelFieldValue(fieldId, matchedModel.value);
            } else {
                hiddenInput.value = typedValue;
                updateModelSelectNote(fieldId, typedValue);
            }
            window.setTimeout(() => closeModelMenu(fieldId), 120);
        });
    });

    document.addEventListener('click', (event) => {
        if (!page.contains(event.target)) return;
        Object.keys(DEFAULT_MODEL_VALUES).forEach((fieldId) => {
            const { displayInput, menu } = getModelFieldElements(fieldId);
            if (!displayInput || !menu) return;
            const clickedInside = displayInput.contains(event.target) || menu.contains(event.target);
            if (!clickedInside) closeModelMenu(fieldId);
        });
    });

    document.getElementById('btn-models-refresh')?.addEventListener('click', () => {
        loadModelCatalog(true).catch(() => {});
    });

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
                : (data.info || 'Settings saved. Budget changes take effect immediately.');
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
        const result = await showSettingsModal({
            title: 'Reset All Data?',
            message: 'This will delete all runtime data (state, memory, logs, settings) and restart.\nThe repo (agent code) will be preserved.\nYou will need to re-enter your API key.\n\nContinue?',
            confirmLabel: 'Reset All Data',
            cancelLabel: 'Cancel',
            confirmClassName: 'btn btn-danger',
        });
        if (!result?.confirmed) return;
        try {
            const res = await fetch('/api/reset', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'ok') {
                await showSettingsModal({
                    title: 'Reset Complete',
                    message: 'Deleted: ' + (data.deleted.join(', ') || 'nothing') + '\nReloading the app state...',
                    confirmLabel: 'OK',
                    hideCancel: true,
                    confirmClassName: 'btn btn-primary',
                });
                window.location.reload();
            } else {
                await showSettingsModal({
                    title: 'Reset Failed',
                    message: 'Error: ' + (data.error || 'unknown'),
                    confirmLabel: 'OK',
                    hideCancel: true,
                    confirmClassName: 'btn btn-primary',
                });
            }
        } catch (e) {
            await showSettingsModal({
                title: 'Reset Failed',
                message: 'Reset failed: ' + e.message,
                confirmLabel: 'OK',
                hideCancel: true,
                confirmClassName: 'btn btn-primary',
            });
        }
    }

    page.querySelectorAll('[data-settings-save]').forEach((button) => {
        button.addEventListener('click', saveSettings);
    });

    page.querySelectorAll('[data-settings-reset]').forEach((button) => {
        button.addEventListener('click', resetAllData);
    });

}
