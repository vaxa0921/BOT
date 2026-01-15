"""Remainder / dust tracking."""
from typing import Dict, List, Any, Optional
from web3 import Web3


def track_dust_accumulation(
    w3: Web3,
    contract_address: str,
    operations: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Track dust accumulation from rounding operations.

    Args:
        w3: Web3 instance
        contract_address: Contract address
        operations: List of operations with amounts

    Returns:
        Dictionary with dust tracking results
    """
    total_dust = 0
    dust_events = []
    
    for op in operations:
        amount_in = op.get("amount_in", 0)
        amount_out = op.get("amount_out", 0)
        expected_out = op.get("expected_out", 0)
        
        if expected_out > 0:
            remainder = expected_out - amount_out
            if remainder > 0:
                total_dust += remainder
                dust_events.append({
                    "operation": op.get("type", "unknown"),
                    "expected": expected_out,
                    "actual": amount_out,
                    "dust": remainder,
                    "block": op.get("block", 0)
                })
    
    return {
        "address": contract_address,
        "total_dust": total_dust,
        "dust_events": dust_events,
        "dust_count": len(dust_events),
        "has_dust": total_dust > 0
    }


def calculate_remainder(
    numerator: int,
    denominator: int
) -> int:
    """
    Calculate remainder from division.

    Args:
        numerator: Numerator
        denominator: Denominator

    Returns:
        Remainder
    """
    if denominator == 0:
        return 0
    return numerator % denominator


def detect_rounding_dust(
    w3: Web3,
    contract_address: str
) -> Dict[str, Any]:
    """
    Detect rounding dust in contract operations.

    Args:
        w3: Web3 instance
        contract_address: Contract address

    Returns:
        Dictionary with dust detection results
    """
    # Check for vault-like contracts
    abi = [
        {
            "constant": True,
            "inputs": [],
            "name": "totalAssets",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [],
            "name": "totalSupply",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        }
    ]
    
    try:
        contract = w3.eth.contract(address=contract_address, abi=abi)
        
        assets = contract.functions.totalAssets().call()
        supply = contract.functions.totalSupply().call()
        
        if supply > 0:
            remainder = calculate_remainder(assets, supply)
            price_per_share = assets // supply
            
            return {
                "address": contract_address,
                "total_assets": assets,
                "total_supply": supply,
                "price_per_share": price_per_share,
                "remainder": remainder,
                "has_dust": remainder > 0,
                "dust_wei": remainder
            }
    except Exception:
        pass
    
    return {
        "address": contract_address,
        "total_assets": 0,
        "total_supply": 0,
        "price_per_share": 0,
        "remainder": 0,
        "has_dust": False,
        "dust_wei": 0
    }
