"""
Confidence scoring for analysis results.
Score is based on step success rate, total retries, and empty result sets.
"""

from backend.agents.state import AgentState


def compute_confidence(state: AgentState) -> tuple[float, str]:
    """Returns (score: 0.0–1.0, label: High|Medium|Low|None)."""
    step_results = state.get("step_results", [])
    total = len(step_results)

    if total == 0:
        return 0.0, "None"

    # Steps that succeeded AND returned data are full-weight successes
    full_success = [sr for sr in step_results if not sr["error"] and sr["results"]]
    # Steps that succeeded but returned empty results are partial
    empty_success = [sr for sr in step_results if not sr["error"] and not sr["results"]]

    success_rate = (len(full_success) + 0.5 * len(empty_success)) / total

    # Penalise for retries (each retry = model needed correction)
    total_retries = state.get("total_retries", 0)
    retry_penalty = min(total_retries * 0.08, 0.30)

    score = round(max(0.0, min(1.0, success_rate - retry_penalty)), 2)

    if score >= 0.85:
        label = "High"
    elif score >= 0.55:
        label = "Medium"
    else:
        label = "Low"

    return score, label
