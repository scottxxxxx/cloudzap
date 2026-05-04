"""Unit tests for provider request building (not live API calls)."""

from app.models.chat import ChatRequest
from app.services.providers.anthropic import _CACHE_BREAK, AnthropicAdapter
from app.services.providers.openai_compat import OpenAICompatAdapter


def test_openai_text_only_content():
    """Text-only request should produce a string user content, not array."""
    request = ChatRequest(
        provider="openai",
        model="gpt-5.2",
        system_prompt="You are helpful.",
        user_content="Hello world",
    )
    content = OpenAICompatAdapter._build_user_content(request)
    assert isinstance(content, str)
    assert content == "Hello world"


def test_openai_image_content():
    """Request with images should produce multipart content array."""
    request = ChatRequest(
        provider="openai",
        model="gpt-5.2",
        system_prompt="You are helpful.",
        user_content="Describe this image",
        images=["abc123base64"],
    )
    content = OpenAICompatAdapter._build_user_content(request)
    assert isinstance(content, list)
    assert len(content) == 2
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert "abc123base64" in content[1]["image_url"]["url"]


def test_base64_redaction():
    """Long base64 strings should be redacted in raw JSON."""
    from app.services.providers.base import ProviderAdapter

    long_b64 = "A" * 200
    json_str = f'{{"data": "{long_b64}"}}'
    redacted = ProviderAdapter._redact_base64(json_str)
    assert "[BASE64_REDACTED]" in redacted
    assert long_b64 not in redacted


def test_short_data_not_redacted():
    """Short data strings should not be redacted."""
    from app.services.providers.base import ProviderAdapter

    json_str = '{"data": "short"}'
    redacted = ProviderAdapter._redact_base64(json_str)
    assert redacted == json_str


# ---------------------------------------------------------------------------
# Anthropic system-prompt cache split (Option C + Option A)
# ---------------------------------------------------------------------------
# Prompt caching strategy splits the single system block into two
# independently-cached blocks at the __CQ_BREAK__ sentinel:
#   - head (above marker): stable system instructions — caches across
#     turns within the 5-min ephemeral window
#   - tail (below marker): per-turn Context Quilt enrichment — caches
#     within a turn (e.g. across the two-call tool_use cycle of a
#     search-enabled query)
# When the marker is absent (legacy iOS templates), we MUST emit a
# single block to stay back-compat.


def test_system_block_no_marker_emits_single_cached_block():
    """Legacy iOS template without the marker: single cache_control block."""
    blocks = AnthropicAdapter._build_system_block("You are a helpful assistant.")
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"
    assert blocks[0]["text"] == "You are a helpful assistant."
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_system_block_marker_splits_into_two_cached_blocks():
    """Marker present: two blocks, each with cache_control, head and tail
    separated cleanly with the marker itself stripped."""
    prompt = (
        "Stable system rules.\nLine two.\n\n"
        f"{_CACHE_BREAK}\n"
        "Variable Context Quilt content for this turn."
    )
    blocks = AnthropicAdapter._build_system_block(prompt)
    assert len(blocks) == 2
    assert blocks[0]["text"] == "Stable system rules.\nLine two."
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"] == "Variable Context Quilt content for this turn."
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}
    # Marker itself must not leak into either block
    assert _CACHE_BREAK not in blocks[0]["text"]
    assert _CACHE_BREAK not in blocks[1]["text"]


def test_system_block_empty_tail_collapses_to_single_block():
    """If only the head is present (no enrichment for this turn), don't
    emit a useless empty cache slot — collapse to a single block."""
    prompt = f"Stable rules only.{_CACHE_BREAK}"
    blocks = AnthropicAdapter._build_system_block(prompt)
    assert len(blocks) == 1
    assert blocks[0]["text"] == "Stable rules only."


def test_system_block_empty_head_collapses_to_single_block():
    """Defensive: marker at the very start is degenerate; collapse rather
    than send an empty stable block."""
    prompt = f"{_CACHE_BREAK}\nOnly variable content."
    blocks = AnthropicAdapter._build_system_block(prompt)
    assert len(blocks) == 1
    assert blocks[0]["text"] == "Only variable content."


def test_build_body_routes_through_split():
    """End-to-end: a ChatRequest whose system_prompt contains the marker
    produces a body whose `system` is the two-block list."""
    request = ChatRequest(
        provider="anthropic",
        model="claude-sonnet-4-6",
        system_prompt=f"Head text\n\n{_CACHE_BREAK}\nTail text",
        user_content="Hello",
    )
    adapter = AnthropicAdapter(
        api_key="test",
        base_url="https://api.anthropic.com/v1/messages",
        auth_header="x-api-key",
        auth_prefix="",
    )
    body, _headers = adapter._build_body(request)
    assert isinstance(body["system"], list)
    assert len(body["system"]) == 2
    assert body["system"][0]["text"] == "Head text"
    assert body["system"][1]["text"] == "Tail text"
