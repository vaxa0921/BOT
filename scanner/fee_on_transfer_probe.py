from typing import Dict, Any, Optional, List, Tuple
from web3 import Web3
from eth_utils import to_hex
import threading
import time
from scanner.config import (
    FOT_SLOT_BRUTEFORCE_MAX,
    FOT_SCREEN_AMOUNT_WEI,
    FOT_SIM_AMOUNT_WEI,
    FOT_USE_DEBUG_TRACE,
    FOT_SCREEN_ONLY,
    FOT_DEEP_CONCURRENCY,
    FOT_CACHE_TTL_SEC,
)

TRANSFER_FROM_SELECTOR = "0x23b872dd"
EVENT_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

_CACHE_LOCK = threading.Lock()
_SLOT_CACHE: Dict[str, Tuple[float, Tuple[int, int]]] = {}
_TAX_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_TRACE_SUPPORT: Optional[bool] = None
_DEEP_SEM = threading.Semaphore(max(1, int(FOT_DEEP_CONCURRENCY)))


def _now() -> float:
    return time.time()


def _cache_get(cache: Dict[str, Tuple[float, Any]], key: str) -> Optional[Any]:
    with _CACHE_LOCK:
        v = cache.get(key)
        if not v:
            return None
        ts, payload = v
        if _now() - ts > max(int(FOT_CACHE_TTL_SEC), 1):
            try:
                del cache[key]
            except Exception:
                pass
            return None
        return payload


def _cache_put(cache: Dict[str, Tuple[float, Any]], key: str, payload: Any) -> None:
    with _CACHE_LOCK:
        cache[key] = (_now(), payload)


def _debug_trace_supported(w3: Web3) -> bool:
    global _TRACE_SUPPORT
    if _TRACE_SUPPORT is not None:
        return _TRACE_SUPPORT
    if not FOT_USE_DEBUG_TRACE:
        _TRACE_SUPPORT = False
        return False
    try:
        res = w3.provider.make_request(
            "debug_traceCall",
            [{"to": "0x0000000000000000000000000000000000000000", "data": "0x"}, "latest", {"tracer": "callTracer"}],
        )
        if isinstance(res, dict) and res.get("error"):
            _TRACE_SUPPORT = False
        else:
            _TRACE_SUPPORT = True
    except Exception:
        _TRACE_SUPPORT = False
    return bool(_TRACE_SUPPORT)


def _has_transfer_signatures(bytecode_hex: str) -> bool:
    h = bytecode_hex.lower()
    return (TRANSFER_FROM_SELECTOR[2:] in h) or ("23b872dd" in h) or ("ddf252ad" in h)


def _normalize_token_return(val: Any) -> List[str]:
    out: List[str] = []
    try:
        if isinstance(val, str) and val.startswith("0x") and len(val) == 42:
            out.append(Web3.to_checksum_address(val))
        elif isinstance(val, (list, tuple)):
            for x in val:
                if isinstance(x, str) and x.startswith("0x") and len(x) == 42:
                    out.append(Web3.to_checksum_address(x))
        elif isinstance(val, dict):
            for x in val.values():
                if isinstance(x, str) and x.startswith("0x") and len(x) == 42:
                    out.append(Web3.to_checksum_address(x))
    except Exception:
        return []
    # Dedup while preserving order
    seen = set()
    uniq: List[str] = []
    for a in out:
        k = a.lower()
        if k in seen:
            continue
        seen.add(k)
        uniq.append(a)
    return uniq


