"""Backfill scanner for historical contract discovery."""
import warnings
import os
import time
import logging
from typing import Optional, List
from web3 import Web3
from scanner.contract_queue import enqueue

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
    KNOWN_FACTORIES
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

    logger.info(f"Starting backfill from block {start_block} to {end_block}")
    logger.info(f"Total blocks to scan: {end_block - start_block}")

    while current < end_block:
        batch_end = min(current + BACKFILL_BATCH_SIZE, end_block)
        
        try:
            for block_num in range(current, batch_end):
                try:
                    block = w3.eth.get_block(block_num, full_transactions=True)
                    scanned += 1
                    total_txs += len(block.transactions)

                    contract_creations = 0
                    for tx in block.transactions:
                        if tx.to is not None:
                            continue

                        try:
                            receipt = w3.eth.get_transaction_receipt(tx.hash)
                            addr = receipt.contractAddress

                            if addr:
                                enqueue(addr)
                                found += 1
                                contract_creations += 1
                        except Exception as tx_error:
                            logger.debug(f"Error getting receipt for tx {tx.hash.hex()}: {tx_error}")
                            continue

                    if contract_creations > 0:
                        logger.debug(
                            f"Block {block_num}: found {contract_creations} contract(s)"
                        )

                except Exception as block_error:
                    logger.warning(f"Error processing block {block_num}: {block_error}")
                    scanned += 1
                    continue

            current = batch_end
            logger.info(
                f"Backfill progress: {current}/{end_block} "
                f"(scanned={scanned}, found={found}, txs={total_txs})"
            )

        except Exception as e:
            logger.error(f"Backfill error at block {current}: {e}")
            time.sleep(5)
            # Try next RPC (round-robin)
            rpc_idx = (current // BACKFILL_BATCH_SIZE) % len(RPCS)
            w3 = Web3(Web3.HTTPProvider(RPCS[rpc_idx]))

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
