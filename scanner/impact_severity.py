"""Impact-driven severity scoring."""
from typing import Dict, Any
from scanner.impact_calculator import calculate_real_impact
from scanner.config import MIN_NET_PROFIT_WEI


def score_impact_severity(
    impact_data: Dict[str, Any]
) -> int:
    """
    Score severity based on impact.

    Args:
        impact_data: Impact calculation results

    Returns:
        Severity score (0-10)
    """
    score = 0
    
    stolen = impact_data.get("stolen_wei", 0)
    percentage = impact_data.get("percentage_loss", 0.0)
    tvl = impact_data.get("tvl_wei", 0)
    
    # Amount-based scoring
    if stolen >= 10**20:  # >= 100 ETH
        score += 5
    elif stolen >= 10**19:  # >= 10 ETH
        score += 4
    elif stolen >= 10**18:  # >= 1 ETH
        score += 3
    elif stolen >= 10**17:  # >= 0.1 ETH
        score += 2
    elif stolen > 0:
        score += 1
    
    # Percentage-based scoring
    if percentage >= 50:
        score += 3
    elif percentage >= 10:
        score += 2
    elif percentage >= 1:
        score += 1
    
    # TVL-based scoring (larger TVL = higher severity)
    if tvl >= 10**21:  # >= 1000 ETH
        score += 1
    
    return min(score, 10)


def is_bounty_worthy(
    impact_data: Dict[str, Any],
    severity_score: int,
    min_severity: int = 7
) -> bool:
    """
    Determine if finding is bounty-worthy.

    Args:
        impact_data: Impact calculation results
        severity_score: Severity score
        min_severity: Minimum severity for bounty

    Returns:
        True if bounty-worthy
    """
    if severity_score < min_severity:
        return False
    
    stolen = impact_data.get("stolen_wei", 0)
    percentage = impact_data.get("percentage_loss", 0.0)
    
    # Must have meaningful impact
    if stolen < 10**17:  # Less than 0.1 ETH
        return False
    
    if percentage < 0.1:  # Less than 0.1% of TVL
        return False
    net_profit = impact_data.get("net_profit_wei", 0)
    if net_profit < MIN_NET_PROFIT_WEI:
        return False
    return True
