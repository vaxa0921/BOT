"""Analyzer for detecting rounding issues in contracts."""
from typing import Dict, Optional, Any
from web3 import Web3


def detect_rounding(w3: Web3, addr: str) -> Optional[Dict[str, Any]]:
    """
    Detect rounding issues in a contract.

    Args:
        w3: Web3 instance
        addr: Contract address

    Returns:
        Dictionary with price and dust if rounding detected, None otherwise
    """
    abi = [
        {"name": "deposit", "type": "function",
         "inputs": [{"type": "uint256"}]},
        {"name": "withdraw", "type": "function",
         "inputs": [{"type": "uint256"}]},
        {"name": "totalAssets", "type": "function",
         "outputs": [{"type": "uint256"}]},
        {"name": "totalSupply", "type": "function",
         "outputs": [{"type": "uint256"}]},
    ]
    contract = w3.eth.contract(address=addr, abi=abi)
    try:
        assets = contract.functions.totalAssets().call()
        supply = contract.functions.totalSupply().call()
        if supply == 0:
            return None
        price = assets // supply
        if assets % supply != 0:
            return {"price": price, "dust": assets % supply}
    except Exception:
        return None
    return None
