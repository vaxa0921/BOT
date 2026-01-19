"""Bytecode analysis and heuristic filtering."""
from typing import Dict, List, Tuple, Optional, Set

ARITH_OPS: Set[str] = {"ADD", "SUB", "MUL", "DIV", "MOD", "SDIV", "SMOD"}
STATE_OPS: Set[str] = {"SSTORE", "SLOAD"}
FLOW_OPS: Set[str] = {"CALL", "DELEGATECALL", "STATICCALL"}

CONST_SMALL_THRESHOLD: int = 1_000

_OPCODE_TABLE: Dict[int, str] = {
    0x01: "ADD", 0x02: "MUL", 0x03: "SUB",
    0x04: "DIV", 0x05: "SDIV", 0x06: "MOD", 0x07: "SMOD",
    0x3a: "GASPRICE", 0x42: "TIMESTAMP", 0x48: "BASEFEE",
    0x54: "SLOAD", 0x55: "SSTORE",
    0xF0: "CREATE", 0xF1: "CALL", 0xF4: "DELEGATECALL", 0xF5: "CREATE2", 0xFA: "STATICCALL",
    0xFF: "SELFDESTRUCT",
}


def analyze_bytecode(bytecode: str) -> Dict[str, int]:
    """
    Analyze bytecode for arithmetic and state operations.

    Args:
        bytecode: Hex string of bytecode (with or without 0x prefix)

    Returns:
        Dictionary with operation counts
    """
    if bytecode.startswith("0x"):
        bytecode = bytecode[2:]

    ops = _disassemble(bytecode)

    counts = {
        "arith": 0,
        "div_mod": 0,
        "state": 0,
        "calls": 0,
        "small_consts": 0,
        "interesting_ops": 0,
        "total_ops": len(ops),
    }

    for op, arg in ops:
        if op in ARITH_OPS:
            counts["arith"] += 1
        if op in {"DIV", "SDIV", "MOD", "SMOD"}:
            counts["div_mod"] += 1
        if op in STATE_OPS:
            counts["state"] += 1
        if op in FLOW_OPS:
            counts["calls"] += 1
        if op in {"TIMESTAMP", "GASPRICE", "BASEFEE", "SELFDESTRUCT", "DELEGATECALL", "CREATE", "CREATE2"}:
            counts["interesting_ops"] += 1
        if op.startswith("PUSH") and arg:
            try:
                value = int(arg, 16)
                if 0 < value <= CONST_SMALL_THRESHOLD:
                    counts["small_consts"] += 1
            except (ValueError, TypeError):
                pass

    return counts


def prefilter_pass(signals: Dict[str, int]) -> bool:
    """
    Check if contract passes prefilter for further analysis.
    
    Weakened prefilter: lower thresholds for more contracts.

    Args:
        signals: Dictionary with operation counts

    Returns:
        True if contract should be analyzed further
    """
    # Bypass if interesting opcodes detected
    if signals.get("interesting_ops", 0) > 0:
        return True

    # Weakened prefilter - lower thresholds
    if signals["arith"] < 1:  # was 3
        return False

    if signals["small_consts"] < 0:  # was 1 - now optional
        # Still check div_mod ratio if no small consts
        total_ops = max(signals["total_ops"], 1)
        if signals["div_mod"] / total_ops < 0.0005:  # was 0.001
            return False

    # More lenient: just need some arithmetic or division
    total_ops = max(signals["total_ops"], 1)
    if signals["div_mod"] == 0 and signals["arith"] < 2:
        return False

    return True


def passes_prefilter(bytecode: str) -> bool:
    """
    Check if bytecode passes prefilter.

    Args:
        bytecode: Hex string of bytecode

    Returns:
        True if bytecode passes prefilter
    """
    return prefilter_pass(analyze_bytecode(bytecode))


def _disassemble(bytecode: str) -> List[Tuple[str, Optional[str]]]:
    """
    Disassemble bytecode into opcodes.

    Args:
        bytecode: Hex string of bytecode

    Returns:
        List of (opcode, argument) tuples
    """
    i = 0
    byte_data = bytes.fromhex(bytecode)
    out: List[Tuple[str, Optional[str]]] = []

    while i < len(byte_data):
        op = byte_data[i]
        if 0x60 <= op <= 0x7F:
            n = op - 0x5F
            arg = byte_data[i+1:i+1+n].hex()
            out.append((f"PUSH{n}", arg))
            i += 1 + n
        else:
            opcode_name = _OPCODE_TABLE.get(op, f"OP_{op:02x}")
            out.append((opcode_name, None))
            i += 1
    return out
