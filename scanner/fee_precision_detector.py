"""Fee and precision math detection."""
from typing import Dict, Any, List, Optional
from web3 import Web3


def detect_fee_precision_math(
    w3: Web3,
    contract_address: str
) -> Dict[str, Any]:
    """
    Detect fee and precision math operations.

    Args:
        w3: Web3 instance
        contract_address: Contract address

    Returns:
        Dictionary with fee/precision detection results
    """
    # Common fee-related function signatures
    abi = [
        {
            "constant": True,
            "inputs": [],
            "name": "fee",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [],
            "name": "protocolFee",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [{"name": "amount", "type": "uint256"}],
            "name": "calculateFee",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        }
    ]
    
    try:
        contract = w3.eth.contract(address=contract_address, abi=abi)
        
        fee_value = None
        has_fee = False
        has_calculate_fee = False
        
        # Check for fee function
        try:
            fee_value = contract.functions.fee().call()
            has_fee = True
        except Exception:
            try:
                fee_value = contract.functions.protocolFee().call()
                has_fee = True
            except Exception:
                pass
        
        # Check for calculateFee function
        try:
            test_amount = 1000000
            contract.functions.calculateFee(test_amount).call()
            has_calculate_fee = True
        except Exception:
            pass
        
        # Analyze bytecode for fee calculations
        code = w3.eth.get_code(contract_address).hex()
        precision_issues = []
        
        # Look for division patterns that might cause precision loss
        if "div" in code.lower() or "sdiv" in code.lower():
            # Check for patterns like: amount * fee / 10000
            # This is a heuristic - real analysis needs bytecode parsing
            precision_issues.append("division_operation_detected")
        
        return {
            "address": contract_address,
            "has_fee": has_fee,
            "fee_value": fee_value,
            "has_calculate_fee": has_calculate_fee,
            "precision_issues": precision_issues,
            "potential_rounding": len(precision_issues) > 0
        }
    except Exception:
        return {
            "address": contract_address,
            "has_fee": False,
            "fee_value": None,
            "has_calculate_fee": False,
            "precision_issues": [],
            "potential_rounding": False
        }
