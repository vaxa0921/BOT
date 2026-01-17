"""Economic-aware static prefilter."""
from typing import Dict, Any
from scanner.heuristic import analyze_bytecode


def economic_prefilter(
    bytecode: str,
    contract_address: str,
    min_tvl: int = 10**18  # 1 ETH minimum
) -> Dict[str, Any]:
    """
    Economic-aware prefilter that considers potential value.

    Args:
        bytecode: Contract bytecode
        contract_address: Contract address
        min_tvl: Minimum TVL threshold

    Returns:
        Dictionary with prefilter results
    """
    signals = analyze_bytecode(bytecode)
    
    # Economic signals
    economic_score = 0
    
    # High arithmetic operations suggest financial logic
    if signals["arith"] > 2:
        economic_score += 2
    
    # Division operations suggest price calculations
    if signals["div_mod"] > 0:
        economic_score += 2
    
    # State operations suggest value storage
    if signals["state"] > 2:
        economic_score += 1
    
    # Call operations suggest external interactions
    if signals["calls"] > 0:
        economic_score += 1
    
    # Small constants might be fees (e.g., 30 = 0.3%)
    if signals["small_consts"] > 0:
        economic_score += 1
    
    passes = economic_score >= 2
    
    return {
        "address": contract_address,
        "passes": passes,
        "economic_score": economic_score,
        "signals": signals,
        "reason": "economic_indicators" if passes else "insufficient_economic_activity"
    }


def negative_knowledge_skip(
    bytecode: str,
    known_safe_patterns: list = None
) -> bool:
    """
    Skip contracts with known safe patterns (negative knowledge).

    Args:
        bytecode: Contract bytecode
        known_safe_patterns: List of known safe bytecode patterns

    Returns:
        True if should skip (is safe), False if should analyze
    """
    if known_safe_patterns is None:
        known_safe_patterns = []  # User requested mass scan: removed standard preambles to scan everything

    
    bytecode_lower = bytecode.lower()
    
    # Skip if matches known safe patterns
    for pattern in known_safe_patterns:
        if pattern in bytecode_lower:
            return True
    
    # Do NOT skip minimal proxies (EIP-1167) even if bytecode is short
    if is_minimal_proxy(bytecode_lower):
        return False
    
    return False


def is_minimal_proxy(bytecode_lower: str) -> bool:
    """
    Detect EIP-1167 minimal proxy pattern in bytecode.
    """
    return (
        "363d3d373d3d3d363d73" in bytecode_lower and
        "5af43d82803e903d91602b57fd5bf3" in bytecode_lower
    )
