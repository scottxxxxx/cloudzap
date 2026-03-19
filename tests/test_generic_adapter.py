"""Tests for the generic config-driven adapter and base utility methods."""

from app.services.providers.base import ProviderAdapter
from app.services.providers.generic import GenericAdapter
from app.models.chat import ChatRequest


def test_extract_path_simple():
    data = {"usage": {"prompt_tokens": 100, "completion_tokens": 50}}
    assert ProviderAdapter._extract_path(data, "usage.prompt_tokens") == 100
    assert ProviderAdapter._extract_path(data, "usage.completion_tokens") == 50


def test_extract_path_array_index():
    data = {"choices": [{"message": {"content": "Hello"}}]}
    assert ProviderAdapter._extract_path(data, "choices.0.message.content") == "Hello"


def test_extract_path_missing():
    data = {"usage": {"prompt_tokens": 100}}
    assert ProviderAdapter._extract_path(data, "usage.missing_field") is None
    assert ProviderAdapter._extract_path(data, "nonexistent.path") is None


def test_extract_path_deep_nested():
    data = {"a": {"b": {"c": {"d": 42}}}}
    assert ProviderAdapter._extract_path(data, "a.b.c.d") == 42


def test_flatten_usage_simple():
    usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    flat = ProviderAdapter._flatten_usage(usage)
    assert flat == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}


def test_flatten_usage_nested():
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "prompt_tokens_details": {
            "cached_tokens": 20,
            "audio_tokens": 0,
        },
        "completion_tokens_details": {
            "reasoning_tokens": 10,
        },
    }
    flat = ProviderAdapter._flatten_usage(usage)
    assert flat["prompt_tokens"] == 100
    assert flat["prompt_tokens_details.cached_tokens"] == 20
    assert flat["completion_tokens_details.reasoning_tokens"] == 10
    # audio_tokens is 0 which is not None, so it should be included
    assert flat["prompt_tokens_details.audio_tokens"] == 0


def test_flatten_usage_skips_none():
    usage = {"prompt_tokens": 100, "cached_tokens": None}
    flat = ProviderAdapter._flatten_usage(usage)
    assert "cached_tokens" not in flat
    assert flat["prompt_tokens"] == 100


def test_generic_build_user_content_text_only():
    request = ChatRequest(
        provider="test",
        model="test-v1",
        system_prompt="sys",
        user_content="hello",
    )
    content = GenericAdapter._build_user_content(request, "openai")
    assert content == "hello"


def test_generic_build_user_content_openai_images():
    request = ChatRequest(
        provider="test",
        model="test-v1",
        system_prompt="sys",
        user_content="describe",
        images=["abc123"],
    )
    content = GenericAdapter._build_user_content(request, "openai")
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"


def test_generic_build_user_content_anthropic_images():
    request = ChatRequest(
        provider="test",
        model="test-v1",
        system_prompt="sys",
        user_content="describe",
        images=["abc123"],
    )
    content = GenericAdapter._build_user_content(request, "anthropic")
    assert isinstance(content, list)
    # Anthropic: images first, then text
    assert content[0]["type"] == "image"
    assert content[1]["type"] == "text"


def test_generic_build_user_content_no_images():
    request = ChatRequest(
        provider="test",
        model="test-v1",
        system_prompt="sys",
        user_content="hello",
        images=["abc123"],
    )
    content = GenericAdapter._build_user_content(request, "none")
    assert content == "hello"  # Images ignored


def test_generic_build_url_with_model_placeholder():
    adapter = GenericAdapter(
        api_key="key",
        base_url="https://api.example.com/v1/models/{model}:generate",
        auth_header="Authorization",
        auth_prefix="Bearer ",
    )
    request = ChatRequest(
        provider="test", model="my-model-v1",
        system_prompt="sys", user_content="hello",
    )
    url = adapter._build_url(request)
    assert url == "https://api.example.com/v1/models/my-model-v1:generate"
