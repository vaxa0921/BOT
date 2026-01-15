from typing import Dict, Any, List
from web3 import Web3


def _encode_function_call(selector: str, args: List[bytes]) -> bytes:
    data = bytes.fromhex(selector[2:])
    for arg in args:
        padded = arg.ljust(32, b"\x00")
        data += padded
    return data


def detect_multicall_context_leak(
    w3: Web3,
    contract_address: str,
    test_value_wei: int = int(0.0001 * 10**18)
) -> Dict[str, Any]:
    addr = Web3.to_checksum_address(contract_address)
    multicall_sigs = [
        "0x5ae401dc",
        "0x1f05571c",
        "0x17352e13",
    ]
    deposit_sigs = [
        "0xd0e30db0",
        "0xb6b55f25",
    ]
    balance_sigs = [
        "0xf7888aec",
        "0x70a08231",
    ]
    try:
        balance_before = w3.eth.get_balance(addr)
    except Exception:
        balance_before = 0
    for m_sig in multicall_sigs:
        for d_sig in deposit_sigs:
            inner = _encode_function_call(d_sig, [])
            encoded_inner = inner.ljust(32, b"\x00")
            offset = (4 + 32 + 32).to_bytes(32, "big")
            length = (2).to_bytes(32, "big")
            call_data = m_sig
            call_data_bytes = bytes.fromhex(call_data[2:])
            call_data_bytes += offset
            call_data_bytes += length
            call_data_bytes += encoded_inner
            call_data_bytes += encoded_inner
            tx = {
                "to": addr,
                "from": w3.eth.accounts[0] if w3.eth.accounts else addr,
                "value": test_value_wei,
                "data": call_data_bytes,
            }
            try:
                w3.eth.call(tx)
            except Exception:
                continue
            for b_sig in balance_sigs:
                bal_call = {
                    "to": addr,
                    "data": b_sig + "0" * 24 + addr[2:],
                }
                try:
                    res = w3.eth.call(bal_call)
                    if res and len(res) >= 32:
                        bal = int.from_bytes(res[-32:], "big")
                        if bal > test_value_wei:
                            return {
                                "address": addr,
                                "vulnerable": True,
                                "balance": bal,
                                "sent": test_value_wei,
                                "multicall_selector": m_sig,
                                "deposit_selector": d_sig,
                                "balance_selector": b_sig,
                            }
                except Exception:
                    continue
    return {
        "address": addr,
        "vulnerable": False,
    }

