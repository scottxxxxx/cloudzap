from app.services.ai_tier import tier_to_ai_tier


def test_pro_maps_to_advanced():
    assert tier_to_ai_tier("pro") == "advanced"


def test_admin_maps_to_advanced():
    assert tier_to_ai_tier("admin") == "advanced"


def test_plus_maps_to_standard():
    assert tier_to_ai_tier("plus") == "standard"


def test_free_maps_to_standard():
    assert tier_to_ai_tier("free") == "standard"


def test_unknown_falls_back_to_standard():
    # New tiers (e.g., byok) and unknown values stay in the cheaper bucket.
    assert tier_to_ai_tier("byok") == "standard"
    assert tier_to_ai_tier("anything") == "standard"
    assert tier_to_ai_tier("") == "standard"
    assert tier_to_ai_tier(None) == "standard"
