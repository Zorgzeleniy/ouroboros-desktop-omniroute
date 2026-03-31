"""Desktop onboarding wizard helpers for the launcher."""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from ouroboros.config import SETTINGS_DEFAULTS
from ouroboros.provider_models import ANTHROPIC_DIRECT_DEFAULTS, OPENAI_DIRECT_DEFAULTS


_OPENROUTER_MODEL_DEFAULTS = {
    "main": str(SETTINGS_DEFAULTS["OUROBOROS_MODEL"]),
    "code": str(SETTINGS_DEFAULTS["OUROBOROS_MODEL_CODE"]),
    "light": str(SETTINGS_DEFAULTS["OUROBOROS_MODEL_LIGHT"]),
    "fallback": str(SETTINGS_DEFAULTS["OUROBOROS_MODEL_FALLBACK"]),
}
_OPENAI_MODEL_DEFAULTS = dict(OPENAI_DIRECT_DEFAULTS)
_ANTHROPIC_MODEL_DEFAULTS = dict(ANTHROPIC_DIRECT_DEFAULTS)
_LOCAL_PRESETS: Dict[str, Dict[str, Any]] = {
    "qwen25-7b": {
        "label": "Qwen2.5-7B Instruct Q3_K_M",
        "source": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q3_k_m.gguf",
        "context_length": 16384,
        "chat_format": "",
    },
    "qwen3-14b": {
        "label": "Qwen3-14B Instruct Q4_K_M",
        "source": "Qwen/Qwen3-14B-GGUF",
        "filename": "Qwen3-14B-Q4_K_M.gguf",
        "context_length": 16384,
        "chat_format": "",
    },
    "qwen3-32b": {
        "label": "Qwen3-32B Instruct Q4_K_M",
        "source": "Qwen/Qwen3-32B-GGUF",
        "filename": "Qwen3-32B-Q4_K_M.gguf",
        "context_length": 32768,
        "chat_format": "",
    },
}
_MODEL_SUGGESTIONS = [
    "anthropic/claude-opus-4.6",
    "anthropic/claude-sonnet-4.6",
    "anthropic::claude-opus-4-6",
    "anthropic::claude-sonnet-4-6",
    "google/gemini-3.1-pro-preview",
    "google/gemini-3-flash-preview",
    "openai/gpt-5.4",
    "openai::gpt-5.4",
    "openai::gpt-5.4-mini",
    "openai-compatible::meta-llama/compatible",
    "cloudru::giga-model",
]


