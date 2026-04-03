import asyncio
import pathlib


def test_multi_model_review_async_uses_llm_client_chat_async(monkeypatch, tmp_path):
    from ouroboros.tools.registry import ToolContext
    from ouroboros.tools import review as review_module

    calls = []

    class FakeLLMClient:
        def __init__(self, *args, **kwargs):
            pass

        async def chat_async(self, **kwargs):
            calls.append(kwargs)
            return (
                {"content": '[{"item":"check","verdict":"PASS","severity":"advisory","reason":"ok"}]'},
                {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "cached_tokens": 7,
                    "cache_write_tokens": 2,
                    "cost": 0.01,
                },
            )

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(review_module, "LLMClient", FakeLLMClient)
    monkeypatch.setattr(review_module, "_load_bible", lambda: "Bible")

    ctx = ToolContext(repo_dir=pathlib.Path(tmp_path), drive_root=pathlib.Path(tmp_path))
    result = asyncio.run(
        review_module._multi_model_review_async(
            "review target",
            "review instructions",
            ["anthropic/claude-sonnet-4.6"],
            ctx,
        )
    )

    assert calls
    assert calls[0]["model"] == "anthropic/claude-sonnet-4.6"
    assert calls[0]["temperature"] == 0.2
    assert result["results"][0]["cached_tokens"] == 7
    assert result["results"][0]["cache_write_tokens"] == 2
    assert ctx.pending_events
    assert ctx.pending_events[0]["usage"]["cached_tokens"] == 7
    assert ctx.pending_events[0]["usage"]["cache_write_tokens"] == 2
