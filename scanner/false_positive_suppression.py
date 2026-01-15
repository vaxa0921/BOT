"""False-positive suppression."""
from typing import Dict, List, Any, Set
from collections import defaultdict
import json
from pathlib import Path

FALSE_POSITIVE_FILE = Path("scanner/data/false_positives.json")


def load_false_positives() -> Set[str]:
    """
    Load known false positives.

    Returns:
        Set of false positive identifiers
    """
    if not FALSE_POSITIVE_FILE.exists():
        return set()
    
    try:
        with open(FALSE_POSITIVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("addresses", []))
    except Exception:
        return set()


def save_false_positive(address: str, reason: str) -> None:
    """
    Save a false positive.

    Args:
        address: Contract address
        reason: Reason for false positive
    """
    false_positives = load_false_positives()
    false_positives.add(address.lower())
    
    FALSE_POSITIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "addresses": list(false_positives),
        "reasons": {address.lower(): reason}
    }
    
    with open(FALSE_POSITIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_false_positive(
    address: str,
    finding: Dict[str, Any]
) -> bool:
    """
    Check if finding is a known false positive.

    Args:
        address: Contract address
        finding: Finding data

    Returns:
        True if false positive
    """
    false_positives = load_false_positives()
    
    if address.lower() in false_positives:
        return True
    
    # Check for common false positive patterns
    finding_class = finding.get("class", "").lower()
    
    # Known false positive classes
    fp_classes = [
        "expected_behavior",
        "by_design",
        "insufficient_funds"
    ]
    
    if any(fp in finding_class for fp in fp_classes):
        return True
    
    return False


def suppress_false_positives(
    findings: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Filter out false positives from findings.

    Args:
        findings: List of findings

    Returns:
        Filtered findings
    """
    filtered = []
    
    for finding in findings:
        address = finding.get("address", "")
        if not is_false_positive(address, finding):
            filtered.append(finding)
    
    return filtered
