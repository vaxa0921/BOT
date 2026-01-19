"""Block watcher for new contract deployments."""
import time
import logging
import asyncio
from typing import Optional, List, Any
from web3 import Web3, AsyncWeb3
try:
    from web3.providers.async_rpc import AsyncHTTPProvider, AsyncWebsocketProvider
except Exception:
    from web3.providers.async_rpc import AsyncHTTPProvider
    AsyncWebsocketProvider = None
from scanner.contract_queue import enqueue, enqueue_priority
from scanner.config import RPCS, RPCS_WS, USE_WS, MAX_LOG_RANGE_BLOCKS, BLOCK_LAG as CONFIG_BLOCK_LAG, LARGE_TRANSFER_THRESHOLD_WEI
from scanner.watchlist_manager import load_watchlist
from scanner.worker import process_contract
from scanner.sniper import snipe_inflation_attack

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHER] %(message)s"
)

BLOCK_LAG: int = CONFIG_BLOCK_LAG
POLL_INTERVAL: int = 0.5
BLOCK_BATCH_SIZE: int = min(3, MAX_LOG_RANGE_BLOCKS)  # Fetch multiple blocks at once

logger = logging.getLogger(__name__)


def watch(w3: Web3) -> None:
    """
    Watch for new contract deployments and enqueue them.
    Uses async implementation for faster block fetching.
    
    Args:
        w3: Web3 instance (sync, used for initial setup/compat)
    """
    logger.info("Watcher started (Sync Fallback for Stability)")
    # _watch_sync(w3)
    try:
        asyncio.run(_watch_async())
    except Exception as e:
        logger.error(f"Async watcher failed: {e}. Falling back to sync.")
        _watch_sync(w3)


