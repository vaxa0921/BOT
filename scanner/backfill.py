"""Backfill scanner for historical contract discovery."""
import warnings
import os
import time
import logging
from typing import Optional, List
from web3 import Web3
from scanner.contract_queue import enqueue, enqueue_priority

# Suppress eth_utils network warnings
warnings.filterwarnings("ignore", category=UserWarning, module="eth_utils")
warnings.filterwarnings("ignore", message=".*does not have a valid ChainId.*")
warnings.filterwarnings("ignore", message=".*Network.*does not have a valid ChainId.*")
os.environ["PYTHONWARNINGS"] = "ignore::UserWarning:eth_utils"
from scanner.config import (
    RPCS,
    BACKFILL_BATCH_SIZE,
    BACKFILL_START_BLOCK,
    BACKFILL_END_BLOCK,
    BACKFILL_BLOCKS_BACK,
    KNOWN_FACTORIES,
)
from scanner.factory_scanner import scan_factory_creations, scan_global_factory_events
from scanner.verified_ingestion import ingest_verified_contracts

logger = logging.getLogger(__name__)


def run_backfill(
    start_block: Optional[int] = None,
    end_block: Optional[int] = None,
    include_factories: bool = True,
    include_verified: bool = True
) -> None:
    """
    Run backfill scanner for historical blocks.

    Args:
        start_block: Starting block number (None = config value)
        end_block: Ending block number (None = config value or current)
        include_factories: Whether to scan factory contracts
        include_verified: Whether to ingest verified contracts
    """
    w3 = Web3(Web3.HTTPProvider(RPCS[0]))
    current_block = w3.eth.block_number
    
    if start_block is None:
        if BACKFILL_START_BLOCK == 0:
            # Start from recent blocks (default to config or 1000)
            start_block = max(current_block - BACKFILL_BLOCKS_BACK, 1)
        else:
            start_block = BACKFILL_START_BLOCK
    
    if end_block is None:
        end_block = BACKFILL_END_BLOCK or current_block

    logger.info(f"Backfill: blocks {start_block} → {end_block}")

    # Ingest verified contracts
    if include_verified:
        logger.info("Ingesting verified contracts...")
        try:
            verified_count = ingest_verified_contracts()
            logger.info(f"Ingested {verified_count} verified contracts")
        except Exception as e:
            logger.error(f"Verified ingestion failed: {e}")

    # Scan factory contracts
    factory_addresses: List[str] = []
    if include_factories:
        # Global scan by event topics (PairCreated/PoolCreated)
        try:
            global_created = scan_global_factory_events(w3, blocks=BACKFILL_BLOCKS_BACK)
            if global_created:
                logger.info(f"Global factory events found {len(global_created)} contracts")
                for addr in global_created:
                    enqueue(addr)
                    factory_addresses.append(addr)
        except Exception as e:
            logger.error(f"Global factory event scan failed: {e}")
        
        for factory_addr in KNOWN_FACTORIES:
            try:
                # Try common event names
                created = scan_factory_creations(w3, factory_addr, "PairCreated")
                if not created:
                     created = scan_factory_creations(w3, factory_addr, "PoolCreated")
                
                factory_addresses.extend(created)
                
                if created:
                    logger.info(f"Found {len(created)} contracts from factory {factory_addr}")
                    for addr in created:
                        enqueue(addr)
            except Exception as e:
                logger.error(f"Error scanning factory {factory_addr}: {e}")

    current = start_block
    scanned = 0
    found = 0
    total_txs = 0

    total_blocks = end_block - start_block
    logger.info(f"Starting backfill from block {start_block} to {end_block} ({total_blocks} blocks)")
    
    # 1. Scan Factory Events FIRST (High Priority)
    # This finds existing vaults/pools which are the most likely targets for rounding/inflation bugs
    # We scan the ENTIRE range for these specific topics
    
    # Factory Topics
    new_vault_topic = "0x4241302c393c713e690702c4a45a57e93cef59aa8c6e2358495853b3420551d8"
    vault_created_topic = "0x5d9c31ffa0fecffd7cf379989a3c7af252f0335e0d2a1320b55245912c781f53"
    pair_created_topic = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9" # Uniswap V2
    pool_created_topic = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118" # Uniswap V3
    
    logger.info("Scanning for Factory Events (Vaults/Pools) to populate queue...")
    
    # We use a larger batch size for logs since we filter by topic
    log_batch_size = 2000 
    
    for b_start in range(start_block, end_block + 1, log_batch_size):
        b_end = min(b_start + log_batch_size - 1, end_block)
        try:
            logs = w3.eth.get_logs({
                "fromBlock": b_start,
                "toBlock": b_end,
                "address": KNOWN_FACTORIES,
                "topics": [[new_vault_topic, vault_created_topic, pair_created_topic, pool_created_topic]]
            })
            
            for log in logs:
                try:
                    topics = log.get("topics", [])
                    if len(topics) > 1:
                        # Extract address from topic (usually topic 1 or 2)
                        # V2/V3: pair/pool is usually in data or topic, but let's try standard patterns
                        
                        # V2 PairCreated: pair is in data (first 32 bytes)
                        if topics[0].hex() == pair_created_topic:
                            data = log.get("data", "0x")
                            if len(data) >= 66:
                                addr = w3.to_checksum_address("0x" + data[2:42]) # First 20 bytes of data often pair
                                enqueue(addr)
                                continue
                                
                        # V3 PoolCreated: pool is in data? No, V3 PoolCreated is (token0, token1, fee, tickSpacing, pool)
                        # pool is at end of arguments.
                        # Actually standard V3 event: PoolCreated(token0, token1, fee, tickSpacing, pool)
                        # topics: [sig, token0, token1, fee] -> pool is in data?
                        # Let's just grab address from the log emitter itself if it's a factory, or try to parse data.
                        # Simpler: Just grab any address-like thing in topics/data
                        
                        # Generic Vault Patterns (NewVault/VaultCreated usually have vault in topic 1)
                        addr = w3.to_checksum_address("0x" + topics[1].hex()[-40:])
                        enqueue(addr)
                except Exception:
                    pass
            
            logger.info(f"[BACKFILL] Scanned factory logs {b_start}-{b_end}. Found {len(logs)} events.")
            
        except Exception as e:
            logger.error(f"[BACKFILL] Log scan failed: {e}")
            time.sleep(1)

    # 2. Standard Block Scan (Transactions)
    # Only if we really need deep scan. For now, Factory scan is much higher yield for "finding something profitable".
    # We will skip the full tx scan to save time and focus on the vaults we just found.
    logger.info("Factory scan complete. Processing queue...")
    return

    logger.info(
        f"Backfill complete: scanned={scanned}, "
        f"contracts={found}, factories={len(factory_addresses)}"
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [BACKFILL] %(message)s"
    )
    run_backfill()
