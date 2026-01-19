"""Idempotent worker implementation."""
import time
import hashlib
import json
from typing import Dict, Any, Set, Optional, Tuple
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


def load_processed_data() -> Tuple[Set[str], Dict[str, float], Dict[str, Any]]:
    """
    Load processed data (ids, timestamps, results).

    Returns:
        Tuple of (processed_ids, timestamps, results)
    """
    if not PROCESSED_FILE.exists():
        return set(), {}, {}
    
    try:
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            processed = set(data.get("processed", []))
            timestamps = data.get("timestamps", {})
            results = data.get("results", {})
            return processed, timestamps, results
    except Exception:
        return set(), {}, {}


def save_processed(work_id: str, result: Dict[str, Any]) -> None:
    """
    Save processed work ID with timestamp.

    Args:
        work_id: Work ID
        result: Work result
    """
    processed, timestamps, results = load_processed_data()
    processed.add(work_id)
    timestamps[work_id] = time.time()
    results[work_id] = result
    
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "processed": list(processed),
        "timestamps": timestamps,
        "results": results
    }
    
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_processed(address: str, work_type: str = "default", ttl: int = 0) -> bool:
    """
    Check if work was already processed.

    Args:
        address: Contract address
        work_type: Type of work
        ttl: Time to live in seconds (0 = infinite/forever)

    Returns:
        True if already processed and valid (within TTL)
    """
    work_id = get_work_id(address, work_type)
    processed, timestamps, _ = load_processed_data()
    
    if work_id not in processed:
        return False
        
    if ttl > 0:
        last_ts = timestamps.get(work_id, 0)
        if time.time() - last_ts > ttl:
            return False
            
    return True


def idempotent_work(
    address: str,
    work_function: callable,
    work_type: str = "default",
    ttl: int = 0
) -> Optional[Dict[str, Any]]:
    """
    Execute work idempotently.

    Args:
        address: Contract address
        work_function: Function to execute
        work_type: Type of work
        ttl: Time to live in seconds

    Returns:
        Work result or None if already processed
    """
    if is_processed(address, work_type, ttl):
        return None
    
    work_id = get_work_id(address, work_type)
    try:
        result = work_function(address)
    except TypeError:
        result = work_function()
    
    save_processed(work_id, result)
    
    return result
