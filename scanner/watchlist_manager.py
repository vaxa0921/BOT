import json
import os
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)
WATCHLIST_FILE = "watchlist.json"

def load_watchlist() -> List[Dict[str, Any]]:
    if not os.path.exists(WATCHLIST_FILE):
        return []
    try:
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load watchlist: {e}")
        return []

def save_watchlist(watchlist: List[Dict[str, Any]]):
    try:
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(watchlist, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save watchlist: {e}")

def add_to_watchlist(entry: Dict[str, Any]):
    watchlist = load_watchlist()
    # Check duplicate
    for item in watchlist:
        if item["address"].lower() == entry["address"].lower():
            return # Already watched
            
    watchlist.append(entry)
    save_watchlist(watchlist)
    logger.info(f"[WATCHLIST] Added {entry['address']} ({entry.get('reason', 'unknown')})")

def remove_from_watchlist(address: str):
    watchlist = load_watchlist()
    new_list = [item for item in watchlist if item["address"].lower() != address.lower()]
    if len(new_list) != len(watchlist):
        save_watchlist(new_list)
        logger.info(f"[WATCHLIST] Removed {address}")
