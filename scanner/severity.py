"""Severity scoring for findings."""
from typing import Dict, Any


def score_severity(signals: Dict[str, Any], impact: Dict[str, Any]) -> int:
    """
    Calculate severity score based on signals and impact.

    Args:
        signals: Dictionary with analysis signals
        impact: Dictionary with impact assessment

    Returns:
        Severity score (0-10)
    """
    score = 0

    score += min(signals.get("arith", 0), 4)
    score += min(signals.get("div_mod", 0), 3)
    score += min(signals.get("state", 0), 3)
    score += min(signals.get("small_consts", 0), 2)

    # Add impact-based scoring
    if impact.get("is_exploit", False):
        score += 2
    if impact.get("stealable_wei", 0) > 10**18:
        score += 1

    return min(score, 10)
