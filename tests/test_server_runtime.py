from ouroboros.server_runtime import (
    apply_runtime_provider_defaults,
    has_startup_ready_provider,
    has_supervisor_provider,
)


def test_has_startup_ready_provider_accepts_any_remote_key_or_local_source():
    assert has_startup_ready_provider({"OPENROUTER_API_KEY": "sk-or-test"})
    assert has_startup_ready_provider({"OPENAI_API_KEY": "sk-openai"})
    assert has_startup_ready_provider({"ANTHROPIC_API_KEY": "sk-ant"})
    assert has_startup_ready_provider({"OPENAI_COMPATIBLE_API_KEY": "compat-key"})
    assert has_startup_ready_provider({"CLOUDRU_FOUNDATION_MODELS_API_KEY": "cloudru-key"})
    assert has_startup_ready_provider({"LOCAL_MODEL_SOURCE": "Qwen/Qwen2.5-7B-Instruct-GGUF"})


def test_has_supervisor_provider_requires_remote_credentials_or_local_routing():
    assert has_supervisor_provider({"OPENAI_API_KEY": "sk-openai"})
    assert has_supervisor_provider({"ANTHROPIC_API_KEY": "sk-ant"})
    assert has_supervisor_provider({"USE_LOCAL_MAIN": True})
    assert has_supervisor_provider({"USE_LOCAL_FALLBACK": "True"})
    assert not has_supervisor_provider({"LOCAL_MODEL_SOURCE": "Qwen/Qwen2.5-7B-Instruct-GGUF"})


def test_apply_runtime_provider_defaults_autofills_official_openai_models():
    normalized, changed, changed_keys = apply_runtime_provider_defaults({
        "OPENAI_API_KEY": "sk-openai",
        "OUROBOROS_MODEL": "anthropic/claude-opus-4.6",
        "OUROBOROS_MODEL_CODE": "anthropic/claude-opus-4.6",
        "OUROBOROS_MODEL_LIGHT": "anthropic/claude-sonnet-4.6",
        "OUROBOROS_MODEL_FALLBACK": "anthropic/claude-sonnet-4.6",
    })

    assert changed
    assert set(changed_keys) == {
        "OUROBOROS_MODEL",
        "OUROBOROS_MODEL_CODE",
        "OUROBOROS_MODEL_LIGHT",
        "OUROBOROS_MODEL_FALLBACK",
        "OUROBOROS_REVIEW_MODELS",
    }
    assert normalized["OUROBOROS_MODEL"] == "openai::gpt-5.4"
    assert normalized["OUROBOROS_MODEL_CODE"] == "openai::gpt-5.4"
    assert normalized["OUROBOROS_MODEL_LIGHT"] == "openai::gpt-5.4-mini"
    assert normalized["OUROBOROS_MODEL_FALLBACK"] == "openai::gpt-5.4-mini"
    assert normalized["OUROBOROS_REVIEW_MODELS"] == ",".join(["openai::gpt-5.4"] * 3)


def test_apply_runtime_provider_defaults_migrates_saved_openai_values():
    normalized, changed, changed_keys = apply_runtime_provider_defaults({
        "OPENAI_API_KEY": "sk-openai",
        "OUROBOROS_MODEL": "openai/gpt-5.4",
        "OUROBOROS_MODEL_CODE": "openai/gpt-5.4",
        "OUROBOROS_MODEL_LIGHT": "openai/gpt-4.1",
        "OUROBOROS_MODEL_FALLBACK": "openai/gpt-4.1",
        "OUROBOROS_REVIEW_MODELS": "openai/gpt-5.4",
    })

    assert changed
    assert set(changed_keys) == {
        "OUROBOROS_MODEL",
        "OUROBOROS_MODEL_CODE",
        "OUROBOROS_MODEL_LIGHT",
        "OUROBOROS_MODEL_FALLBACK",
        "OUROBOROS_REVIEW_MODELS",
    }
    assert normalized["OUROBOROS_MODEL"] == "openai::gpt-5.4"
    assert normalized["OUROBOROS_MODEL_CODE"] == "openai::gpt-5.4"
    assert normalized["OUROBOROS_MODEL_LIGHT"] == "openai::gpt-5.4-mini"
    assert normalized["OUROBOROS_MODEL_FALLBACK"] == "openai::gpt-5.4-mini"
    assert normalized["OUROBOROS_REVIEW_MODELS"] == ",".join(["openai::gpt-5.4"] * 3)


def test_apply_runtime_provider_defaults_keeps_explicit_official_openai_review_models():
    normalized, changed, changed_keys = apply_runtime_provider_defaults({
        "OPENAI_API_KEY": "sk-openai",
        "OUROBOROS_MODEL": "openai::gpt-5.4",
        "OUROBOROS_MODEL_CODE": "openai::gpt-5.4",
        "OUROBOROS_MODEL_LIGHT": "openai::gpt-5.4-mini",
        "OUROBOROS_MODEL_FALLBACK": "openai::gpt-5.4-mini",
        "OUROBOROS_REVIEW_MODELS": "openai::gpt-5.4,openai::gpt-5.4-mini",
    })

    assert not changed
    assert changed_keys == []
    assert normalized["OUROBOROS_REVIEW_MODELS"] == "openai::gpt-5.4,openai::gpt-5.4-mini"


def test_apply_runtime_provider_defaults_normalizes_anthropic_only_setup():
    normalized, changed, changed_keys = apply_runtime_provider_defaults({
        "ANTHROPIC_API_KEY": "sk-ant",
        "OUROBOROS_MODEL": "anthropic/claude-opus-4.6",
        "OUROBOROS_MODEL_CODE": "anthropic/claude-opus-4.6",
        "OUROBOROS_MODEL_LIGHT": "anthropic/claude-sonnet-4.6",
        "OUROBOROS_MODEL_FALLBACK": "anthropic/claude-sonnet-4.6",
    })

    assert changed
    assert set(changed_keys) == {
        "OUROBOROS_MODEL",
        "OUROBOROS_MODEL_CODE",
        "OUROBOROS_MODEL_LIGHT",
        "OUROBOROS_MODEL_FALLBACK",
        "OUROBOROS_REVIEW_MODELS",
    }
    assert normalized["OUROBOROS_MODEL"] == "anthropic::claude-opus-4-6"
    assert normalized["OUROBOROS_MODEL_CODE"] == "anthropic::claude-opus-4-6"
    assert normalized["OUROBOROS_MODEL_LIGHT"] == "anthropic::claude-sonnet-4-6"
    assert normalized["OUROBOROS_MODEL_FALLBACK"] == "anthropic::claude-sonnet-4-6"
    assert normalized["OUROBOROS_REVIEW_MODELS"] == ",".join(["anthropic::claude-opus-4-6"] * 3)


def test_apply_runtime_provider_defaults_skips_non_official_or_custom_configs():
    normalized, changed, changed_keys = apply_runtime_provider_defaults({
        "OPENAI_API_KEY": "sk-openai",
        "OPENAI_BASE_URL": "https://compat.example/v1",
        "OUROBOROS_MODEL": "custom-model",
    })

    assert not changed
    assert changed_keys == []
    assert normalized["OUROBOROS_MODEL"] == "custom-model"
