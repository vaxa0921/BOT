"""Share ↔ asset conversion detection."""
from typing import Dict, Any, Optional
from web3 import Web3


def detect_share_asset_conversion(
    w3: Web3,
    contract_address: str
) -> Dict[str, Any]:
    """
    Detect share to asset conversion patterns (vaults, pools).

    Args:
        w3: Web3 instance
        contract_address: Contract address

    Returns:
        Dictionary with conversion detection results
    """
    # Common function signatures
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
        },
        {
            "constant": True,
            "inputs": [{"name": "shares", "type": "uint256"}],
            "name": "convertToAssets",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": True,
            "inputs": [{"name": "assets", "type": "uint256"}],
            "name": "convertToShares",
            "outputs": [{"name": "", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": False,
            "inputs": [{"name": "assets", "type": "uint256"}],
            "name": "deposit",
            "outputs": [{"name": "shares", "type": "uint256"}],
            "type": "function"
        },
        {
            "constant": False,
            "inputs": [{"name": "shares", "type": "uint256"}],
            "name": "withdraw",
            "outputs": [{"name": "assets", "type": "uint256"}],
            "type": "function"
        }
    ]
    
    try:
        contract = w3.eth.contract(address=contract_address, abi=abi)
        
        has_total_assets = False
        has_total_supply = False
        has_convert_to_assets = False
        has_convert_to_shares = False
        has_deposit = False
        has_withdraw = False
        
        # Check which functions exist
        try:
            contract.functions.totalAssets().call()
            has_total_assets = True
        except Exception:
            pass
        
        try:
            contract.functions.totalSupply().call()
            has_total_supply = True
        except Exception:
            pass
        
        try:
            contract.functions.convertToAssets(1).call()
            has_convert_to_assets = True
        except Exception:
            pass
        
        try:
            contract.functions.convertToShares(1).call()
            has_convert_to_shares = True
        except Exception:
            pass
        
        # Calculate conversion ratio
        ratio = None
        inflation_risk = False
        
        if has_total_assets and has_total_supply:
            try:
                assets = contract.functions.totalAssets().call()
                supply = contract.functions.totalSupply().call()
                if supply > 0:
                    ratio = assets / supply
                    # Check for inflation attack risk (Price per share is very high)
                    if ratio > 100:  # 1 share worth > 100 assets is suspicious for standard vaults
                         inflation_risk = True
                elif supply == 0 and assets > 0:
                    # Empty supply but assets exist? Strange.
                    inflation_risk = True

            except Exception:
                pass
        
        # Check for rounding
        rounding_detected = False
        if ratio:
            # Check if ratio has remainder
            if has_total_assets and has_total_supply:
                try:
                    assets = contract.functions.totalAssets().call()
                    supply = contract.functions.totalSupply().call()
                    if supply > 0 and assets % supply != 0:
                        rounding_detected = True
                except Exception:
                    pass
        
        return {
            "address": contract_address,
            "is_vault_like": (has_total_assets and has_total_supply) or has_convert_to_assets,
            "has_total_assets": has_total_assets,
            "has_total_supply": has_total_supply,
            "has_convert_to_assets": has_convert_to_assets,
            "has_convert_to_shares": has_convert_to_shares,
            "has_deposit": has_deposit,
            "has_withdraw": has_withdraw,
            "conversion_ratio": ratio,
            "rounding_detected": rounding_detected,
            "inflation_attack_risk": inflation_risk
        }
    except Exception:
        return {
            "address": contract_address,
            "is_vault_like": False,
            "has_total_assets": False,
            "has_total_supply": False,
            "has_convert_to_assets": False,
            "has_convert_to_shares": False,
            "has_deposit": False,
            "has_withdraw": False,
            "conversion_ratio": None,
            "rounding_detected": False
        }
