"""Bytecode hash deduplication."""
import hashlib
import threading
from typing import Set, Optional

_BYTECODE_HASHES: Set[str] = set()
_LOCK: threading.Lock = threading.Lock()


def get_bytecode_hash(bytecode: str) -> str:
    """
    Calculate SHA256 hash of bytecode.

    Args:
        bytecode: Hex string of bytecode

    Returns:
        Hex string of hash
    """
    if bytecode.startswith("0x"):
        bytecode = bytecode[2:]
    
    byte_data = bytes.fromhex(bytecode)
    return hashlib.sha256(byte_data).hexdigest()


def is_duplicate(bytecode: str) -> bool:
    """
    Check if bytecode hash was already seen.

    Args:
        bytecode: Hex string of bytecode

    Returns:
        True if duplicate, False otherwise
    """
    hash_value = get_bytecode_hash(bytecode)
    
    with _LOCK:
        if hash_value in _BYTECODE_HASHES:
            return True
        _BYTECODE_HASHES.add(hash_value)
        return False


def add_bytecode(bytecode: str) -> None:
    """
    Add bytecode hash to seen set.

    Args:
        bytecode: Hex string of bytecode
    """
    hash_value = get_bytecode_hash(bytecode)
    with _LOCK:
        _BYTECODE_HASHES.add(hash_value)


def clear() -> None:
    """Clear all seen bytecode hashes."""
    with _LOCK:
        _BYTECODE_HASHES.clear()
