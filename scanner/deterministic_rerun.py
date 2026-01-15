"""Deterministic reruns for verification."""
import hashlib
import json
from typing import Dict, Any, Optional
from pathlib import Path

RERUN_CACHE = Path("scanner/data/rerun_cache.json")


def get_finding_hash(finding: Dict[str, Any]) -> str:
    """
    Get deterministic hash for finding.

    Args:
        finding: Finding dictionary

    Returns:
        Hash string
    """
    # Create deterministic representation
    key_data = {
        "address": finding.get("address", "").lower(),
        "class": finding.get("class", ""),
        "description": finding.get("description", "")
    }
    
    data_str = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(data_str.encode()).hexdigest()


def load_rerun_cache() -> Dict[str, Dict[str, Any]]:
    """
    Load rerun cache.

    Returns:
        Dictionary mapping hash to result
    """
    if not RERUN_CACHE.exists():
        return {}
    
    try:
        with open(RERUN_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_rerun_result(
    finding_hash: str,
    result: Dict[str, Any]
) -> None:
    """
    Save rerun result to cache.

    Args:
        finding_hash: Finding hash
        result: Rerun result
    """
    cache = load_rerun_cache()
    cache[finding_hash] = result
    
    RERUN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(RERUN_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def should_rerun(
    finding: Dict[str, Any],
    min_confidence: float = 0.8
) -> bool:
    """
    Determine if finding should be rerun.

    Args:
        finding: Finding dictionary
        min_confidence: Minimum confidence to skip rerun

    Returns:
        True if should rerun
    """
    confidence = finding.get("confidence", 0.0)
    
    if confidence >= min_confidence:
        return False
    
    finding_hash = get_finding_hash(finding)
    cache = load_rerun_cache()
    
    if finding_hash in cache:
        cached_result = cache[finding_hash]
        cached_confidence = cached_result.get("confidence", 0.0)
        
        if cached_confidence >= min_confidence:
            return False
    
    return True


def deterministic_rerun(
    finding: Dict[str, Any],
    rerun_function: callable
) -> Dict[str, Any]:
    """
    Perform deterministic rerun of finding.

    Args:
        finding: Finding dictionary
        rerun_function: Function to rerun analysis

    Returns:
        Rerun result
    """
    finding_hash = get_finding_hash(finding)
    cache = load_rerun_cache()
    
    # Check cache first
    if finding_hash in cache:
        return cache[finding_hash]
    
    # Perform rerun
    result = rerun_function(finding)
    
    # Save to cache
    save_rerun_result(finding_hash, result)
    
    return result
