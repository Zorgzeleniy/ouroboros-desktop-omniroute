"""Test OmniRoute provider routing in LLMClient."""
import os
import sys
import types
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeOpenAI:
    created = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        type(self).created.append(self)


class TestOmniRouteRouting(unittest.TestCase):
    def setUp(self):
        _FakeOpenAI.created.clear()

    def test_omniroute_env_overrides_openrouter(self):
        """When OMNIROUTE_BASE_URL is set, LLMClient uses OmniRoute."""
        from ouroboros.llm import LLMClient

        fake_openai = types.SimpleNamespace(OpenAI=_FakeOpenAI)
        with patch.dict(sys.modules, {"openai": fake_openai}):
            env = {
                "OPENROUTER_API_KEY": "sk-or-old",
                "OMNIROUTE_API_KEY": "sk-omni-key",
                "OMNIROUTE_BASE_URL": "https://omniroute.ai/api/v1",
            }
            with patch.dict(os.environ, env, clear=False):
                client = LLMClient()
                c = client._get_client()

        self.assertEqual(len(_FakeOpenAI.created), 1)
        self.assertEqual(_FakeOpenAI.created[0].kwargs["api_key"], "sk-omni-key")
        self.assertEqual(_FakeOpenAI.created[0].kwargs["base_url"], "https://omniroute.ai/api/v1")

    def test_fallback_to_openrouter_when_no_omniroute(self):
        """When no OmniRoute config, falls back to OpenRouter."""
        from ouroboros.llm import LLMClient

        fake_openai = types.SimpleNamespace(OpenAI=_FakeOpenAI)
        with patch.dict(sys.modules, {"openai": fake_openai}):
            env = {
                "OPENROUTER_API_KEY": "sk-or-key",
            }
            # Ensure OmniRoute keys are absent
            for k in ("OMNIROUTE_API_KEY", "OMNIROUTE_BASE_URL"):
                os.environ.pop(k, None)
            with patch.dict(os.environ, env, clear=False):
                client = LLMClient()
                c = client._get_client()

        self.assertEqual(len(_FakeOpenAI.created), 1)
        self.assertEqual(_FakeOpenAI.created[0].kwargs["api_key"], "sk-or-key")
        self.assertEqual(_FakeOpenAI.created[0].kwargs["base_url"], "https://openrouter.ai/api/v1")


if __name__ == "__main__":
    unittest.main()