async def _watch_async() -> None:
    """Async implementation of block watcher."""
    use_ws = bool(USE_WS and RPCS_WS and AsyncWebsocketProvider)
    rpc_index = 0
    provider = AsyncWebsocketProvider(RPCS_WS[rpc_index]) if use_ws else AsyncHTTPProvider(RPCS[rpc_index])
    async_w3 = AsyncWeb3(provider)
    if not await async_w3.is_connected():
        raise ConnectionError("Cannot connect to async RPC")
        
    last_block = await async_w3.eth.block_number
    pending_seen: set[str] = set()
    pair_topic = Web3.keccak(text="PairCreated(address,address,address,uint256)").hex()
    pool_topic = Web3.keccak(text="PoolCreated(address,address,uint24,int24,address)").hex()
    mint_topic = Web3.keccak(text="Transfer(address,address,uint256)").hex()
    
    # Factory Topics for Vaults/Proxies
    new_vault_topic = "0x4241302c393c713e690702c4a45a57e93cef59aa8c6e2358495853b3420551d8" # NewVault(address,address)
    vault_created_topic = "0x5d9c31ffa0fecffd7cf379989a3c7af252f0335e0d2a1320b55245912c781f53" # VaultCreated(address,address)
    proxy_created_topic = "0x00fffc2da0b561cae30d9826d37709e9421c4725faebc226cbbb7ef5fc5e7349" # ProxyCreated(address)
    proxy_created_2_topic = "0x9678a1e87ca9f1a37dc659a97b39d812d98cd236947e1b53b3d0d6fd346acb6e" # ProxyCreated(address,address)

    zero_topic = "0x0000000000000000000000000000000000000000000000000000000000000000"
    
    # Cache watchlist
    watchlist_addrs = set()
    last_wl_update = 0
    backoff = 0.5
    
    while True:
        # Update watchlist cache
        now_ts = time.time()
        if now_ts - last_wl_update > 10:
            try:
                wl = load_watchlist()
                watchlist_addrs = {w["address"].lower() for w in wl}
                last_wl_update = now_ts
            except Exception:
                pass

        try:
            # Fast path: poll pending block frequently to catch deployments early
            try:
                pending_block = await async_w3.eth.get_block("pending", full_transactions=True)
                if pending_block and getattr(pending_block, "transactions", None):
                    for tx in pending_block.transactions:
                        if tx.to is None:
                            # Try to fetch receipt; if not yet mined, skip
                            try:
                                rec = await async_w3.eth.get_transaction_receipt(tx.hash)
                                if rec and rec.contractAddress and rec.contractAddress not in pending_seen:
                                    pending_seen.add(rec.contractAddress)
                                    enqueue(rec.contractAddress)
                                    logger.info(f"[PENDING] New contract (mined): {rec.contractAddress}")
                            except Exception:
                                # Not mined yet; will be caught in newHeads path below
                                pass
            except Exception as e:
                logger.debug(f"Pending block poll error: {e}")

            current = await async_w3.eth.block_number
            
            if current <= last_block + BLOCK_LAG:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            
            # Calculate range to fetch
            start_block = last_block + 1
            # Ensure we never exceed provider getLogs range limits
            max_range = max(int(MAX_LOG_RANGE_BLOCKS), 1)
            end_block = min(current - BLOCK_LAG, start_block + min(BLOCK_BATCH_SIZE, max_range) - 1)
            
            if start_block > end_block:
                continue

            # Fetch blocks concurrently
            tasks = []
            for b in range(start_block, end_block + 1):
                tasks.append(async_w3.eth.get_block(b, full_transactions=True))
            
            blocks = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Poll logs for PairCreated/PoolCreated/Transfer(Mint) in the same range
            try:
                logs = await async_w3.eth.get_logs({
                    "fromBlock": start_block,
                    "toBlock": end_block,
                    "topics": [[pair_topic, pool_topic, mint_topic, new_vault_topic, vault_created_topic, proxy_created_topic, proxy_created_2_topic]]
                })
                for log in logs:
                    addr_fields = []
                    
                    try:
                        topics = log.get("topics", [])
                        if len(topics) > 0:
                            sig = topics[0].hex()
                            
                            # 1. NewVault / VaultCreated
                            if sig == new_vault_topic or sig == vault_created_topic:
                                # usually vault is topic 1
                                if len(topics) > 1:
                                    vault = Web3.to_checksum_address("0x" + topics[1].hex()[-40:])
                                    enqueue_priority(vault)
                                    logger.info(f"[FACTORY] New Vault detected via Event: {vault}")
                                    
                                    # SNIPER: Instant First Deposit Check
                                    try:
                                        loop = asyncio.get_running_loop()
                                        loop.run_in_executor(None, snipe_inflation_attack, Web3(Web3.HTTPProvider(RPCS[0])), vault)
                                    except Exception as e:
                                        logger.error(f"[SNIPER] Failed to trigger inflation sniper: {e}")
                                    continue
                            
                            # 2. ProxyCreated
                            if sig == proxy_created_topic: # ProxyCreated(address proxy)
                                if len(topics) > 1:
                                    proxy = Web3.to_checksum_address("0x" + topics[1].hex()[-40:])
                                    enqueue_priority(proxy)
                                    logger.info(f"[FACTORY] New Proxy detected via Event: {proxy}")
                                    continue

                            if sig == proxy_created_2_topic: # ProxyCreated(address impl, address proxy)
                                if len(topics) > 2:
                                    proxy = Web3.to_checksum_address("0x" + topics[2].hex()[-40:])
                                    enqueue_priority(proxy)
                                    logger.info(f"[FACTORY] New Proxy detected via Event: {proxy}")
                                    continue

                            # 3. Mint detection: Transfer(from=0, to=X, val)
                            if sig == mint_topic:
                                # topic1 is from, topic2 is to
                                if len(topics) > 2:
                                    receiver = Web3.to_checksum_address("0x" + topics[2].hex()[-40:])
                                    
                                    # Check Watchlist Sniper
                                    if receiver.lower() in watchlist_addrs:
                                        logger.warning(f"[SNIPER] Watchlist target {receiver} received funds! Triggering exploit...")
                                        try:
                                            loop = asyncio.get_running_loop()
                                            loop.run_in_executor(None, process_contract, Web3(Web3.HTTPProvider(RPCS[0])), receiver)
                                        except Exception as e:
                                            logger.error(f"[SNIPER] Failed to trigger worker: {e}")

                                    # Check for Mint (from=0)
                                    if topics[1].hex() == zero_topic:
                                        enqueue_priority(receiver)
                                        # logger.info(f"[MINT] Mint detected to {receiver}")
                                        continue
                                    
                                    # Check for Large Transfer
                                    data_hex = log.get("data", "0x")
                                    if data_hex and data_hex != "0x":
                                        try:
                                            val = int(data_hex, 16)
                                            if val >= LARGE_TRANSFER_THRESHOLD_WEI:
                                                receiver = Web3.to_checksum_address("0x" + topics[2].hex()[-40:])
                                                enqueue_priority(receiver)
                                                # logger.info(f"[TRANSFER] Large transfer to {receiver}")
                                                continue
                                        except Exception:
                                            pass

                                continue # Skip standard pair logic for mints/transfers
                    except Exception:
                        pass

                    try:
                        if "address" in log and log["address"]:
                            addr_fields.append(log["address"])
                    except Exception:
                        pass
                    for a in addr_fields:
                        try:
                            enqueue(Web3.to_checksum_address(a))
                        except Exception:
                            continue
                    logger.info(f"[FACTORY] Pair/Pool/Mint event detected in blocks {start_block}-{end_block}")
            except Exception as e:
                logger.debug(f"Log poll error: {e}")
            
            for block in blocks:
                if isinstance(block, Exception):
                    logger.error(f"Error fetching block: {block}")
                    continue
                
                if not block:
                    continue

                # Process transactions
                # Optimization: Check if 'to' is None (contract creation)
                # This is much faster than getting receipt for every tx
                
                # Note: Internal transactions (factory deployments) are missed here.
                # To catch factory deployments, we would need trace_block (expensive/unavailable on public RPCs)
                # or filter logs for 'ContractCreated' events if emitted by factories.
                
                # For standard deployments:
                for tx in block.transactions:
                    if tx.to is None:
                        # Fetch receipt to get address
                        # We do this individually or could batch if needed
                        try:
                            receipt = await async_w3.eth.get_transaction_receipt(tx.hash)
                            if receipt.contractAddress:
                                enqueue(receipt.contractAddress)
                                logger.info(f"Found new contract: {receipt.contractAddress}")
                        except Exception as e:
                            logger.error(f"Error fetching receipt: {e}")
                    elif tx.value >= LARGE_TRANSFER_THRESHOLD_WEI:
                        try:
                            enqueue_priority(tx.to)
                            logger.info(f"[WHALE] Large transfer detected to {tx.to} ({tx.value/10**18:.2f} ETH)")
                        except Exception:
                            pass

            last_block = end_block
            backoff = 0.5
            
        except Exception as e:
            msg = str(e)
            logger.error(f"Async watcher error: {e}")
            if "429" in msg or "Too Many Requests" in msg:
                await asyncio.sleep(backoff)
                if backoff < 30.0:
                    backoff *= 2.0
            else:
                await asyncio.sleep(5)
            try:
                if use_ws and RPCS_WS:
                    rpc_index = (rpc_index + 1) % len(RPCS_WS)
                    provider = AsyncWebsocketProvider(RPCS_WS[rpc_index])
                    logger.info(f"Rotated to WS RPC #{rpc_index}")
                elif RPCS:
                    rpc_index = (rpc_index + 1) % len(RPCS)
                    provider = AsyncHTTPProvider(RPCS[rpc_index])
                    logger.info(f"Rotated to HTTP RPC #{rpc_index}: {RPCS[rpc_index]}")
                async_w3 = AsyncWeb3(provider)
            except Exception as conn_err:
                logger.error(f"Failed to rotate async RPC endpoint: {conn_err}")


