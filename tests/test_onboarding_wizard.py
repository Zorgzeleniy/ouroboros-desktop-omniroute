from ouroboros.onboarding_wizard import build_onboarding_html, prepare_onboarding_settings


def _base_payload() -> dict:
    return {
        "OPENROUTER_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "TOTAL_BUDGET": 10,
        "LOCAL_MODEL_SOURCE": "",
        "LOCAL_MODEL_FILENAME": "",
        "LOCAL_MODEL_CONTEXT_LENGTH": 16384,
        "LOCAL_MODEL_N_GPU_LAYERS": -1,
        "LOCAL_MODEL_CHAT_FORMAT": "",
        "LOCAL_ROUTING_MODE": "cloud",
        "OUROBOROS_MODEL": "openai::gpt-5.4",
        "OUROBOROS_MODEL_CODE": "openai::gpt-5.4",
        "OUROBOROS_MODEL_LIGHT": "openai::gpt-5.4-mini",
        "OUROBOROS_MODEL_FALLBACK": "openai::gpt-5.4-mini",
    }


def test_prepare_onboarding_settings_requires_runnable_config():
    prepared, error = prepare_onboarding_settings(_base_payload(), {})

    assert prepared == {}
    assert "Configure OpenRouter, OpenAI, Anthropic, or a local model" in error


def test_prepare_onboarding_settings_accepts_openai_only_setup():
    payload = _base_payload()
    payload["OPENAI_API_KEY"] = "sk-openai-1234567890"

    prepared, error = prepare_onboarding_settings(payload, {})

    assert error is None
    assert prepared["OPENAI_API_KEY"] == "sk-openai-1234567890"
    assert prepared["OUROBOROS_MODEL"] == "openai::gpt-5.4"
    assert prepared["TOTAL_BUDGET"] == 10.0


def test_prepare_onboarding_settings_accepts_anthropic_only_setup():
    payload = _base_payload()
    payload["ANTHROPIC_API_KEY"] = "sk-ant-1234567890"
    payload["OUROBOROS_MODEL"] = "anthropic::claude-opus-4-6"
    payload["OUROBOROS_MODEL_CODE"] = "anthropic::claude-opus-4-6"
    payload["OUROBOROS_MODEL_LIGHT"] = "anthropic::claude-sonnet-4-6"
    payload["OUROBOROS_MODEL_FALLBACK"] = "anthropic::claude-sonnet-4-6"

    prepared, error = prepare_onboarding_settings(payload, {})

    assert error is None
    assert prepared["ANTHROPIC_API_KEY"] == "sk-ant-1234567890"
    assert prepared["OUROBOROS_MODEL"] == "anthropic::claude-opus-4-6"


def test_prepare_onboarding_settings_sets_all_local_routes():
    payload = _base_payload()
    payload["LOCAL_MODEL_SOURCE"] = "Qwen/Qwen2.5-7B-Instruct-GGUF"
    payload["LOCAL_MODEL_FILENAME"] = "qwen2.5-7b-instruct-q3_k_m.gguf"
    payload["LOCAL_ROUTING_MODE"] = "all"

    prepared, error = prepare_onboarding_settings(payload, {})

    assert error is None
    assert prepared["USE_LOCAL_MAIN"] is True
    assert prepared["USE_LOCAL_CODE"] is True
    assert prepared["USE_LOCAL_LIGHT"] is True
    assert prepared["USE_LOCAL_FALLBACK"] is True


def test_build_onboarding_html_contains_multistep_markers():
    html = build_onboarding_html({})

    assert "STEP_ORDER = [\"providers\", \"models\", \"summary\"]" in html
    assert "Add your access" in html
    assert "Review model lanes" in html
    assert "You can paste several keys here" in html
    assert "openai::gpt-5.4" in html
    assert "openai::gpt-5.4-mini" in html
    assert "anthropic::claude-sonnet-4-6" in html
    assert "Skip optional step" not in html


def test_build_onboarding_html_adapts_to_multi_provider_access():
    html = build_onboarding_html({})

    assert "function activeProviderProfile()" in html
    assert "function profileLabel(profile)" in html
    assert "function nextButtonShouldBeDisabled()" in html
    assert "function syncCurrentStepActionState()" in html
    assert 'if (hasOpenai && hasAnthropic) {' in html
    assert 'return "direct-multi";' in html
    assert 'OPENROUTER_API_KEY: trim(state.openrouterKey)' in html
    assert 'OPENAI_API_KEY: trim(state.openaiKey)' in html
    assert 'ANTHROPIC_API_KEY: trim(state.anthropicKey)' in html
    assert 'LOCAL_ROUTING_MODE: trim(state.localSource) ? state.localRoutingMode : "cloud"' in html