def _call0_addr(w3: Web3, addr: str, fn: str) -> List[str]:
    abi = [{"inputs": [], "name": fn, "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        val = getattr(c.functions, fn)().call()
        return _normalize_token_return(val)
    except Exception:
        return []


def _call0_addr_raw(w3: Web3, addr: str, fn_sig: str) -> List[str]:
    """Raw eth_call fallback for functions that return a single address and take no args."""
    try:
        selector = Web3.keccak(text=fn_sig)[:4].hex()
        res = w3.provider.make_request(
            "eth_call",
            [{"to": Web3.to_checksum_address(addr), "data": "0x" + selector}, "latest"],
        )
        out = res.get("result") if isinstance(res, dict) else None
        if not (isinstance(out, str) and out.startswith("0x") and len(out) >= 66):
            return []
        # last 20 bytes of 32-byte word
        raw = out[-40:]
        if raw == "0" * 40:
            return []
        return [Web3.to_checksum_address("0x" + raw)]
    except Exception:
        return []


def _read_candidate_tokens(w3: Web3, addr: str) -> List[str]:
    # Common token getter names across staking/vault/router style contracts
    for fn in (
        "token",
        "asset",
        "underlying",
        "want",
        "stakingToken",
        "depositToken",
        "lpToken",
        "baseToken",
        "quoteToken",
    ):
        vals = _call0_addr(w3, addr, fn)
        if not vals:
            vals = _call0_addr_raw(w3, addr, f"{fn}()")
        if vals:
            return vals

    # LP pairs/pools
    lp_tokens: List[str] = []
    for fn in ("token0", "token1"):
        vals = _call0_addr(w3, addr, fn)
        if not vals:
            vals = _call0_addr_raw(w3, addr, f"{fn}()")
        if vals:
            lp_tokens.extend(vals)
    if lp_tokens:
        # token0/token1 are both potentially taxable; keep both
        return _normalize_token_return(lp_tokens)

    try:
        # MasterChef-like poolInfo (first field is often LP token)
        abi = [{"inputs": [{"name": "pid", "type": "uint256"}], "name": "poolInfo", "outputs": [{"type": "address"}, {"type": "uint256"}, {"type": "uint256"}, {"type": "uint256"}], "stateMutability": "view", "type": "function"}]
        c = w3.eth.contract(address=addr, abi=abi)
        r = c.functions.poolInfo(0).call()
        vals = _normalize_token_return(r)
        if vals:
            return vals
    except Exception:
        pass
    return []


def _read_candidate_token(w3: Web3, addr: str) -> Optional[str]:
    toks = _read_candidate_tokens(w3, addr)
    return toks[0] if toks else None


def cheap_fot_candidate(w3: Web3, victim: str) -> Dict[str, Any]:
    try:
        code = w3.eth.get_code(victim).hex()
        if not code or code == "0x":
            return {"address": victim, "candidate": False, "reason": "no_code"}
        
        # Check for tokens first - if we find a token, it's a strong candidate regardless of signatures
        tokens = _read_candidate_tokens(w3, victim)
        token = tokens[0] if tokens else None
        
        if token:
             return {"address": victim, "candidate": True, "token": token, "tokens": tokens, "reason": "candidate_via_token"}
             
        # Fallback to signature check if no token found immediately
        if not _has_transfer_signatures(code):
            return {"address": victim, "candidate": False, "reason": "no_transfer_signatures"}
            
        return {"address": victim, "candidate": True, "token": None, "tokens": [], "reason": "candidate_via_sig"}
    except Exception as e:
        return {"address": victim, "candidate": False, "reason": f"error:{e}"}


def _pad32(v: int) -> str:
    h = hex(v)[2:]
    return ("0" * (64 - len(h))) + h


def _build_call_data(selector_text: str, types: List[str], args: List[Any]) -> str:
    selector = Web3.keccak(text=selector_text)[:4].hex()
    if types == ["uint256"] and len(args) == 1:
        return selector + _pad32(int(args[0]))
    return selector


def _override_erc20_storage(token: str, owner: str, spender: str, owner_balance: int, allowance_amount: int, balance_slot: int = 0, allowance_slot: int = 1) -> Dict[str, Any]:
    k_bal = Web3.solidity_keccak(["address", "uint256"], [Web3.to_checksum_address(owner), balance_slot]).hex()
    inner = Web3.solidity_keccak(["address", "uint256"], [Web3.to_checksum_address(owner), allowance_slot]).hex()
    k_allow = Web3.solidity_keccak(["address", "bytes32"], [Web3.to_checksum_address(spender), bytes.fromhex(inner[2:])]).hex()
    return {
        Web3.to_checksum_address(token): {
            "stateDiff": {
                k_bal: to_hex(owner_balance),
                k_allow: to_hex(allowance_amount)
            }
        }
    }


def _trace_call(w3: Web3, call_obj: Dict[str, Any], state_override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    params = [call_obj, "latest", {"tracer": "callTracer"}]
    if state_override:
        params[2]["stateOverrides"] = state_override
        params[2]["stateOverride"] = state_override
    try:
        return w3.provider.make_request("debug_traceCall", params)
    except Exception as e:
        return {"error": str(e), "result": None}


def _eth_call_override(w3: Web3, to: str, data: str, state_override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    params: List[Any] = [{"to": Web3.to_checksum_address(to), "data": data}, "latest"]
    if state_override:
        params.append({"stateOverride": state_override})
    try:
        return w3.provider.make_request("eth_call", params)
    except Exception as e:
        return {"error": str(e), "result": None}


def find_erc20_slots(w3: Web3, token: str, test_owner: str, test_spender: str) -> Tuple[int, int]:
    token_key = Web3.to_checksum_address(token)
    cached = _cache_get(_SLOT_CACHE, token_key)
    if cached is not None:
        return cached
    balance_slot = 0
    allowance_slot = 1
    try:
        selector_bal = Web3.keccak(text="balanceOf(address)")[:4].hex()
        owner_padded = ("0" * 24) + Web3.to_checksum_address(test_owner)[2:].lower()
        data_bal = selector_bal + owner_padded + ("0" * 64)
        for s in range(0, int(FOT_SLOT_BRUTEFORCE_MAX) + 1):
            ov = _override_erc20_storage(token, test_owner, test_spender, 10**24, 0, balance_slot=s, allowance_slot=allowance_slot)
            res = _eth_call_override(w3, token, data_bal, ov)
            out = res.get("result")
            if isinstance(out, str) and out.startswith("0x") and int(out, 16) > 0:
                balance_slot = s
                break
        selector_all = Web3.keccak(text="allowance(address,address)")[:4].hex()
        owner_padded = ("0" * 24) + Web3.to_checksum_address(test_owner)[2:].lower()
        spender_padded = ("0" * 24) + Web3.to_checksum_address(test_spender)[2:].lower()
        data_all = selector_all + owner_padded + ("0" * 64) + spender_padded + ("0" * 64)
        for s in range(0, int(FOT_SLOT_BRUTEFORCE_MAX) + 1):
            ov = _override_erc20_storage(token, test_owner, test_spender, 0, 10**24, balance_slot=balance_slot, allowance_slot=s)
            res = _eth_call_override(w3, token, data_all, ov)
            out = res.get("result")
            if isinstance(out, str) and out.startswith("0x") and int(out, 16) > 0:
                allowance_slot = s
                break
    except Exception:
        pass
    out = (balance_slot, allowance_slot)
    _cache_put(_SLOT_CACHE, token_key, out)
    return out


def simulate_fot(w3: Web3, victim: str, amount_wei: int = FOT_SIM_AMOUNT_WEI, from_addr: Optional[str] = None) -> Dict[str, Any]:
    if not _debug_trace_supported(w3):
        token = _read_candidate_token(w3, victim)
        return {
            "address": victim,
            "candidate": bool(token),
            "vulnerable": False,
            "reason": "debug_trace_disabled",
            "token": token,
        }
    from_addr = from_addr or "0x0000000000000000000000000000000000000111"
    code = w3.eth.get_code(victim).hex()
    if not _has_transfer_signatures(code):
        return {"address": victim, "candidate": False, "vulnerable": False, "reason": "no_transfer_signatures"}
    token = _read_candidate_token(w3, victim)
    if not token:
        # Check if victim itself looks like a token
        if _has_transfer_signatures(code):
             return {
                 "address": victim,
                 "candidate": True,
                 "vulnerable": False,
                 "reason": "is_token_itself",
                 "token": victim 
             }
        return {"address": victim, "candidate": True, "vulnerable": False, "reason": "no_token_address"}
    data = None
    selectors = [
        ("deposit(uint256)", ["uint256"], [amount_wei]),
        ("stake(uint256)", ["uint256"], [amount_wei]),
        ("enterStaking(uint256)", ["uint256"], [amount_wei]),
        ("addLiquidity(uint256)", ["uint256"], [amount_wei])
    ]
    bslot, aslot = find_erc20_slots(w3, Web3.to_checksum_address(token), Web3.to_checksum_address(from_addr), Web3.to_checksum_address(victim))
    for s, t, a in selectors:
        try:
            d = _build_call_data(s, t, a)
            call_obj = {"to": Web3.to_checksum_address(victim), "from": Web3.to_checksum_address(from_addr), "data": d}
            ov = _override_erc20_storage(Web3.to_checksum_address(token), Web3.to_checksum_address(from_addr), Web3.to_checksum_address(victim), amount_wei, amount_wei, bslot, aslot)
            trace = _trace_call(w3, call_obj, ov)
            if trace and trace.get("result"):
                data = d
                break
        except Exception:
            continue
    if not data:
        return {"address": victim, "candidate": True, "vulnerable": False, "reason": "no_callable_deposit"}
    call_obj = {"to": Web3.to_checksum_address(victim), "from": Web3.to_checksum_address(from_addr), "data": data}
    ov = _override_erc20_storage(Web3.to_checksum_address(token), Web3.to_checksum_address(from_addr), Web3.to_checksum_address(victim), amount_wei, amount_wei, bslot, aslot)
    trace = _trace_call(w3, call_obj, ov)
    if not trace or not trace.get("result"):
        return {"address": victim, "candidate": True, "vulnerable": False, "reason": "trace_failed"}
    logs = []
    def _collect(res: Any):
        if isinstance(res, dict):
            if "logs" in res and isinstance(res["logs"], list):
                for l in res["logs"]:
                    logs.append(l)
            for v in res.values():
                _collect(v)
        elif isinstance(res, list):
            for v in res:
                _collect(v)
    _collect(trace)
    transfer_values = []
    for l in logs:
        topics = l.get("topics") or []
        if topics and topics[0].lower() == EVENT_TRANSFER_TOPIC:
            data_hex = l.get("data", "0x")
            try:
                val = int(data_hex, 16)
                transfer_values.append(val)
            except Exception:
                pass
    if not transfer_values:
        return {"address": victim, "candidate": True, "vulnerable": False, "reason": "no_transfer_logs"}
    min_transferred = min(transfer_values)
    vulnerable = min_transferred < amount_wei
    return {
        "address": victim,
        "candidate": True,
        "vulnerable": vulnerable,
        "token": token,
        "amount": amount_wei,
        "transferred": min_transferred
    }


def screen_token_tax(w3: Web3, token: str, amount_wei: int = FOT_SCREEN_AMOUNT_WEI) -> Dict[str, Any]:
    token_key = Web3.to_checksum_address(token)
    cached = _cache_get(_TAX_CACHE, token_key)
    if cached is not None:
        return cached
    if not _debug_trace_supported(w3):
        out = {"token": token_key, "taxed": False, "tax_pct": 0, "reason": "debug_trace_disabled"}
        _cache_put(_TAX_CACHE, token_key, out)
        return out
    from_addr = "0x0000000000000000000000000000000000000222"
    to_addr = "0x0000000000000000000000000000000000000333"
    try:
        selector = Web3.keccak(text="transfer(address,uint256)")[:4].hex()
        addr_padded = ("0" * 24) + to_addr.lower()[2:]
        data = selector + addr_padded + _pad32(amount_wei)
        call_obj = {"to": Web3.to_checksum_address(token), "from": Web3.to_checksum_address(from_addr), "data": data}
        bslot, aslot = find_erc20_slots(w3, Web3.to_checksum_address(token), Web3.to_checksum_address(from_addr), Web3.to_checksum_address(to_addr))
        ov = _override_erc20_storage(Web3.to_checksum_address(token), Web3.to_checksum_address(from_addr), Web3.to_checksum_address(to_addr), amount_wei, amount_wei, bslot, aslot)
        trace = _trace_call(w3, call_obj, ov)
        logs = []
        def _collect(res: Any):
            if isinstance(res, dict):
                if "logs" in res and isinstance(res["logs"], list):
                    for l in res["logs"]:
                        logs.append(l)
                for v in res.values():
                    _collect(v)
            elif isinstance(res, list):
                for v in res:
                    _collect(v)
        _collect(trace)
        transfer_values = []
        for l in logs:
            topics = l.get("topics") or []
            if topics and topics[0].lower() == EVENT_TRANSFER_TOPIC:
                data_hex = l.get("data", "0x")
                try:
                    val = int(data_hex, 16)
                    transfer_values.append(val)
                except Exception:
                    pass
        if not transfer_values:
            out = {"token": token_key, "taxed": False, "tax_pct": 0}
            _cache_put(_TAX_CACHE, token_key, out)
            return out
        min_transferred = min(transfer_values)
        taxed = min_transferred < amount_wei
        tax_pct = 0.0
        if taxed:
            tax_pct = (amount_wei - min_transferred) / amount_wei
        out = {"token": token_key, "taxed": taxed, "transferred": min_transferred, "tax_pct": tax_pct}
        _cache_put(_TAX_CACHE, token_key, out)
        return out
    except Exception:
        out = {"token": token_key, "taxed": False, "tax_pct": 0}
        _cache_put(_TAX_CACHE, token_key, out)
        return out


def probe_fee_on_transfer(w3: Web3, victim: str) -> Dict[str, Any]:
    with _DEEP_SEM:
        fot = simulate_fot(w3, victim, FOT_SIM_AMOUNT_WEI)
        tok = fot.get("token")
        
        # Fallback: if no token found inside, but victim has signatures, treat victim as the token
        if not tok:
            try:
                code = w3.eth.get_code(victim).hex()
                if _has_transfer_signatures(code):
                    tok = victim
                    fot["token"] = victim
                    fot["note"] = "victim_is_token"
            except Exception:
                pass

        if tok:
            fot["token_screen"] = screen_token_tax(w3, tok, FOT_SCREEN_AMOUNT_WEI)
            if not FOT_SCREEN_ONLY and tok.lower() != victim.lower():
                fot["roundtrip"] = simulate_roundtrip(w3, victim, tok, FOT_SIM_AMOUNT_WEI)
        return fot


def simulate_roundtrip(w3: Web3, victim: str, token: str, amount_wei: int = FOT_SIM_AMOUNT_WEI, from_addr: Optional[str] = None) -> Dict[str, Any]:
    from_addr = from_addr or "0x0000000000000000000000000000000000000444"
    bslot, aslot = find_erc20_slots(w3, Web3.to_checksum_address(token), Web3.to_checksum_address(from_addr), Web3.to_checksum_address(victim))
    ok = True
    steps = []
    try:
        selector_appr = Web3.keccak(text="approve(address,uint256)")[:4].hex()
        addr_padded = ("0" * 24) + Web3.to_checksum_address(victim)[2:].lower()
        data_appr = selector_appr + addr_padded + _pad32(amount_wei)
        ov = _override_erc20_storage(Web3.to_checksum_address(token), Web3.to_checksum_address(from_addr), Web3.to_checksum_address(victim), amount_wei, amount_wei, bslot, aslot)
        res1 = _trace_call(w3, {"to": Web3.to_checksum_address(token), "from": Web3.to_checksum_address(from_addr), "data": data_appr}, ov)
        ok = ok and bool(res1.get("result"))
        steps.append({"approve": ok})
        data_dep = _build_call_data("deposit(uint256)", ["uint256"], [amount_wei])
        res2 = _trace_call(w3, {"to": Web3.to_checksum_address(victim), "from": Web3.to_checksum_address(from_addr), "data": data_dep}, ov)
        ok = ok and bool(res2.get("result"))
        steps.append({"deposit": bool(res2.get("result"))})
        data_wd = _build_call_data("withdraw(uint256)", ["uint256"], [amount_wei])
        res3 = _trace_call(w3, {"to": Web3.to_checksum_address(victim), "from": Web3.to_checksum_address(from_addr), "data": data_wd}, ov)
        ok = ok and bool(res3.get("result"))
        steps.append({"withdraw": bool(res3.get("result"))})
    except Exception:
        ok = False
    return {"roundtrip_ok": ok, "steps": steps}
