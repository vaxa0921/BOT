"""Async batch code fetcher."""
import asyncio
import aiohttp
from typing import List, Dict, Optional
from scanner.config import RPCS, BATCH_SIZE, ASYNC_CONCURRENT

logger = None


def _get_logger():
    """Lazy logger initialization."""
    global logger
    if logger is None:
        import logging
        logger = logging.getLogger(__name__)
    return logger


async def fetch_code_batch(
    addresses: List[str],
    rpc_url: str,
    session: aiohttp.ClientSession
) -> Dict[str, Optional[str]]:
    """
    Fetch code for multiple addresses in one batch.

    Args:
        addresses: List of contract addresses
        rpc_url: RPC endpoint URL
        session: aiohttp session

    Returns:
        Dictionary mapping address to bytecode (hex) or None
    """
    if not addresses:
        return {}

    # Prepare batch RPC requests
    requests = []
    for i, addr in enumerate(addresses):
        requests.append({
            "jsonrpc": "2.0",
            "id": i,
            "method": "eth_getCode",
            "params": [addr, "pending"]
        })

    try:
        async with session.post(
            rpc_url,
            json=requests,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status != 200:
                _get_logger().error(
                    f"RPC error {response.status} for {rpc_url}"
                )
                return {addr: None for addr in addresses}

            data = await response.json()
            results = {}

            # Handle both single response and batch response
            if isinstance(data, list):
                for resp in data:
                    idx = resp.get("id", 0)
                    if idx < len(addresses):
                        addr = addresses[idx]
                        code = resp.get("result")
                        results[addr] = code if code and code != "0x" else None
            else:
                # Single request fallback
                code = data.get("result")
                if addresses:
                    results[addresses[0]] = (
                        code if code and code != "0x" else None
                    )

            return results

    except Exception as e:
        _get_logger().error(f"Error fetching batch: {e}")
        return {addr: None for addr in addresses}


async def fetch_codes_async(
    addresses: List[str],
    rpc_urls: Optional[List[str]] = None
) -> Dict[str, Optional[str]]:
    """
    Fetch codes for addresses asynchronously with batching.

    Args:
        addresses: List of contract addresses
        rpc_urls: List of RPC URLs (default: from config)

    Returns:
        Dictionary mapping address to bytecode (hex) or None
    """
    if rpc_urls is None:
        rpc_urls = RPCS

    if not addresses:
        return {}

    # Split into batches
    batches = [
        addresses[i:i + BATCH_SIZE]
        for i in range(0, len(addresses), BATCH_SIZE)
    ]

    results: Dict[str, Optional[str]] = {}

    async with aiohttp.ClientSession() as session:
        # Process batches with concurrency limit
        semaphore = asyncio.Semaphore(ASYNC_CONCURRENT)
        
        async def fetch_with_semaphore(batch: List[str], rpc: str):
            async with semaphore:
                return await fetch_code_batch(batch, rpc, session)

        tasks = []
        for batch in batches:
            # Round-robin RPC selection
            rpc = rpc_urls[len(tasks) % len(rpc_urls)]
            tasks.append(fetch_with_semaphore(batch, rpc))

        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        for batch_result in batch_results:
            if isinstance(batch_result, Exception):
                _get_logger().error(f"Batch fetch error: {batch_result}")
                continue
            results.update(batch_result)

    return results


def fetch_codes_sync(addresses: List[str]) -> Dict[str, Optional[str]]:
    """
    Synchronous wrapper for async code fetching.

    Args:
        addresses: List of contract addresses

    Returns:
        Dictionary mapping address to bytecode (hex) or None
    """
    return asyncio.run(fetch_codes_async(addresses))
