"""Crash-safe orchestration."""
import json
import signal
import sys
import time
from typing import Dict, Any, List, Optional
from pathlib import Path

CHECKPOINT_FILE = Path("scanner/data/checkpoint.json")


class CrashSafeOrchestrator:
    """Orchestrator with crash recovery."""
    
    def __init__(self):
        self.checkpoint_file = CHECKPOINT_FILE
        self.running = True
        self.setup_signal_handlers()
    
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(sig, frame):
            try:
                self.save_checkpoint({"timestamp": int(time.time()), "event": "signal_shutdown"})
            except Exception:
                pass
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def save_checkpoint(self, state: Optional[Dict[str, Any]] = None) -> None:
        """
        Save current state to checkpoint.

        Args:
            state: Current state dictionary
        """
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        
        payload = state or {"timestamp": int(time.time())}
        with open(self.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    
    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """
        Load state from checkpoint.

        Returns:
            State dictionary or None
        """
        if not self.checkpoint_file.exists():
            return None
        
        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    
    def clear_checkpoint(self) -> None:
        """Clear checkpoint file."""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()


def save_progress(
    processed_addresses: List[str],
    current_block: int,
    findings: List[Dict[str, Any]]
) -> None:
    """
    Save processing progress.

    Args:
        processed_addresses: List of processed addresses
        current_block: Current block number
        findings: List of findings
    """
    state = {
        "processed_addresses": processed_addresses,
        "current_block": current_block,
        "findings_count": len(findings),
        "timestamp": int(time.time())
    }
    
    orchestrator = CrashSafeOrchestrator()
    orchestrator.save_checkpoint(state)


def load_progress() -> Optional[Dict[str, Any]]:
    """
    Load processing progress.

    Returns:
        Progress state or None
    """
    orchestrator = CrashSafeOrchestrator()
    return orchestrator.load_checkpoint()
