"""Verified contracts ingestion and source fetching (Etherscan/BaseScan)."""
import os
import time
import requests
from typing import List, Set, Optional
from scanner.contract_queue import enqueue
from scanner.config import BASESCAN_API_KEY

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")


def fetch_verified_contracts(
    start_page: int = 1,
    pages: int = 100,
    delay: float = 0.25
) -> List[str]:
    """
    Fetch verified contract addresses from Etherscan.

    Args:
        start_page: Starting page number
        pages: Number of pages to fetch
        delay: Delay between requests (seconds)

    Returns:
        List of contract addresses
    """
    addresses: Set[str] = set()
    
    if not ETHERSCAN_API_KEY:
        return []
    
    for page in range(start_page, start_page + pages):
        url = "https://api.basescan.org/api"
        params = {
            "module": "contract",
            "action": "listcontracts",
            "startblock": 0,
            "endblock": 99999999,
            "page": page,
            "offset": 100,
            "apikey": BASESCAN_API_KEY
        }
        
        try:
            response = requests.get(url, params=params, timeout=15)
            data = response.json()
            
            if data.get("status") != "1":
                break
            
            for item in data.get("result", []):
                addr = item.get("contractAddress")
                if addr:
                    addresses.add(addr.lower())
                    enqueue(addr)
            
            time.sleep(delay)
            
        except Exception as e:
            print(f"[VERIFIED] Error on page {page}: {e}")
            break
    
    return list(addresses)


def ingest_verified_contracts() -> int:
    """
    Main ingestion function for verified contracts.

    Returns:
        Number of contracts ingested
    """
    addresses = fetch_verified_contracts()
    return len(addresses)

def fetch_basescan_source(
    address: str
) -> Optional[str]:
    """
    Fetch verified source code from BaseScan if available.
    """
    api_key = BASESCAN_API_KEY or os.getenv("BASESCAN_API_KEY", "")
    if not api_key:
        return None
    try:
        url = "https://api.basescan.org/api"
        params = {
            "module": "contract",
            "action": "getsourcecode",
            "address": address,
            "apikey": api_key
        }
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
        if data.get("status") != "1":
            return None
        result = data.get("result", [])
        if not result:
            return None
        source = result[0].get("SourceCode") or ""
        return source if source else None
    except Exception:
        return None


if __name__ == "__main__":
    count = ingest_verified_contracts()
    print(f"[VERIFIED] Ingested {count} verified contracts")
