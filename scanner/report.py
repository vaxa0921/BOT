"""Report generation and management."""
import os
import json
import time
from typing import Dict, Any, List
from scanner.severity import score_severity

OUT = "reports"
ALERT_FILE = os.path.join(OUT, "alerts.json")

os.makedirs(OUT, exist_ok=True)

_findings: List[Dict[str, Any]] = []
_all_findings_callback = None  # Callback to update main's _all_findings


def set_findings_callback(callback):
    """Set callback to update external findings list."""
    global _all_findings_callback
    _all_findings_callback = callback


def add_finding(addr: str, signals: Dict[str, Any],
                impact: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add a finding to the reports.

    Args:
        addr: Contract address
        signals: Analysis signals
        impact: Impact assessment

    Returns:
        Finding dictionary
    """
    finding = {
        "address": addr,
        "timestamp": int(time.time()),
        "signals": signals,
        "impact": impact,
        "severity": score_severity(signals, impact)
    }
    _findings.append(finding)
    
    # Immediate terminal feedback
    pct = impact.get("percentage_loss", 0.0)
    tvl = impact.get("tvl_wei", 0)
    stolen = impact.get("stolen_wei", 0)
    netp = impact.get("net_profit_wei", 0)
    imp_lvl = impact.get("impact_level", "LOW")
    print(f"[FOUND] {addr} sev={finding['severity']} impact={imp_lvl} tvl={tvl} stolen={stolen} net={netp} pct={pct:.4f}%")
    
    # Update main's findings list if callback set
    if _all_findings_callback:
        _all_findings_callback(finding)
    
    _flush()
    return finding


def _flush() -> None:
    """Flush findings to disk."""
    with open(ALERT_FILE, "w", encoding="utf-8") as f:
        json.dump(_findings, f, indent=2)
