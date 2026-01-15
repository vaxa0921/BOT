"""Multi-transaction accumulation detector."""
from typing import Dict, List, Any, Optional
from collections import defaultdict


def detect_multi_tx_accumulation(
    transactions: List[Dict[str, Any]],
    target_address: str
) -> Dict[str, Any]:
    """
    Detect accumulation patterns across multiple transactions.

    Args:
        transactions: List of transaction data
        target_address: Address to monitor

    Returns:
        Dictionary with accumulation detection results
    """
    accumulations = defaultdict(list)
    
    for tx in transactions:
        tx_type = tx.get("type", "unknown")
        from_addr = tx.get("from", "").lower()
        to_addr = tx.get("to", "").lower()
        amount = tx.get("value", 0) or tx.get("amount", 0)
        
        if to_addr == target_address.lower():
            accumulations[from_addr].append({
                "tx_hash": tx.get("hash", ""),
                "amount": amount,
                "block": tx.get("block", 0)
            })
    
    # Find addresses with multiple transactions
    multi_tx_addresses = {
        addr: txs for addr, txs in accumulations.items()
        if len(txs) >= 2
    }
    
    # Calculate total accumulation per address
    accumulation_totals = {}
    for addr, txs in multi_tx_addresses.items():
        total = sum(tx["amount"] for tx in txs)
        accumulation_totals[addr] = {
            "address": addr,
            "tx_count": len(txs),
            "total_amount": total,
            "transactions": txs
        }
    
    return {
        "target_address": target_address,
        "multi_tx_addresses": list(multi_tx_addresses.keys()),
        "accumulation_count": len(multi_tx_addresses),
        "accumulations": accumulation_totals,
        "has_accumulation": len(multi_tx_addresses) > 0
    }


def detect_rounding_accumulation(
    operations: List[Dict[str, Any]],
    threshold: int = 10**12  # 0.000001 ETH
) -> Dict[str, Any]:
    """
    Detect accumulation of rounding errors.

    Args:
        operations: List of operations
        threshold: Minimum accumulated dust

    Returns:
        Dictionary with rounding accumulation results
    """
    total_accumulated = 0
    accumulation_events = []
    
    for op in operations:
        remainder = op.get("remainder", 0)
        if remainder > 0:
            total_accumulated += remainder
            accumulation_events.append({
                "operation": op.get("type", "unknown"),
                "remainder": remainder,
                "block": op.get("block", 0)
            })
    
    return {
        "total_accumulated": total_accumulated,
        "accumulation_events": accumulation_events,
        "event_count": len(accumulation_events),
        "exceeds_threshold": total_accumulated >= threshold,
        "has_accumulation": total_accumulated > 0
    }
