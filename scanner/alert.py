"""Alert checking and management."""
import json
from pathlib import Path
from typing import List, Dict, Any

ALERT_FILE: Path = Path("reports/alerts.json")
ALERT_FILE.parent.mkdir(exist_ok=True)

SEVERITY_THRESHOLD: int = 8


def check_alerts() -> List[Dict[str, Any]]:
    """
    Check for high-severity alerts.

    Returns:
        List of findings with severity >= threshold
    """
    if not ALERT_FILE.exists():
        return []

    try:
        with open(ALERT_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                data = []
            else:
                data = json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        print(f"[ALERT ERROR] Failed to read alerts file: {e}")
        return []

    return [finding for finding in data
            if finding.get("severity", 0) >= SEVERITY_THRESHOLD]
