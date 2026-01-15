"""Balance delta detection."""
from typing import Dict, List, Any, Optional
from web3 import Web3


def detect_balance_delta(
    w3: Web3,
    contract_address: str,
    token_address: Optional[str] = None,
    blocks: int = 100
) -> Dict[str, Any]:
    """
    Detect balance changes in contract.

    Args:
        w3: Web3 instance
        contract_address: Contract address to monitor
        token_address: Token address (None for ETH)
        blocks: Number of blocks to check

    Returns:
        Dictionary with balance delta information
    """
    current_block = w3.eth.block_number
    start_block = max(current_block - blocks, 0)
    
    if token_address:
        # ERC20 token balance
        abi = [{
            "constant": True,
            "inputs": [{"name": "_owner", "type": "address"}],
            "name": "balanceOf",
            "outputs": [{"name": "balance", "type": "uint256"}],
            "type": "function"
        }]
        token = w3.eth.contract(address=token_address, abi=abi)
        balance_start = token.functions.balanceOf(contract_address).call(
            block_identifier=start_block
        )
        balance_end = token.functions.balanceOf(contract_address).call()
    else:
        # ETH balance
        balance_start = w3.eth.get_balance(contract_address, block_identifier=start_block)
        balance_end = w3.eth.get_balance(contract_address)
    
    delta = balance_end - balance_start
    
    return {
        "address": contract_address,
        "token": token_address,
        "balance_start": balance_start,
        "balance_end": balance_end,
        "delta": delta,
        "blocks": blocks,
        "has_delta": delta != 0
    }


def detect_balance_anomalies(
    w3: Web3,
    addresses: List[str],
    threshold: int = 10**15  # 0.001 ETH
) -> List[Dict[str, Any]]:
    """
    Detect balance anomalies across multiple addresses.

    Args:
        w3: Web3 instance
        addresses: List of addresses to check
        threshold: Minimum delta threshold

    Returns:
        List of addresses with significant balance changes
    """
    anomalies = []
    
    for addr in addresses:
        delta_info = detect_balance_delta(w3, addr)
        if abs(delta_info["delta"]) >= threshold:
            anomalies.append(delta_info)
    
    return anomalies
