"""Tests for effort, review models, and review enforcement settings."""
import os
from ouroboros.config import (
    SETTINGS_DEFAULTS,
    apply_settings_to_env,
    resolve_effort,
    get_review_models,
    get_review_enforcement,
)


# ---------------------------------------------------------------------------
# Legacy env var backward compat
# ---------------------------------------------------------------------------

def test_initial_effort_default(monkeypatch):
    """Default effort is 'medium' when env var not set."""
    monkeypatch.delenv("OUROBOROS_EFFORT_TASK", raising=False)
    monkeypatch.delenv("OUROBOROS_INITIAL_REASONING_EFFORT", raising=False)
    assert resolve_effort("task") == "medium"


def test_initial_effort_valid_values(monkeypatch):
    """Valid effort values pass through unchanged via OUROBOROS_EFFORT_TASK."""
    for effort in ("none", "low", "medium", "high"):
        monkeypatch.setenv("OUROBOROS_EFFORT_TASK", effort)
        monkeypatch.delenv("OUROBOROS_INITIAL_REASONING_EFFORT", raising=False)
        assert resolve_effort("task") == effort


def test_initial_effort_invalid_falls_back_to_medium(monkeypatch):
    """Invalid effort values fall back to 'medium'."""
    monkeypatch.setenv("OUROBOROS_EFFORT_TASK", "extreme")
    monkeypatch.delenv("OUROBOROS_INITIAL_REASONING_EFFORT", raising=False)
    assert resolve_effort("task") == "medium"


# ---------------------------------------------------------------------------
# New per-type defaults in SETTINGS_DEFAULTS
# ---------------------------------------------------------------------------

def test_effort_defaults_in_config():
    """All four effort keys have correct defaults in SETTINGS_DEFAULTS."""
    assert SETTINGS_DEFAULTS.get("OUROBOROS_EFFORT_TASK") == "medium"
    assert SETTINGS_DEFAULTS.get("OUROBOROS_EFFORT_EVOLUTION") == "high"
    assert SETTINGS_DEFAULTS.get("OUROBOROS_EFFORT_REVIEW") == "medium"
    assert SETTINGS_DEFAULTS.get("OUROBOROS_EFFORT_CONSCIOUSNESS") == "low"


def test_review_models_default_in_config():
    """OUROBOROS_REVIEW_MODELS has a default value in config."""
    val = SETTINGS_DEFAULTS.get("OUROBOROS_REVIEW_MODELS", "")
    assert val  # non-empty
    models = [m.strip() for m in val.split(",") if m.strip()]
    assert len(models) >= 2  # quorum requires at least 2


def test_review_enforcement_default_in_config():
    """OUROBOROS_REVIEW_ENFORCEMENT defaults to advisory."""
    assert SETTINGS_DEFAULTS.get("OUROBOROS_REVIEW_ENFORCEMENT") == "advisory"


# ---------------------------------------------------------------------------
# get_review_models() — single source of truth
# ---------------------------------------------------------------------------

def test_get_review_models_default(monkeypatch):
    """get_review_models() returns the config default when env is unset."""
    monkeypatch.delenv("OUROBOROS_REVIEW_MODELS", raising=False)
    models = get_review_models()
    assert isinstance(models, list)
    assert len(models) >= 2
    assert all("/" in m for m in models)  # valid OpenRouter model IDs


def test_get_review_models_custom(monkeypatch):
    """get_review_models() returns custom models when env is set."""
    monkeypatch.setenv("OUROBOROS_REVIEW_MODELS", "a/b,c/d")
    models = get_review_models()
    assert models == ["a/b", "c/d"]


def test_get_review_models_empty_env_falls_back_to_default(monkeypatch):
    """get_review_models() falls back to default when env is empty string."""
    monkeypatch.setenv("OUROBOROS_REVIEW_MODELS", "")
    models = get_review_models()
    # Must return the default, not an empty list
    assert len(models) >= 2
    assert models == [m.strip() for m in SETTINGS_DEFAULTS["OUROBOROS_REVIEW_MODELS"].split(",") if m.strip()]


