"""Map provider model identifiers to abstract AI tier labels.

Clients render `ai_tier` instead of raw model names so we can swap models
without breaking client-side mappings or leaking model identity into UI.
"""


def infer_ai_tier(model: str | None) -> str:
    """Return "standard" or "advanced" for the given model name.

    Anything not recognized falls through to "standard" — safe default that
    matches the cheaper-quality bucket.
    """
    if not model:
        return "standard"
    name = model.lower()
    if "sonnet" in name or "opus" in name:
        return "advanced"
    return "standard"
