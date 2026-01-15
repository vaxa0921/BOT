"""State-transition model for contract analysis."""
from typing import Dict, List, Any, Optional, Set
from web3 import Web3


class StateTransition:
    """Represents a state transition in a contract."""
    
    def __init__(
        self,
        block_number: int,
        transaction_hash: str,
        from_state: Dict[str, Any],
        to_state: Dict[str, Any],
        operation: str
    ):
        self.block_number = block_number
        self.transaction_hash = transaction_hash
        self.from_state = from_state
        self.to_state = to_state
        self.operation = operation
    
    def get_delta(self) -> Dict[str, Any]:
        """Calculate state delta."""
        delta = {}
        all_keys = set(self.from_state.keys()) | set(self.to_state.keys())
        
        for key in all_keys:
            from_val = self.from_state.get(key, 0)
            to_val = self.to_state.get(key, 0)
            delta[key] = to_val - from_val
        
        return delta


def track_state_transitions(
    w3: Web3,
    contract_address: str,
    state_variables: List[str],
    blocks: int = 100
) -> List[StateTransition]:
    """
    Track state transitions for a contract.

    Args:
        w3: Web3 instance
        contract_address: Contract address
        state_variables: List of state variable names to track
        blocks: Number of blocks to analyze

    Returns:
        List of state transitions
    """
    current_block = w3.eth.block_number
    from_block = max(current_block - blocks, 0)
    
    transitions = []
    
    # Get contract events
    try:
        # Generic Transfer event for state changes
        abi = [{
            "anonymous": False,
            "inputs": [
                {"indexed": True, "name": "from", "type": "address"},
                {"indexed": True, "name": "to", "type": "address"},
                {"indexed": False, "name": "value", "type": "uint256"}
            ],
            "name": "Transfer",
            "type": "event"
        }]
        
        contract = w3.eth.contract(address=contract_address, abi=abi)
        events = contract.events.Transfer.get_logs(
            fromBlock=from_block,
            toBlock=current_block
        )
        
        for event in events:
            # Get state before and after
            block_before = event.blockNumber - 1
            block_after = event.blockNumber
            
            from_state = {}
            to_state = {}
            
            # Read state variables (simplified - would need ABI)
            try:
                # This is a placeholder - real implementation needs ABI
                from_state["balance"] = w3.eth.get_balance(
                    contract_address,
                    block_identifier=block_before
                )
                to_state["balance"] = w3.eth.get_balance(
                    contract_address,
                    block_identifier=block_after
                )
            except Exception:
                pass
            
            transition = StateTransition(
                block_number=event.blockNumber,
                transaction_hash=event.transactionHash.hex(),
                from_state=from_state,
                to_state=to_state,
                operation="transfer"
            )
            transitions.append(transition)
    except Exception:
        pass
    
    return transitions


def detect_invariant_violations(
    transitions: List[StateTransition],
    invariants: List[callable]
) -> List[Dict[str, Any]]:
    """
    Detect invariant violations in state transitions.

    Args:
        transitions: List of state transitions
        invariants: List of invariant check functions

    Returns:
        List of violations
    """
    violations = []
    
    for transition in transitions:
        for invariant in invariants:
            try:
                if not invariant(transition):
                    violations.append({
                        "block": transition.block_number,
                        "tx": transition.transaction_hash,
                        "invariant": invariant.__name__,
                        "from_state": transition.from_state,
                        "to_state": transition.to_state
                    })
            except Exception:
                pass
    
    return violations