def _watch_sync(w3: Web3) -> None:
    """
    Legacy synchronous watcher (fallback).
    """
    try:
        last_block: int = w3.eth.block_number
    except Exception:
        try:
            from scanner.config import RPCS
            w3 = Web3(Web3.HTTPProvider(RPCS[0]))
            last_block = w3.eth.block_number
        except Exception:
            time.sleep(5)
            return

    backoff = 0.5
    while True:
        try:
            current: int = w3.eth.block_number

            if current <= last_block + BLOCK_LAG:
                time.sleep(POLL_INTERVAL)
                continue

            for block_num in range(last_block + 1, current - BLOCK_LAG + 1):
                block = w3.eth.get_block(block_num, full_transactions=True)

                for tx in block.transactions:
                    # контракт створюється ТІЛЬКИ якщо to == None
                    if tx.to is not None:
                        if tx.value >= LARGE_TRANSFER_THRESHOLD_WEI:
                            try:
                                enqueue_priority(tx.to)
                                logger.info(f"[WHALE] Large transfer detected to {tx.to} ({tx.value/10**18:.2f} ETH)")
                            except Exception:
                                pass
                        continue

                    receipt = w3.eth.get_transaction_receipt(tx.hash)
                    addr: Optional[str] = receipt.contractAddress

                    if addr:
                        enqueue(addr)

            last_block = current

        except Exception as e:
            logger.error(f"Watcher error {e}")
            msg = str(e)
            try:
                from scanner.config import RPCS
                for endpoint in RPCS:
                    try:
                        w3 = Web3(Web3.HTTPProvider(endpoint))
                        _ = w3.eth.block_number
                        break
                    except Exception:
                        continue
            except Exception:
                pass
            if "429" in msg or "Too Many Requests" in msg:
                time.sleep(backoff)
                if backoff < 30.0:
                    backoff *= 2.0
            else:
                time.sleep(5)
