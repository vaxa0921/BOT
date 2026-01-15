"""Impact estimation for findings."""
from typing import Dict, Any


def estimate_impact(sim_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Estimate impact from simulation results.

    Args:
        sim_result: Simulation results dictionary

    Returns:
        Impact assessment dictionary
    """
    return {
        "stealable_wei": sim_result.get("delta", 0),
        "tx_needed": sim_result.get("tx", 0),
        "is_exploit": sim_result.get("delta", 0) > 0
    }