def _string(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    return _string(value).lower() in {"1", "true", "yes", "on"}


def _detect_local_preset(settings: dict) -> str:
    source = _string(settings.get("LOCAL_MODEL_SOURCE"))
    filename = _string(settings.get("LOCAL_MODEL_FILENAME"))
    if not source:
        return ""
    for preset_id, preset in _LOCAL_PRESETS.items():
        if source == preset["source"] and filename == preset["filename"]:
            return preset_id
    return "custom"


def _derive_provider_profile(settings: dict) -> str:
    if _string(settings.get("OPENROUTER_API_KEY")):
        return "openrouter"
    if _string(settings.get("OPENAI_API_KEY")):
        return "openai"
    if _string(settings.get("ANTHROPIC_API_KEY")):
        return "anthropic"
    if _string(settings.get("LOCAL_MODEL_SOURCE")):
        return "local"
    return "openrouter"


def _derive_local_routing_mode(settings: dict) -> str:
    use_main = _truthy(settings.get("USE_LOCAL_MAIN"))
    use_code = _truthy(settings.get("USE_LOCAL_CODE"))
    use_light = _truthy(settings.get("USE_LOCAL_LIGHT"))
    use_fallback = _truthy(settings.get("USE_LOCAL_FALLBACK"))
    if use_main and use_code and use_light and use_fallback:
        return "all"
    if not use_main and not use_code and not use_light and use_fallback:
        return "fallback"
    return "cloud"


def _initial_models(settings: dict, provider_profile: str) -> dict:
    defaults = _OPENROUTER_MODEL_DEFAULTS
    if provider_profile == "openai":
        defaults = _OPENAI_MODEL_DEFAULTS
    elif provider_profile == "anthropic":
        defaults = _ANTHROPIC_MODEL_DEFAULTS
    return {
        "main": _string(settings.get("OUROBOROS_MODEL")) or defaults["main"],
        "code": _string(settings.get("OUROBOROS_MODEL_CODE")) or defaults["code"],
        "light": _string(settings.get("OUROBOROS_MODEL_LIGHT")) or defaults["light"],
        "fallback": _string(settings.get("OUROBOROS_MODEL_FALLBACK")) or defaults["fallback"],
    }


def build_onboarding_html(settings: dict) -> str:
    provider_profile = _derive_provider_profile(settings)
    models = _initial_models(settings, provider_profile)
    initial_state = {
        "providerProfile": provider_profile,
        "openrouterKey": _string(settings.get("OPENROUTER_API_KEY")),
        "openaiKey": _string(settings.get("OPENAI_API_KEY")),
        "anthropicKey": _string(settings.get("ANTHROPIC_API_KEY")),
        "budget": float(settings.get("TOTAL_BUDGET") or SETTINGS_DEFAULTS["TOTAL_BUDGET"]),
        "localPreset": _detect_local_preset(settings),
        "localSource": _string(settings.get("LOCAL_MODEL_SOURCE")),
        "localFilename": _string(settings.get("LOCAL_MODEL_FILENAME")),
        "localContextLength": int(settings.get("LOCAL_MODEL_CONTEXT_LENGTH") or SETTINGS_DEFAULTS["LOCAL_MODEL_CONTEXT_LENGTH"]),
        "localGpuLayers": int(settings.get("LOCAL_MODEL_N_GPU_LAYERS") if settings.get("LOCAL_MODEL_N_GPU_LAYERS") is not None else SETTINGS_DEFAULTS["LOCAL_MODEL_N_GPU_LAYERS"]),
        "localChatFormat": _string(settings.get("LOCAL_MODEL_CHAT_FORMAT")),
        "localRoutingMode": _derive_local_routing_mode(settings),
        "mainModel": models["main"],
        "codeModel": models["code"],
        "lightModel": models["light"],
        "fallbackModel": models["fallback"],
    }
    return (
        _WIZARD_HTML_TEMPLATE
        .replace("__INITIAL_STATE__", json.dumps(initial_state, ensure_ascii=True))
        .replace("__OPENROUTER_DEFAULTS__", json.dumps(_OPENROUTER_MODEL_DEFAULTS, ensure_ascii=True))
        .replace("__OPENAI_DEFAULTS__", json.dumps(_OPENAI_MODEL_DEFAULTS, ensure_ascii=True))
        .replace("__ANTHROPIC_DEFAULTS__", json.dumps(_ANTHROPIC_MODEL_DEFAULTS, ensure_ascii=True))
        .replace("__LOCAL_PRESETS__", json.dumps(_LOCAL_PRESETS, ensure_ascii=True))
        .replace("__MODEL_SUGGESTIONS__", json.dumps(_MODEL_SUGGESTIONS, ensure_ascii=True))
    )


def prepare_onboarding_settings(data: dict, current_settings: dict) -> Tuple[dict, str | None]:
    openrouter_key = _string(data.get("OPENROUTER_API_KEY"))
    openai_key = _string(data.get("OPENAI_API_KEY"))
    anthropic_key = _string(data.get("ANTHROPIC_API_KEY"))
    local_source = _string(data.get("LOCAL_MODEL_SOURCE"))
    local_filename = _string(data.get("LOCAL_MODEL_FILENAME"))
    local_chat_format = _string(data.get("LOCAL_MODEL_CHAT_FORMAT"))
    local_routing_mode = _string(data.get("LOCAL_ROUTING_MODE")) or "cloud"

    if openrouter_key and len(openrouter_key) < 10:
        return {}, "OpenRouter API key looks too short."
    if openai_key and len(openai_key) < 10:
        return {}, "OpenAI API key looks too short."
    if anthropic_key and len(anthropic_key) < 10:
        return {}, "Anthropic API key looks too short."

    has_local = bool(local_source)
    if not openrouter_key and not openai_key and not anthropic_key and not has_local:
        return {}, "Configure OpenRouter, OpenAI, Anthropic, or a local model before continuing."

    if has_local and "/" in local_source and not local_source.startswith(("/", "~")) and not local_filename:
        return {}, "Local HuggingFace sources need a GGUF filename."

    models = {
        "OUROBOROS_MODEL": _string(data.get("OUROBOROS_MODEL")),
        "OUROBOROS_MODEL_CODE": _string(data.get("OUROBOROS_MODEL_CODE")),
        "OUROBOROS_MODEL_LIGHT": _string(data.get("OUROBOROS_MODEL_LIGHT")),
        "OUROBOROS_MODEL_FALLBACK": _string(data.get("OUROBOROS_MODEL_FALLBACK")),
    }
    if not all(models.values()):
        return {}, "Confirm all four model lanes before starting Ouroboros."

    try:
        total_budget = float(data.get("TOTAL_BUDGET") or SETTINGS_DEFAULTS["TOTAL_BUDGET"])
    except (TypeError, ValueError):
        return {}, "Budget must be a number."
    if total_budget <= 0:
        return {}, "Budget must be greater than zero."

    try:
        local_context_length = int(data.get("LOCAL_MODEL_CONTEXT_LENGTH") or SETTINGS_DEFAULTS["LOCAL_MODEL_CONTEXT_LENGTH"])
        local_gpu_layers = int(data.get("LOCAL_MODEL_N_GPU_LAYERS") if data.get("LOCAL_MODEL_N_GPU_LAYERS") is not None else SETTINGS_DEFAULTS["LOCAL_MODEL_N_GPU_LAYERS"])
    except (TypeError, ValueError):
        return {}, "Local model context length and GPU layers must be integers."

    use_local = {
        "cloud": (False, False, False, False),
        "fallback": (False, False, False, True),
        "all": (True, True, True, True),
    }.get(local_routing_mode, (False, False, False, False))
    if not has_local:
        use_local = (False, False, False, False)

    prepared = dict(current_settings)
    prepared.update(models)
    prepared.update({
        "OPENROUTER_API_KEY": openrouter_key,
        "OPENAI_API_KEY": openai_key,
        "ANTHROPIC_API_KEY": anthropic_key,
        "TOTAL_BUDGET": total_budget,
        "LOCAL_MODEL_SOURCE": local_source if has_local else "",
        "LOCAL_MODEL_FILENAME": local_filename if has_local else "",
        "LOCAL_MODEL_CONTEXT_LENGTH": local_context_length,
        "LOCAL_MODEL_N_GPU_LAYERS": local_gpu_layers,
        "LOCAL_MODEL_CHAT_FORMAT": local_chat_format if has_local else "",
        "USE_LOCAL_MAIN": use_local[0],
        "USE_LOCAL_CODE": use_local[1],
        "USE_LOCAL_LIGHT": use_local[2],
        "USE_LOCAL_FALLBACK": use_local[3],
    })
    return prepared, None


_WIZARD_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Ouroboros Setup</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b0910;
      --panel: rgba(20, 18, 28, 0.92);
      --panel-2: rgba(255, 255, 255, 0.04);
      --panel-3: rgba(232, 93, 111, 0.08);
      --border: rgba(255, 255, 255, 0.10);
      --border-strong: rgba(232, 93, 111, 0.35);
      --text: #edf2f7;
      --muted: rgba(237, 242, 247, 0.62);
      --accent: #e85d6f;
      --accent-2: #fb7185;
      --green: #34d399;
      --shadow: 0 28px 64px rgba(0, 0, 0, 0.45);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      padding: 24px;
      background:
        radial-gradient(circle at top left, rgba(232, 93, 111, 0.12), transparent 35%),
        radial-gradient(circle at top right, rgba(99, 102, 241, 0.12), transparent 30%),
        var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .wizard-shell {
      max-width: 1040px;
      min-height: calc(100vh - 48px);
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 18px;
      padding: 24px;
      border: 1px solid var(--border);
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02));
      backdrop-filter: blur(18px);
      box-shadow: var(--shadow);
    }
    .wizard-header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 20px;
      align-items: start;
    }
    .wizard-title {
      font-size: 32px;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin: 0 0 8px;
    }
    .wizard-subtitle {
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
      max-width: 700px;
    }
    .wizard-badge {
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--panel-2);
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .wizard-steps {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .wizard-step {
      padding: 14px 16px;
      border-radius: 16px;
      background: var(--panel-2);
      border: 1px solid var(--border);
      min-width: 0;
    }
    .wizard-step.active {
      background: var(--panel-3);
      border-color: var(--border-strong);
      box-shadow: inset 0 0 0 1px rgba(232, 93, 111, 0.16);
    }
    .wizard-step.done {
      border-color: rgba(52, 211, 153, 0.22);
    }
    .wizard-step-index {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 26px;
      height: 26px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.08);
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 10px;
    }
    .wizard-step.active .wizard-step-index {
      background: rgba(232, 93, 111, 0.22);
      color: var(--text);
    }
    .wizard-step-title {
      font-size: 14px;
      font-weight: 600;
      margin: 0 0 4px;
    }
    .wizard-step-copy {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.45;
      margin: 0;
    }
    .wizard-content {
      flex: 1 1 auto;
      min-height: 0;
      display: flex;
      flex-direction: column;
      gap: 18px;
      padding: 22px;
      border-radius: 20px;
      border: 1px solid var(--border);
      background: var(--panel);
    }
    .step-header {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-start;
      flex-wrap: wrap;
    }
    .step-title {
      font-size: 24px;
      font-weight: 700;
      margin: 0 0 6px;
    }
    .step-copy {
      margin: 0;
      color: var(--muted);
      max-width: 760px;
      line-height: 1.55;
    }
    .step-chip-row,
    .pill-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .preset-pill,
    .mode-pill {
      border: 1px solid var(--border);
      background: rgba(255,255,255,0.03);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 999px;
      cursor: pointer;
      font: inherit;
      transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
    }
    .preset-pill:hover,
    .mode-pill:hover {
      border-color: rgba(255,255,255,0.22);
      transform: translateY(-1px);
    }
    .preset-pill.active,
    .mode-pill.active {
      background: rgba(232, 93, 111, 0.16);
      border-color: var(--border-strong);
    }
    .grid {
      display: grid;
      gap: 16px;
    }
    .grid.two {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .grid.three {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .panel-card {
      padding: 18px;
      border-radius: 18px;
      background: rgba(255,255,255,0.03);
      border: 1px solid var(--border);
      min-width: 0;
    }
    .panel-card h3 {
      margin: 0 0 8px;
      font-size: 15px;
    }
    .panel-card p {
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    .field-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    .field {
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 0;
    }
    .field-label-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
    }
    .field label {
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: rgba(237, 242, 247, 0.68);
    }
    .field-clear {
      color: rgba(237, 242, 247, 0.48);
      font-size: 11px;
      border: none;
      background: transparent;
      cursor: pointer;
      padding: 0;
    }
    .field-clear:hover { color: var(--text); }
    input, select {
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: rgba(11, 9, 16, 0.72);
      color: var(--text);
      padding: 12px 14px;
      font-size: 14px;
      outline: none;
      font-family: inherit;
      min-width: 0;
    }
    input:focus, select:focus {
      border-color: var(--border-strong);
      box-shadow: 0 0 0 3px rgba(232, 93, 111, 0.12);
    }
    .field-note,
    .inline-note {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .inline-note code {
      padding: 1px 4px;
      border-radius: 6px;
      background: rgba(255,255,255,0.08);
    }
    .summary-card {
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 18px;
      border-radius: 18px;
      background: rgba(255,255,255,0.03);
      border: 1px solid var(--border);
    }
    .summary-kv {
      display: grid;
      grid-template-columns: 180px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      font-size: 13px;
    }
    .summary-kv strong {
      color: rgba(237, 242, 247, 0.72);
      font-weight: 600;
    }
    .wizard-footer {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      flex-wrap: wrap;
      padding-top: 4px;
    }
    .footer-copy {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      max-width: 620px;
    }
    .footer-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .btn {
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 16px;
      font: inherit;
      cursor: pointer;
      transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
    }
    .btn:hover:not(:disabled) { transform: translateY(-1px); }
    .btn.secondary {
      background: rgba(255,255,255,0.03);
      color: var(--text);
    }
    .btn.primary {
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      border-color: rgba(251, 113, 133, 0.55);
      color: white;
      min-width: 170px;
      font-weight: 700;
    }
    .btn:disabled {
      opacity: 0.42;
      cursor: default;
      transform: none;
    }
    .wizard-error {
      min-height: 22px;
      color: #fca5a5;
      font-size: 13px;
    }
    .empty-state {
      padding: 18px;
      border: 1px dashed rgba(255,255,255,0.16);
      border-radius: 16px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }
    @media (max-width: 900px) {
      body { padding: 16px; }
      .wizard-shell { min-height: calc(100vh - 32px); padding: 18px; }
      .wizard-steps,
      .field-grid,
      .grid.two,
      .grid.three { grid-template-columns: 1fr; }
      .summary-kv { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div id="root"></div>
  <script>
    const INITIAL_STATE = __INITIAL_STATE__;
    const MODEL_DEFAULTS = {
      openrouter: __OPENROUTER_DEFAULTS__,
      openai: __OPENAI_DEFAULTS__,
      anthropic: __ANTHROPIC_DEFAULTS__,
      local: __OPENROUTER_DEFAULTS__,
    };
    const LOCAL_PRESETS = __LOCAL_PRESETS__;
    const MODEL_SUGGESTIONS = __MODEL_SUGGESTIONS__;
    const STEP_ORDER = ["providers", "models", "summary"];
    const STEP_META = {
      providers: {
        title: "Add your access",
        copy: "Every field on this screen is optional by itself. Fill at least one remote key or a local model source. You can paste several keys here; the next step adapts to what you entered.",
        footer: "Enter only what you already have. OpenRouter, direct provider keys, and an optional local model can coexist."
      },
      models: {
        title: "Review model lanes",
        copy: "Check the visible defaults derived from your current setup, then edit any lane you want before launch.",
        footer: "Plain openai/... or anthropic/... stays OpenRouter-style. Direct lanes use openai::... and anthropic::...."
      },
      summary: {
        title: "Review before launch",
        copy: "Check the final provider, model, and routing picture. Ouroboros will save exactly this snapshot before starting.",
        footer: "The same values remain editable later in Settings."
      }
    };
    const state = Object.assign({}, INITIAL_STATE, { currentStep: "providers", error: "", saving: false, modelsDirty: false });
    const root = document.getElementById("root");

    function trim(value) {
      return String(value || "").trim();
    }

    function escapeHtml(value) {
      return String(value || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function hasCloudProvider() {
      return trim(state.openrouterKey).length >= 10 || trim(state.openaiKey).length >= 10 || trim(state.anthropicKey).length >= 10;
    }

    function hasLocalModel() {
      return trim(state.localSource).length > 0;
    }

    function isLocalFilesystemSource(value) {
      const text = trim(value);
      return text.startsWith("/") || text.startsWith("~");
    }

    function applyPresetSelection(presetId) {
      state.localPreset = presetId;
      if (!presetId) {
        state.localSource = "";
        state.localFilename = "";
        state.localContextLength = 16384;
        state.localChatFormat = "";
        state.localRoutingMode = "cloud";
        return;
      }
      if (presetId === "custom") {
        if (!trim(state.localSource)) {
          state.localSource = "";
        }
        return;
      }
      const preset = LOCAL_PRESETS[presetId];
      if (!preset) {
        return;
      }
      state.localSource = preset.source;
      state.localFilename = preset.filename;
      state.localContextLength = preset.context_length;
      state.localChatFormat = preset.chat_format || "";
      if (activeProviderProfile() === "local") {
        state.localRoutingMode = "all";
      } else if (state.localRoutingMode === "cloud") {
        state.localRoutingMode = "fallback";
      }
    }

    function detectProviderProfile() {
      const hasOpenrouter = trim(state.openrouterKey).length >= 10;
      const hasOpenai = trim(state.openaiKey).length >= 10;
      const hasAnthropic = trim(state.anthropicKey).length >= 10;
      if (hasOpenrouter) {
        return "openrouter";
      }
      if (hasOpenai && hasAnthropic) {
        return "direct-multi";
      }
      if (hasOpenai) {
        return "openai";
      }
      if (hasAnthropic) {
        return "anthropic";
      }
      if (hasLocalModel()) {
        return "local";
      }
      return "openrouter";
    }

    function activeProviderProfile() {
      return detectProviderProfile();
    }

    function profileLabel(profile) {
      if (profile === "openai") return "OpenAI";
      if (profile === "anthropic") return "Anthropic";
      if (profile === "direct-multi") return "OpenAI + Anthropic";
      if (profile === "local") return "Local-first";
      return "OpenRouter";
    }

    function nextButtonShouldBeDisabled() {
      if (state.saving) return true;
      if (state.currentStep === "summary") return false;
      return Boolean(validateCurrentStep());
    }

    function syncCurrentStepActionState() {
      const next = document.getElementById("next-btn");
      if (next) next.disabled = nextButtonShouldBeDisabled();
    }

    function applyModelDefaults(force) {
      if (state.modelsDirty && !force) {
        return;
      }
      const profile = activeProviderProfile();
      state.providerProfile = profile;
      const defaults = MODEL_DEFAULTS[profile] || MODEL_DEFAULTS.openai || MODEL_DEFAULTS.openrouter;
      state.mainModel = defaults.main;
      state.codeModel = defaults.code;
      state.lightModel = defaults.light;
      state.fallbackModel = defaults.fallback;
      state.modelsDirty = false;
    }

    function validateProvidersStep() {
      const openrouterKey = trim(state.openrouterKey);
      const openaiKey = trim(state.openaiKey);
      const anthropicKey = trim(state.anthropicKey);
      const localSource = trim(state.localSource);
      const localFilename = trim(state.localFilename);
      if (openrouterKey && openrouterKey.length < 10) return "OpenRouter API key looks too short.";
      if (openaiKey && openaiKey.length < 10) return "OpenAI API key looks too short.";
      if (anthropicKey && anthropicKey.length < 10) return "Anthropic API key looks too short.";
      if (!openrouterKey && !openaiKey && !anthropicKey && !localSource) {
        return "Enter at least one remote key or a local model source before continuing.";
      }
      if (localSource) {
        if (localSource.includes("/") && !isLocalFilesystemSource(localSource) && !localFilename) {
          return "Local HuggingFace sources need a GGUF filename.";
        }
        if (!Number.isInteger(Number(state.localContextLength)) || Number(state.localContextLength) <= 0) {
          return "Local context length must be a positive integer.";
        }
        if (!Number.isInteger(Number(state.localGpuLayers))) {
          return "Local GPU layers must be an integer.";
        }
      }
      if (!Number.isFinite(Number(state.budget)) || Number(state.budget) <= 0) {
        return "Budget must be greater than zero.";
      }
      return "";
    }

    function validateModelsStep() {
      if (!trim(state.mainModel) || !trim(state.codeModel) || !trim(state.lightModel) || !trim(state.fallbackModel)) {
        return "Fill all four model lanes before continuing.";
      }
      return "";
    }

    function validateCurrentStep() {
      if (state.currentStep === "providers") {
        return validateProvidersStep();
      }
      if (state.currentStep === "models") {
        return validateModelsStep();
      }
      return "";
    }

    function nextStep() {
      const error = validateCurrentStep();
      state.error = error;
      if (error) {
        render();
        return;
      }
      const idx = STEP_ORDER.indexOf(state.currentStep);
      if (state.currentStep === "providers") {
        applyModelDefaults(false);
      }
      if (idx >= 0 && idx < STEP_ORDER.length - 1) {
        state.currentStep = STEP_ORDER[idx + 1];
      }
      state.error = "";
      render();
    }

    function previousStep() {
      const idx = STEP_ORDER.indexOf(state.currentStep);
      if (idx > 0) {
        state.currentStep = STEP_ORDER[idx - 1];
      }
      state.error = "";
      render();
    }

    function summaryRows() {
      const selectedProfile = activeProviderProfile();
      const rows = [
        ["Detected setup", profileLabel(selectedProfile)],
        ["Main", trim(state.mainModel)],
        ["Code", trim(state.codeModel)],
        ["Light", trim(state.lightModel)],
        ["Fallback", trim(state.fallbackModel)],
        ["Budget", `$${Number(state.budget || 0).toFixed(2)}`],
      ];
      if (trim(state.openrouterKey)) {
        rows.splice(1, 0, ["OpenRouter", "configured"]);
      }
      if (trim(state.openaiKey)) {
        rows.splice(1, 0, ["OpenAI", "configured"]);
      }
      if (trim(state.anthropicKey)) {
        rows.splice(1, 0, ["Anthropic", "configured"]);
      }
      if (hasLocalModel()) {
        const localRoute = hasLocalModel()
        ? (state.localRoutingMode === "all" ? "all lanes local" : state.localRoutingMode === "fallback" ? "fallback lane local" : "cloud lanes only")
        : "disabled";
        const localSourceLabel = hasLocalModel()
          ? `${trim(state.localSource)}${trim(state.localFilename) ? " / " + trim(state.localFilename) : ""}`
          : "not configured";
        rows.splice(1, 0,
          ["Local source", localSourceLabel],
          ["Local routing", localRoute],
        );
      }
      return rows;
    }

    function renderStepContent() {
      const meta = STEP_META[state.currentStep];
      const selectedProfile = activeProviderProfile();
      const suggestionOptions = MODEL_SUGGESTIONS.map((model) => `<option value="${escapeHtml(model)}"></option>`).join("");
      const summary = summaryRows().map(([label, value]) => `
        <div class="summary-kv">
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(value)}</span>
        </div>
      `).join("");
      const showLocalAdvanced = hasLocalModel();
      const localAdvanced = showLocalAdvanced ? `
        <div class="grid two">
          <div class="field">
            <div class="field-label-row"><label for="local-context">Context Length</label></div>
            <input id="local-context" type="number" min="2048" step="1024" value="${escapeHtml(state.localContextLength)}">
            <div class="field-note">Used when the embedded llama.cpp server starts.</div>
          </div>
          <div class="field">
            <div class="field-label-row"><label for="local-gpu-layers">GPU Layers</label></div>
            <input id="local-gpu-layers" type="number" step="1" value="${escapeHtml(state.localGpuLayers)}">
            <div class="field-note">Use <code>-1</code> on Apple Silicon for full offload when it fits.</div>
          </div>
          <div class="field" style="grid-column: 1 / -1;">
            <div class="field-label-row">
              <label for="local-chat-format">Chat Format</label>
              <button class="field-clear" data-clear="local-chat-format" type="button">Clear</button>
            </div>
            <input id="local-chat-format" value="${escapeHtml(state.localChatFormat)}" placeholder="Leave empty for auto-detect">
          </div>
        </div>
      ` : "";
      const providersStep = `
        <div class="step-header">
          <div>
            <h2 class="step-title">${escapeHtml(meta.title)}</h2>
            <p class="step-copy">${escapeHtml(meta.copy)}</p>
          </div>
        </div>
        <div class="panel-card">
          <h3>Keys first, routing second</h3>
          <p>${trim(state.openrouterKey)
            ? "OpenRouter is present, so the next step keeps router-style defaults while still saving any extra direct keys you pasted here."
            : selectedProfile === "direct-multi"
              ? "OpenAI and Anthropic are both present, so the next step keeps direct-provider lanes visible and lets you decide which lane uses which provider."
              : selectedProfile === "openai"
                ? "OpenAI is present, so the next step prefills direct openai:: lanes."
                : selectedProfile === "anthropic"
                  ? "Anthropic is present, so the next step prefills direct anthropic:: lanes."
                  : "No remote key is present yet, so local-only setup remains available below."}</p>
        </div>
        <div class="field-grid">
          <div class="field">
            <div class="field-label-row">
              <label for="openrouter-key">OpenRouter API Key</label>
              <button class="field-clear" data-clear="openrouter-key" type="button">Clear</button>
            </div>
            <input id="openrouter-key" type="password" placeholder="sk-or-v1-..." value="${escapeHtml(state.openrouterKey)}">
            <div class="field-note">Optional. Best when you want one router for Anthropic, OpenAI, Google, and more.</div>
          </div>
          <div class="field">
            <div class="field-label-row">
              <label for="openai-key">OpenAI API Key</label>
              <button class="field-clear" data-clear="openai-key" type="button">Clear</button>
            </div>
            <input id="openai-key" type="password" placeholder="sk-..." value="${escapeHtml(state.openaiKey)}">
            <div class="field-note">Optional. If this is the only remote key, the next step prefills direct <code>openai::...</code> lanes.</div>
          </div>
          <div class="field">
            <div class="field-label-row">
              <label for="anthropic-key">Anthropic API Key</label>
              <button class="field-clear" data-clear="anthropic-key" type="button">Clear</button>
            </div>
            <input id="anthropic-key" type="password" placeholder="sk-ant-..." value="${escapeHtml(state.anthropicKey)}">
            <div class="field-note">Optional. Saved for direct <code>anthropic::...</code> lanes and Claude tooling.</div>
          </div>
          <div class="field">
            <div class="field-label-row">
              <label for="budget">Budget (USD)</label>
            </div>
            <input id="budget" type="number" min="1" step="1" value="${escapeHtml(state.budget)}">
            <div class="field-note">The global task budget can still be changed later in Settings.</div>
          </div>
          <div class="field">
            <div class="field-label-row">
              <label for="local-preset">Local Model Preset</label>
              <button class="field-clear" data-clear="local-preset" type="button">Clear</button>
            </div>
            <select id="local-preset">
              <option value="" ${state.localPreset === "" ? "selected" : ""}>None</option>
              <option value="qwen25-7b" ${state.localPreset === "qwen25-7b" ? "selected" : ""}>Qwen2.5-7B Instruct Q3_K_M</option>
              <option value="qwen3-14b" ${state.localPreset === "qwen3-14b" ? "selected" : ""}>Qwen3-14B Instruct Q4_K_M</option>
              <option value="qwen3-32b" ${state.localPreset === "qwen3-32b" ? "selected" : ""}>Qwen3-32B Instruct Q4_K_M</option>
              <option value="custom" ${state.localPreset === "custom" ? "selected" : ""}>Custom source</option>
            </select>
            <div class="field-note">Optional. Choose a preset if you want a local fallback or a fully local setup.</div>
          </div>
          <div class="field">
            <div class="field-label-row"><label>Local routing</label></div>
            <div class="step-chip-row">
              <button class="mode-pill ${state.localRoutingMode === "cloud" ? "active" : ""}" data-local-mode="cloud" type="button">Cloud only</button>
              <button class="mode-pill ${state.localRoutingMode === "fallback" ? "active" : ""}" data-local-mode="fallback" type="button">Fallback local</button>
              <button class="mode-pill ${state.localRoutingMode === "all" ? "active" : ""}" data-local-mode="all" type="button">All lanes local</button>
            </div>
            <div class="field-note">Ignored unless a local model source is configured below.</div>
          </div>
          <div class="field" style="grid-column: 1 / -1;">
            <div class="field-label-row">
              <label for="local-source">Local Source</label>
              <button class="field-clear" data-clear="local-source" type="button">Clear</button>
            </div>
            <input id="local-source" placeholder="Qwen/Qwen2.5-7B-Instruct-GGUF or /absolute/path/model.gguf" value="${escapeHtml(state.localSource)}">
            <div class="field-note">Optional. Leave blank unless you want the embedded local runtime.</div>
          </div>
          <div class="field" style="grid-column: 1 / -1;">
            <div class="field-label-row">
              <label for="local-filename">GGUF Filename</label>
              <button class="field-clear" data-clear="local-filename" type="button">Clear</button>
            </div>
            <input id="local-filename" placeholder="qwen2.5-7b-instruct-q3_k_m.gguf" value="${escapeHtml(state.localFilename)}">
            <div class="field-note">Needed only for HuggingFace repo IDs. Leave empty when the source is an absolute local file path.</div>
          </div>
          ${showLocalAdvanced ? `
            <div class="field" style="grid-column: 1 / -1;">
              <h3 style="margin: 0 0 8px; font-size: 14px;">Local runtime details</h3>
              ${localAdvanced}
            </div>
          ` : ""}
        </div>
      `;
      const modelsStep = `
        <div class="step-header">
          <div>
            <h2 class="step-title">${escapeHtml(meta.title)}</h2>
            <p class="step-copy">${escapeHtml(meta.copy)}</p>
          </div>
        </div>
        <div class="panel-card">
          <h3>Current profile</h3>
          <p>${selectedProfile === "openai" ? "OpenAI-only setup detected. These defaults are explicit and official." : selectedProfile === "anthropic" ? "Anthropic-only setup detected. These defaults are explicit and official." : selectedProfile === "direct-multi" ? "OpenAI and Anthropic are both configured. These defaults start from the direct OpenAI lane values; switch any lane to anthropic::... if you want a different split." : selectedProfile === "local" ? "Local-only setup detected. Review the lane values and local routing before launch." : "OpenRouter-style routing remains active. Unprefixed provider IDs like openai/gpt-5.4 or anthropic/claude-sonnet-4.6 continue to route through OpenRouter."}</p>
        </div>
        <div class="grid two">
          <div class="field">
            <div class="field-label-row"><label for="main-model">Main Model</label></div>
            <input list="model-suggestions" id="main-model" value="${escapeHtml(state.mainModel)}">
            <div class="field-note">Primary reasoning and long-form task lane.</div>
          </div>
          <div class="field">
            <div class="field-label-row"><label for="code-model">Code Model</label></div>
            <input list="model-suggestions" id="code-model" value="${escapeHtml(state.codeModel)}">
            <div class="field-note">Coding and tool-heavy lane.</div>
          </div>
          <div class="field">
            <div class="field-label-row"><label for="light-model">Light Model</label></div>
            <input list="model-suggestions" id="light-model" value="${escapeHtml(state.lightModel)}">
            <div class="field-note">Lightweight tasks, summaries, and quick operations.</div>
          </div>
          <div class="field">
            <div class="field-label-row"><label for="fallback-model">Fallback Model</label></div>
            <input list="model-suggestions" id="fallback-model" value="${escapeHtml(state.fallbackModel)}">
            <div class="field-note">Fallback and resilience path.</div>
          </div>
        </div>
        <div class="inline-note">Direct providers use <code>openai::gpt-5.4</code> and <code>anthropic::claude-sonnet-4-6</code>. Plain <code>openai/...</code> or <code>anthropic/...</code> stays OpenRouter-style by design.</div>
        <datalist id="model-suggestions">${suggestionOptions}</datalist>
      `;
      const summaryStep = `
        <div class="step-header">
          <div>
            <h2 class="step-title">${escapeHtml(meta.title)}</h2>
            <p class="step-copy">${escapeHtml(meta.copy)}</p>
          </div>
        </div>
        <div class="summary-card">
          ${summary}
        </div>
      `;
      return {
        providers: providersStep,
        models: modelsStep,
        summary: summaryStep,
      }[state.currentStep];
    }

    function stepCards() {
      return STEP_ORDER.map((stepId, idx) => {
        const meta = STEP_META[stepId];
        const active = stepId === state.currentStep;
        const done = STEP_ORDER.indexOf(state.currentStep) > idx;
        return `
          <div class="wizard-step ${active ? "active" : ""} ${done ? "done" : ""}">
            <div class="wizard-step-index">${idx + 1}</div>
            <p class="wizard-step-title">${escapeHtml(meta.title)}</p>
            <p class="wizard-step-copy">${escapeHtml(meta.copy)}</p>
          </div>
        `;
      }).join("");
    }

    function render() {
      const meta = STEP_META[state.currentStep];
      const idx = STEP_ORDER.indexOf(state.currentStep);
      const nextLabel = state.currentStep === "summary"
        ? (state.saving ? "Saving..." : "Start Ouroboros")
        : (state.currentStep === "models" ? "Review summary" : "Continue");
      root.innerHTML = `
        <div class="wizard-shell">
          <div class="wizard-header">
            <div>
              <h1 class="wizard-title">Ouroboros</h1>
              <p class="wizard-subtitle">Desktop-first onboarding with all access options on the first step and visible model defaults before launch.</p>
            </div>
            <div class="wizard-badge">Step ${idx + 1} of ${STEP_ORDER.length}</div>
          </div>
          <div class="wizard-steps">${stepCards()}</div>
          <div class="wizard-content">
            ${renderStepContent()}
            <div class="wizard-footer">
              <div class="footer-copy">${escapeHtml(meta.footer)}</div>
              <div class="footer-actions">
                <button class="btn secondary" id="back-btn" type="button" ${idx === 0 || state.saving ? "disabled" : ""}>Back</button>
                <button class="btn primary" id="next-btn" type="button" ${nextButtonShouldBeDisabled() ? "disabled" : ""}>${escapeHtml(nextLabel)}</button>
              </div>
            </div>
            <div class="wizard-error">${escapeHtml(state.error)}</div>
          </div>
        </div>
      `;
      bindStepEvents();
    }

    function bindClearButtons() {
      root.querySelectorAll("[data-clear]").forEach((button) => {
        button.addEventListener("click", () => {
          const target = button.getAttribute("data-clear");
          if (target === "openrouter-key") state.openrouterKey = "";
          if (target === "openai-key") state.openaiKey = "";
          if (target === "anthropic-key") state.anthropicKey = "";
          if (target === "local-preset") {
            state.localPreset = "";
            state.localSource = "";
            state.localFilename = "";
            state.localRoutingMode = "cloud";
          }
          if (target === "local-source") state.localSource = "";
          if (target === "local-filename") state.localFilename = "";
          if (target === "local-chat-format") state.localChatFormat = "";
          state.error = "";
          render();
        });
      });
    }

    function bindProviderStep() {
      const openrouterInput = document.getElementById("openrouter-key");
      const openaiInput = document.getElementById("openai-key");
      const anthropicInput = document.getElementById("anthropic-key");
      const localPreset = document.getElementById("local-preset");
      const localSource = document.getElementById("local-source");
      const localFilename = document.getElementById("local-filename");
      const localContext = document.getElementById("local-context");
      const localGpuLayers = document.getElementById("local-gpu-layers");
      const localChatFormat = document.getElementById("local-chat-format");
      const budget = document.getElementById("budget");
      if (openrouterInput) openrouterInput.addEventListener("input", () => { state.openrouterKey = openrouterInput.value; state.error = ""; syncCurrentStepActionState(); });
      if (openaiInput) openaiInput.addEventListener("input", () => { state.openaiKey = openaiInput.value; state.error = ""; syncCurrentStepActionState(); });
      if (anthropicInput) anthropicInput.addEventListener("input", () => { state.anthropicKey = anthropicInput.value; state.error = ""; syncCurrentStepActionState(); });
      if (localPreset) localPreset.addEventListener("change", () => { applyPresetSelection(localPreset.value); state.error = ""; render(); });
      if (localSource) localSource.addEventListener("input", () => { state.localSource = localSource.value; state.localPreset = state.localPreset || "custom"; state.error = ""; syncCurrentStepActionState(); });
      if (localFilename) localFilename.addEventListener("input", () => { state.localFilename = localFilename.value; state.localPreset = state.localPreset || "custom"; state.error = ""; syncCurrentStepActionState(); });
      if (localContext) localContext.addEventListener("input", () => { state.localContextLength = localContext.value; state.error = ""; syncCurrentStepActionState(); });
      if (localGpuLayers) localGpuLayers.addEventListener("input", () => { state.localGpuLayers = localGpuLayers.value; state.error = ""; syncCurrentStepActionState(); });
      if (localChatFormat) localChatFormat.addEventListener("input", () => { state.localChatFormat = localChatFormat.value; state.error = ""; syncCurrentStepActionState(); });
      if (budget) budget.addEventListener("input", () => { state.budget = budget.value; state.error = ""; syncCurrentStepActionState(); });
      root.querySelectorAll("[data-local-mode]").forEach((button) => {
        button.addEventListener("click", () => {
          state.localRoutingMode = button.getAttribute("data-local-mode");
          state.error = "";
          render();
        });
      });
      syncCurrentStepActionState();
    }

    function bindModelsStep() {
      const map = {
        "main-model": "mainModel",
        "code-model": "codeModel",
        "light-model": "lightModel",
        "fallback-model": "fallbackModel",
      };
      Object.entries(map).forEach(([id, key]) => {
        const input = document.getElementById(id);
        input.addEventListener("input", () => {
          state[key] = input.value;
          state.modelsDirty = true;
          state.error = "";
          syncCurrentStepActionState();
        });
      });
      syncCurrentStepActionState();
    }

    async function saveWizard() {
      const providersError = validateProvidersStep();
      const modelsError = validateModelsStep();
      const selectedProfile = activeProviderProfile();
      state.error = providersError || modelsError;
      if (state.error) {
        render();
        return;
      }
      state.saving = true;
      state.error = "";
      render();
      const payload = {
        OPENROUTER_API_KEY: trim(state.openrouterKey),
        OPENAI_API_KEY: trim(state.openaiKey),
        ANTHROPIC_API_KEY: trim(state.anthropicKey),
        TOTAL_BUDGET: Number(state.budget || 0),
        LOCAL_MODEL_SOURCE: trim(state.localSource),
        LOCAL_MODEL_FILENAME: trim(state.localFilename),
        LOCAL_MODEL_CONTEXT_LENGTH: Number(state.localContextLength || 0),
        LOCAL_MODEL_N_GPU_LAYERS: Number(state.localGpuLayers || 0),
        LOCAL_MODEL_CHAT_FORMAT: trim(state.localChatFormat),
        LOCAL_ROUTING_MODE: trim(state.localSource) ? state.localRoutingMode : "cloud",
        OUROBOROS_MODEL: trim(state.mainModel),
        OUROBOROS_MODEL_CODE: trim(state.codeModel),
        OUROBOROS_MODEL_LIGHT: trim(state.lightModel),
        OUROBOROS_MODEL_FALLBACK: trim(state.fallbackModel),
      };
      try {
        const result = await window.pywebview.api.save_wizard(payload);
        if (result !== "ok") {
          state.saving = false;
          state.error = result || "Failed to save onboarding settings.";
          render();
        }
      } catch (err) {
        state.saving = false;
        state.error = String(err || "Failed to save onboarding settings.");
        render();
      }
    }

    function bindStepEvents() {
      bindClearButtons();
      const back = document.getElementById("back-btn");
      const next = document.getElementById("next-btn");
      if (back) back.addEventListener("click", previousStep);
      if (next) {
        next.addEventListener("click", () => {
          if (state.currentStep === "summary") {
            saveWizard();
          } else {
            nextStep();
          }
        });
      }
      if (state.currentStep === "providers") bindProviderStep();
      if (state.currentStep === "models") bindModelsStep();
      syncCurrentStepActionState();
    }

    applyModelDefaults(false);
    render();
  </script>
</body>
</html>
"""
