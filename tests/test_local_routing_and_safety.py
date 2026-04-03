import pytest


def test_prepare_messages_for_local_context_preserves_core_and_compacts_non_core():
    from ouroboros.llm import LLMClient

    client = LLMClient()
    messages = [
        {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "SYSTEM PROMPT\n\n"
                        "## BIBLE.md\n\nBIBLE TEXT\n\n"
                        "## ARCHITECTURE.md\n\n" + ("A" * 4000)
                    ),
                },
                {
                    "type": "text",
                    "text": (
                        "## Scratchpad\n\nSCRATCHPAD\n\n"
                        "## Identity\n\nIDENTITY\n\n"
                        "## Dialogue History\n\n" + ("D" * 4000)
                    ),
                },
                {
                    "type": "text",
                    "text": (
                        "## Drive state\n\n{}\n\n"
                        "## Runtime context\n\nruntime\n\n"
                        "## Recent tools\n\n" + ("T" * 4000)
                    ),
                },
            ],
        },
        {"role": "user", "content": "hello"},
    ]

    compacted = client._prepare_messages_for_local_context(messages, ctx_len=1500, max_tokens=500)
    system_blocks = compacted[0]["content"]

    assert "## BIBLE.md" in system_blocks[0]["text"]
    assert "ARCHITECTURE.md" in system_blocks[0]["text"]
    assert "[Compacted for local-model context" in system_blocks[0]["text"]
    assert "## Scratchpad" in system_blocks[1]["text"]
    assert "## Identity" in system_blocks[1]["text"]
    assert "Dialogue History" in system_blocks[1]["text"]
    assert "[Compacted for local-model context" in system_blocks[1]["text"]
    assert "## Drive state" in system_blocks[2]["text"]
    assert "## Runtime context" in system_blocks[2]["text"]
    assert "Recent tools" in system_blocks[2]["text"]
    assert "[Compacted for local-model context" in system_blocks[2]["text"]


def test_prepare_messages_for_local_context_raises_when_core_still_too_large():
    from ouroboros.llm import LLMClient, LocalContextTooLargeError

    client = LLMClient()
    huge_core = "X" * 12000
    messages = [
        {
            "role": "system",
            "content": [
                {"type": "text", "text": f"SYSTEM\n\n## BIBLE.md\n\n{huge_core}"},
                {"type": "text", "text": f"## Scratchpad\n\n{huge_core}\n\n## Identity\n\n{huge_core}"},
                {"type": "text", "text": "## Drive state\n\n{}"},
            ],
        },
        {"role": "user", "content": "hello"},
    ]

    with pytest.raises(LocalContextTooLargeError):
        client._prepare_messages_for_local_context(messages, ctx_len=1000, max_tokens=400)


def test_build_openrouter_kwargs_for_anthropic_keeps_require_parameters_only():
    from ouroboros.llm import LLMClient

    client = LLMClient()
    kwargs = client._build_openrouter_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        model="anthropic/claude-opus-4.6",
        tools=None,
        reasoning_effort="medium",
        max_tokens=1000,
        tool_choice="auto",
        temperature=None,
    )

    assert kwargs["extra_body"]["provider"] == {"require_parameters": True}
    assert "order" not in kwargs["extra_body"]["provider"]
    assert "allow_fallbacks" not in kwargs["extra_body"]["provider"]


def test_build_openrouter_kwargs_for_non_anthropic_has_no_provider_block():
    from ouroboros.llm import LLMClient

    client = LLMClient()
    kwargs = client._build_openrouter_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        model="openai/gpt-4.1",
        tools=None,
        reasoning_effort="medium",
        max_tokens=1000,
        tool_choice="auto",
        temperature=None,
    )

    assert "provider" not in kwargs["extra_body"]


def test_format_messages_for_safety_marks_omission():
    from ouroboros.safety import _format_messages_for_safety

    text = "X" * 700
    output = _format_messages_for_safety([
        {"role": "user", "content": text},
    ])

    assert "[..." in output
    assert "chars omitted" in output
