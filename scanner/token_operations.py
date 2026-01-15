"""Mint / burn / transfer detection."""
from typing import Dict, List, Any, Optional, Set
from web3 import Web3


def detect_mint_burn_transfer(
    w3: Web3,
    contract_address: str,
    blocks: int = 1000
) -> Dict[str, Any]:
    """
    Detect mint, burn, and transfer operations.

    Args:
        w3: Web3 instance
        contract_address: Contract address
        blocks: Number of blocks to scan

    Returns:
        Dictionary with detected operations
    """
    current_block = w3.eth.block_number
    from_block = max(current_block - blocks, 0)
    
    # ERC20 Transfer event
    transfer_abi = [{
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"}
        ],
        "name": "Transfer",
        "type": "event"
    }]
    
    try:
        contract = w3.eth.contract(address=contract_address, abi=transfer_abi)
        events = contract.events.Transfer.get_logs(
            fromBlock=from_block,
            toBlock=current_block
        )
        
        mints = []
        burns = []
        transfers = []
        zero_address = "0x0000000000000000000000000000000000000000"
        
        for event in events:
            from_addr = event.args.get("from", "").lower()
            to_addr = event.args.get("to", "").lower()
            value = event.args.get("value", 0)
            
            if from_addr == zero_address:
                mints.append({"to": to_addr, "value": value, "block": event.blockNumber})
            elif to_addr == zero_address:
                burns.append({"from": from_addr, "value": value, "block": event.blockNumber})
            else:
                transfers.append({
                    "from": from_addr,
                    "to": to_addr,
                    "value": value,
                    "block": event.blockNumber
                })
        
        return {
            "address": contract_address,
            "mints": mints,
            "burns": burns,
            "transfers": transfers,
            "mint_count": len(mints),
            "burn_count": len(burns),
            "transfer_count": len(transfers),
            "has_mint": len(mints) > 0,
            "has_burn": len(burns) > 0,
            "has_transfer": len(transfers) > 0
        }
    except Exception:
        return {
            "address": contract_address,
            "mints": [],
            "burns": [],
            "transfers": [],
            "mint_count": 0,
            "burn_count": 0,
            "transfer_count": 0,
            "has_mint": False,
            "has_burn": False,
            "has_transfer": False
        }
