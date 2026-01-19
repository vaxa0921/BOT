"""Main entry point for the scanner."""
import warnings
import os

# Suppress eth_utils network warnings - must be before other imports
warnings.filterwarnings("ignore", category=UserWarning, module="eth_utils")
warnings.filterwarnings("ignore", message=".*does not have a valid ChainId.*")
warnings.filterwarnings("ignore", message=".*Network.*does not have a valid ChainId.*")

# Also set environment variable to suppress warnings
os.environ["PYTHONWARNINGS"] = "ignore::UserWarning:eth_utils"

import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Any
from web3 import Web3

from scanner.config import RPCS, WORKERS, ALERT_CHECK_INTERVAL, BATCH_SIZE, REALTIME_ONLY, FOT_ENABLE, ONLY_FOT_MODE
from scanner.contract_queue import init, next_new, mark
from scanner.heuristic import analyze_bytecode, prefilter_pass
from scanner.worker import process_contract
from scanner.block_watcher import watch
from scanner.bytecode_dedup import is_duplicate, add_bytecode
from scanner.async_code_fetcher import fetch_codes_async
from scanner.economic_prefilter import economic_prefilter, negative_knowledge_skip
from scanner.crash_safe import CrashSafeOrchestrator, save_progress, load_progress
from scanner.auto_report_generator import generate_report, save_report
from scanner.false_positive_suppression import suppress_false_positives
from scanner.simulation import run_honeypot_simulation_eth, run_honeypot_simulation_token
from scanner.share_asset_conversion import detect_share_asset_conversion
from scanner.dust_tracker import detect_rounding_dust
from scanner.fee_on_transfer_probe import cheap_fot_candidate

# ============================================================================
# INIT
# ============================================================================
init()
rpc_i: int = 0
w3: Web3 = Web3(Web3.HTTPProvider(RPCS[rpc_i]))

# Crash-safe orchestration
orchestrator = CrashSafeOrchestrator()
checkpoint = load_progress()
if checkpoint:
    print(f"[RECOVERY] Resuming from checkpoint: {checkpoint.get('current_block', 0)}")

# Track findings for reporting
_all_findings: List[Dict[str, Any]] = []

def _add_to_findings(finding: Dict[str, Any]) -> None:
    """Callback to add finding to main list."""
    _all_findings.append(finding)

# Set callback in report module
from scanner.report import set_findings_callback
set_findings_callback(_add_to_findings)


def _decision(addr: str, stage: str, decision: str, details: Optional[Dict[str, Any]] = None) -> None:
    if decision == "skip":
        print(f"[DECISION] {addr} skipped at {stage}", flush=True)
    elif decision == "bypass":
        print(f"[DECISION] {addr} bypassed checks at {stage}", flush=True)
    return

# ============================================================================
# BLOCK WATCHER
# ============================================================================
threading.Thread(target=watch, args=(w3,), daemon=True).start()

# ============================================================================
# BACKFILL & DISCOVERY
# ============================================================================
def run_discovery_thread():
    """Background thread for backfill and factory scanning."""
    from scanner.backfill import run_backfill
    import time
    
    # Initial delay to let main loop start
    time.sleep(5)
    
    print("Starting historical backfill and factory scan...")
    try:
        # Scan last 5000 blocks on startup
        run_backfill(include_factories=True, include_verified=True)
    except Exception as e:
        print(f"Discovery error: {e}")

if not REALTIME_ONLY:
    threading.Thread(target=run_discovery_thread, daemon=True).start()
else:
    print("[REALTIME] Backfill disabled; scanning only new blocks")

# ============================================================================
# WORKER POOL
# ============================================================================
executor = ThreadPoolExecutor(max_workers=WORKERS)
last_alert_check: int = 0

# Batch processing addresses
_address_batch: List[str] = []

