"""Contract queue management."""
import threading
from collections import deque
from typing import Optional, Set, Deque

# ==============================
# INTERNAL STATE
# ==============================
_QUEUE: Deque[str] = deque()
_PRIORITY_QUEUE: Deque[str] = deque()
_SEEN: Set[str] = set()
_LOCK: threading.Lock = threading.Lock()

# ==============================
# API
# ==============================


def init() -> None:
    """Initialize the queue and seen set."""
    with _LOCK:
        _QUEUE.clear()
        _PRIORITY_QUEUE.clear()
        _SEEN.clear()


def enqueue(address: str) -> None:
    """
    Add an address to the queue if not already seen.

    Args:
        address: Contract address to enqueue
    """
    if not address:
        return
    address = address.lower()

    with _LOCK:
        if address in _SEEN:
            return
        _SEEN.add(address)
        _QUEUE.append(address)


def enqueue_priority(address: str) -> None:
    """
    Add an address to the PRIORITY queue if not already seen.

    Args:
        address: Contract address to enqueue with priority
    """
    if not address:
        return
    address = address.lower()

    with _LOCK:
        # Priority items bypass the _SEEN check to allow re-scanning of active contracts
        # deduplication is handled by the worker's idempotent TTL logic.
        if address not in _SEEN:
            _SEEN.add(address)
        
        _PRIORITY_QUEUE.append(address)


def next_new() -> Optional[str]:
    """
    Get the next address from the queue.

    Returns:
        Next address or None if queue is empty
    """
    with _LOCK:
        if _PRIORITY_QUEUE:
            return _PRIORITY_QUEUE.popleft()
        if _QUEUE:
            return _QUEUE.popleft()
        return None


def mark(address: str, status: str) -> None:
    """
    Mark an address with a status (for compatibility).

    Args:
        address: Contract address
        status: Status (DONE / FAIL / OK)
    """
    # status: DONE / FAIL / OK
    # залишено як no-op для сумісності
    pass
