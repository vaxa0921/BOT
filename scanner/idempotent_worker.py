"""Idempotent worker implementation."""
import hashlib
import json
from typing import Dict, Any, Set, Optional
from pathlib import Path

PROCESSED_FILE = Path("scanner/data/processed.json")


def get_work_id(address: str, work_type: str = "default") -> str:
    """
    Generate unique work ID.

    Args:
        address: Contract address
        work_type: Type of work

    Returns:
        Work ID
    """
    data = f"{address.lower()}:{work_type}"
    return hashlib.sha256(data.encode()).hexdigest()


def load_processed() -> Set[str]:
    """
    Load set of processed work IDs.

    Returns:
        Set of processed work IDs
    """
    if not PROCESSED_FILE.exists():
        return set()
    
    try:
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("processed", []))
    except Exception:
        return set()


def save_processed(work_id: str, result: Dict[str, Any]) -> None:
    """
    Save processed work ID.

    Args:
        work_id: Work ID
        result: Work result
    """
    processed = load_processed()
    processed.add(work_id)
    
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "processed": list(processed),
        "results": {work_id: result}
    }
    
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_processed(address: str, work_type: str = "default") -> bool:
    """
    Check if work was already processed.

    Args:
        address: Contract address
        work_type: Type of work

    Returns:
        True if already processed
    """
    work_id = get_work_id(address, work_type)
    processed = load_processed()
    return work_id in processed


def idempotent_work(
    address: str,
    work_function: callable,
    work_type: str = "default"
) -> Optional[Dict[str, Any]]:
    """
    Execute work idempotently.

    Args:
        address: Contract address
        work_function: Function to execute
        work_type: Type of work

    Returns:
        Work result or None if already processed
    """
    if is_processed(address, work_type):
        return None
    
    work_id = get_work_id(address, work_type)
    try:
        result = work_function(address)
    except TypeError:
        result = work_function()
    
    save_processed(work_id, result)
    
    return result
