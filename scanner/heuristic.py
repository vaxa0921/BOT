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
    0x3B: "EXTCODESIZE", 0x3C: "EXTCODECOPY", 0x3F: "EXTCODEHASH",
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
    # Smart "Interesting" Opcodes (Risk Scoring)
    # 0xf4: DELEGATECALL (Hidden logic/Proxy)
    # 0xff: SELFDESTRUCT (Vulnerability/Rugpull)
    # 0xf1: CALL (Fund movement)
    # 0x55: SSTORE (State change)
    if signals.get("interesting_ops", 0) > 0:
        return True
    
    # Smart "Complex Logic" Check
    # If contract has EXTERNAL CALLS (0xf1) + STATE CHANGES (0x55), it's complex enough
    # regardless of arithmetic. This catches Reentrancy/Logic bugs.
    if signals.get("calls", 0) > 0 and signals.get("state", 0) > 0:
        return True

    # MAXIMUM AGGRESSION MODE:
    # If there is ANY bytecode, we analyze it.
    # We rely purely on simulation to determine profitability.
    if signals.get("total_ops", 0) > 0:
        return True
        
    return True # SAFETY FALLBACK: Always analyze if not empty bytecode (redundant but safe)


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