def test_get_review_enforcement_default(monkeypatch):
    """get_review_enforcement() returns the config default when env is unset."""
    monkeypatch.delenv("OUROBOROS_REVIEW_ENFORCEMENT", raising=False)
    assert get_review_enforcement() == "advisory"


def test_get_review_enforcement_custom(monkeypatch):
    """get_review_enforcement() accepts advisory and blocking."""
    monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "advisory")
    assert get_review_enforcement() == "advisory"
    monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "blocking")
    assert get_review_enforcement() == "blocking"


def test_get_review_enforcement_invalid_falls_back(monkeypatch):
    """Unknown values fall back to advisory (the default)."""
    monkeypatch.setenv("OUROBOROS_REVIEW_ENFORCEMENT", "strictest")
    assert get_review_enforcement() == "advisory"


def test_apply_settings_clears_review_models_restores_default(monkeypatch):
    """Clearing OUROBOROS_REVIEW_MODELS in settings restores the default in env."""
    # Simulate user clearing the field in Settings UI (empty string)
    settings = {"OUROBOROS_REVIEW_MODELS": ""}
    apply_settings_to_env(settings)
    # env var should be the default, not empty
    env_val = os.environ.get("OUROBOROS_REVIEW_MODELS", "")
    assert env_val == SETTINGS_DEFAULTS["OUROBOROS_REVIEW_MODELS"]
    # get_review_models() should also return correct defaults
    assert len(get_review_models()) >= 2


def test_apply_settings_clears_review_enforcement_restores_default(monkeypatch):
    """Clearing OUROBOROS_REVIEW_ENFORCEMENT restores the default in env."""
    settings = {"OUROBOROS_REVIEW_ENFORCEMENT": ""}
    apply_settings_to_env(settings)
    env_val = os.environ.get("OUROBOROS_REVIEW_ENFORCEMENT", "")
    assert env_val == SETTINGS_DEFAULTS["OUROBOROS_REVIEW_ENFORCEMENT"]
    assert get_review_enforcement() == "advisory"


# ---------------------------------------------------------------------------
# apply_settings_to_env propagation
# ---------------------------------------------------------------------------

def test_apply_settings_to_env_includes_effort_keys():
    """apply_settings_to_env propagates all four effort keys."""
    settings = {
        "OUROBOROS_EFFORT_TASK": "low",
        "OUROBOROS_EFFORT_EVOLUTION": "medium",
        "OUROBOROS_EFFORT_REVIEW": "high",
        "OUROBOROS_EFFORT_CONSCIOUSNESS": "none",
        "OUROBOROS_REVIEW_MODELS": "model-a,model-b",
        "OUROBOROS_REVIEW_ENFORCEMENT": "advisory",
    }
    apply_settings_to_env(settings)
    assert os.environ.get("OUROBOROS_EFFORT_TASK") == "low"
    assert os.environ.get("OUROBOROS_EFFORT_EVOLUTION") == "medium"
    assert os.environ.get("OUROBOROS_EFFORT_REVIEW") == "high"
    assert os.environ.get("OUROBOROS_EFFORT_CONSCIOUSNESS") == "none"
    assert os.environ.get("OUROBOROS_REVIEW_MODELS") == "model-a,model-b"
    assert os.environ.get("OUROBOROS_REVIEW_ENFORCEMENT") == "advisory"
    # cleanup
    for k in ("OUROBOROS_EFFORT_TASK", "OUROBOROS_EFFORT_EVOLUTION",
              "OUROBOROS_EFFORT_REVIEW", "OUROBOROS_EFFORT_CONSCIOUSNESS",
              "OUROBOROS_REVIEW_MODELS", "OUROBOROS_REVIEW_ENFORCEMENT"):
        os.environ.pop(k, None)
