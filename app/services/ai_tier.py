"""Map subscription tier to abstract AI tier label clients render.

Decoupled from the model identity: clients render `ai_tier` based on
*what the user is paying for*, not what model happened to answer the
request. Lets us swap models per tier without breaking iOS attribution.
"""


def tier_to_ai_tier(tier_name: str | None) -> str:
    """Return "standard" or "advanced" for the given subscription tier.

    Pro and admin → "advanced" (tier promise: Advanced AI for reports/analysis).
    Everything else (free, plus, byok, unknown) → "standard".
    """
    if tier_name in ("pro", "admin"):
        return "advanced"
    return "standard"
