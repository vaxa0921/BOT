"""Bounty submission formatter."""
import json
from typing import Dict, Any, List, Tuple
from pathlib import Path
from scanner.real_poc_generator import create_exploit_script

SUBMISSIONS_DIR = Path("scanner/reports/submissions")


def format_bounty_submission(finding: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format finding for bounty submission.

    Args:
        finding: Finding dictionary

    Returns:
        Formatted submission
    """
    address = finding.get("address", "")
    impact = finding.get("impact", {})
    signals = finding.get("signals", {})
    poc = finding.get("poc", {})
    
    submission = {
        "title": f"Rounding Vulnerability in {address[:10]}...{address[-8:]}",
        "severity": finding.get("severity", 0),
        "contract_address": address,
        "vulnerability_type": "Rounding / Precision Loss",
        "description": _generate_description(finding),
        "impact": {
            "stolen_wei": impact.get("stolen_wei", 0),
            "stolen_eth": impact.get("stolen_wei", 0) / 10**18,
            "tvl_wei": impact.get("tvl_wei", 0),
            "percentage_loss": impact.get("percentage_loss", 0),
            "impact_level": impact.get("impact_level", "UNKNOWN")
        },
        "proof_of_concept": {
            "exploit_steps": poc.get("exploit_steps", []),
            "test_file": poc.get("test_file"),
            "markdown": create_exploit_script(finding)
        },
        "steps_to_reproduce": _generate_steps(finding),
        "recommended_fix": _generate_fix_recommendation(finding),
        "additional_info": {
            "signals": signals,
            "findings": finding.get("findings", []),
            "timestamp": finding.get("timestamp", 0)
        }
    }
    
    return submission


def _generate_description(finding: Dict[str, Any]) -> str:
    """Generate vulnerability description."""
    address = finding.get("address", "")
    impact = finding.get("impact", {})
    
    return f"""
The contract at {address} contains a rounding vulnerability that allows 
an attacker to accumulate dust/remainder through repeated operations.

**Impact:**
- Potential loss: {impact.get('stolen_wei', 0) / 10**18:.6f} ETH
- Percentage of TVL: {impact.get('percentage_loss', 0):.2f}%

The vulnerability occurs due to improper handling of rounding in arithmetic 
operations, particularly in share-to-asset conversions or fee calculations.
"""


def _generate_steps(finding: Dict[str, Any]) -> List[str]:
    """Generate steps to reproduce."""
    poc = finding.get("poc", {})
    steps = poc.get("exploit_steps", [])
    
    if not steps:
        return [
            "1. Fork mainnet using Foundry",
            "2. Deploy exploit contract",
            "3. Execute rounding exploit",
            "4. Verify profit accumulation"
        ]
    
    return [
        f"{i+1}. {step.get('description', f'Step {i+1}')}"
        for i, step in enumerate(steps)
    ]


def _generate_fix_recommendation(finding: Dict[str, Any]) -> str:
    """Generate fix recommendation."""
    return """
**Recommended Fix:**

1. Use proper rounding (round up for user withdrawals, round down for deposits)
2. Track and accumulate dust explicitly in a separate variable
3. Periodically sweep accumulated dust to a designated address
4. Use libraries like OpenZeppelin's SafeMath for arithmetic operations
5. Consider using higher precision (e.g., 1e27 instead of 1e18) for calculations

Example fix:
```solidity
// Instead of: shares = assets * totalSupply / totalAssets
// Use: shares = (assets * totalSupply + totalAssets - 1) / totalAssets  // Round up
```
"""


def save_submission(finding: Dict[str, Any]) -> Path:
    """
    Save bounty submission to file.

    Args:
        finding: Finding dictionary

    Returns:
        Path to saved submission
    """
    SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    submission = format_bounty_submission(finding)
    address = finding.get("address", "unknown")
    
    # Save JSON
    json_file = SUBMISSIONS_DIR / f"{address}_submission.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(submission, f, indent=2)
    
    # Save Markdown
    md_file = SUBMISSIONS_DIR / f"{address}_submission.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(submission["proof_of_concept"]["markdown"])
    
    return json_file


def validate_submission(finding: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate finding before submission.

    Args:
        finding: Finding dictionary

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    if not finding.get("address"):
        errors.append("Missing contract address")
    
    impact = finding.get("impact", {})
    if impact.get("stolen_wei", 0) < 10**17:  # Less than 0.1 ETH
        errors.append("Impact too low (< 0.1 ETH)")
    
    if finding.get("severity", 0) < 7:
        errors.append("Severity too low (< 7)")
    
    poc = finding.get("poc", {})
    if not poc.get("exploit_steps"):
        errors.append("Missing proof of concept")
    
    return (len(errors) == 0, errors)