while True:
    # Collect addresses for batch processing
    if len(_address_batch) < BATCH_SIZE:
        addr = next_new()
        if addr:
            _address_batch.append(Web3.to_checksum_address(addr))
            continue
        elif not _address_batch:
            time.sleep(1)
            continue

    # Process batch
    if _address_batch:
        try:
            # Async batch fetch codes
            import asyncio
            codes = asyncio.run(fetch_codes_async(_address_batch))

            for addr in _address_batch:
                code = codes.get(addr)
                if not code or code == "0x":
                    mark(addr, "DONE")
                    continue

                # Deduplication by bytecode hash
                if is_duplicate(code):
                    mark(addr, "DONE")
                    continue

                add_bytecode(code)

                signals = analyze_bytecode(code)

                _decision(addr, "signals", "computed")

                # Negative knowledge skip
                if negative_knowledge_skip(code):
                    # Bypass skip if vault-like or dust detected
                    try:
                        conversion = detect_share_asset_conversion(w3, addr)
                        dust = detect_rounding_dust(w3, addr)
                        if conversion.get("is_vault_like") or dust.get("has_dust"):
                            _decision(addr, "negative_knowledge_skip", "bypass")
                            executor.submit(process_contract, w3, addr)
                            continue
                        if FOT_ENABLE or ONLY_FOT_MODE:
                            try:
                                cheap = cheap_fot_candidate(w3, addr)
                                if cheap.get("candidate"):
                                    _decision(addr, "negative_knowledge_skip", "bypass")
                                    executor.submit(process_contract, w3, addr)
                                    continue
                            except Exception:
                                pass
                        _decision(addr, "negative_knowledge_skip", "skip")
                        mark(addr, "DONE")
                        continue
                    except Exception:
                        _decision(addr, "negative_knowledge_skip", "skip")
                        mark(addr, "DONE")
                        continue

                # Economic-aware prefilter
                economic_result = economic_prefilter(code, addr)
                if not economic_result.get("passes"):
                    # Bypass if vault/dust detected
                    try:
                        conversion = detect_share_asset_conversion(w3, addr)
                        dust = detect_rounding_dust(w3, addr)
                        if conversion.get("is_vault_like") or dust.get("has_dust"):
                            _decision(addr, "economic_prefilter", "bypass")
                            executor.submit(process_contract, w3, addr)
                            continue
                        if FOT_ENABLE or ONLY_FOT_MODE:
                            try:
                                cheap = cheap_fot_candidate(w3, addr)
                                if cheap.get("candidate"):
                                    _decision(addr, "economic_prefilter", "bypass")
                                    executor.submit(process_contract, w3, addr)
                                    continue
                            except Exception:
                                pass
                        _decision(addr, "economic_prefilter", "skip")
                        mark(addr, "DONE")
                        continue
                    except Exception:
                        _decision(addr, "economic_prefilter", "skip")
                        mark(addr, "DONE")
                        continue

                # Weakened prefilter
                if not prefilter_pass(signals):
                    # Bypass if vault/dust detected
                    try:
                        conversion = detect_share_asset_conversion(w3, addr)
                        dust = detect_rounding_dust(w3, addr)
                        if conversion.get("is_vault_like") or dust.get("has_dust"):
                            _decision(addr, "prefilter_pass", "bypass")
                            executor.submit(process_contract, w3, addr)
                            continue
                        if FOT_ENABLE or ONLY_FOT_MODE:
                            try:
                                cheap = cheap_fot_candidate(w3, addr)
                                if cheap.get("candidate"):
                                    _decision(addr, "prefilter_pass", "bypass")
                                    executor.submit(process_contract, w3, addr)
                                    continue
                            except Exception:
                                pass
                        _decision(addr, "prefilter_pass", "skip")
                        mark(addr, "DONE")
                        continue
                    except Exception:
                        _decision(addr, "prefilter_pass", "skip")
                        mark(addr, "DONE")
                        continue

                _decision(addr, "prefilters", "queue")
                executor.submit(process_contract, w3, addr)

        except Exception as e:
            print(f"[MAIN ERROR] Batch processing: {e}")
            # Fallback to single address processing
            for addr in _address_batch:
                try:
                    code = w3.eth.get_code(addr).hex()
                    if not code or code == "0x":
                        mark(addr, "DONE")
                        continue

                    if is_duplicate(code):
                        mark(addr, "DONE")
                        continue

                    add_bytecode(code)
                    signals = analyze_bytecode(code)

                    if not prefilter_pass(signals):
                        mark(addr, "DONE")
                        continue

                    executor.submit(process_contract, w3, addr)
                except Exception as e2:
                    mark(addr, "FAIL")
                    print(f"[MAIN ERROR] {addr}: {e2}")

            # Перемикаємо RPC на випадок помилки
            rpc_i = (rpc_i + 1) % len(RPCS)
            w3 = Web3(Web3.HTTPProvider(RPCS[rpc_i]))
            time.sleep(1)

        _address_batch.clear()

    # ============================================================================
    # ALERT CHECK & REPORTING
    # ============================================================================
    now = int(time.time())
    if now - last_alert_check >= ALERT_CHECK_INTERVAL:
        try:
            from scanner.alert import check_alerts
            alerts = check_alerts()
            if alerts:
                print(f"[ALERT] {len(alerts)} high-severity findings! "
                      f"Check reports/alerts.json")
            
            # Generate auto-report
            if _all_findings:
                # Suppress false positives
                filtered = suppress_false_positives(_all_findings)
                
                # Generate report
                report = generate_report(filtered, min_severity=7)
                report_path = save_report(report)
                print(f"[REPORT] Generated report: {report_path}")
                
                # Save checkpoint
                save_progress(
                    processed_addresses=[f.get("address") for f in filtered],
                    current_block=w3.eth.block_number,
                    findings=filtered
                )
                
        except ImportError:
            pass
        last_alert_check = now
