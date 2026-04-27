from app.services.ai_tier import infer_ai_tier


def test_haiku_maps_to_standard():
    assert infer_ai_tier("claude-haiku-4-5-20251001") == "standard"


def test_sonnet_maps_to_advanced():
    assert infer_ai_tier("claude-sonnet-4-6") == "advanced"


def test_opus_maps_to_advanced():
    assert infer_ai_tier("claude-opus-4-7") == "advanced"


def test_unknown_falls_back_to_standard():
    assert infer_ai_tier("gpt-5") == "standard"
    assert infer_ai_tier("") == "standard"
    assert infer_ai_tier(None) == "standard"


def test_anthropic_prefix_does_not_confuse_match():
    # Provider prefix shouldn't trip the substring search.
    assert infer_ai_tier("anthropic/claude-haiku-4-5-20251001") == "standard"
    assert infer_ai_tier("anthropic/claude-sonnet-4-6") == "advanced"
