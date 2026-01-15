"""Auto-report generator."""
import json
import time
from typing import Dict, List, Any, Optional
from pathlib import Path
from scanner.impact_severity import is_bounty_worthy

REPORTS_DIR = Path("scanner/reports")


def generate_report(
    findings: List[Dict[str, Any]],
    min_severity: int = 7
) -> Dict[str, Any]:
    """
    Generate automated report.

    Args:
        findings: List of findings
        min_severity: Minimum severity for inclusion

    Returns:
        Report dictionary
    """
    # Filter by severity
    filtered_findings = [
        f for f in findings
        if f.get("severity", 0) >= min_severity
    ]
    
    # Filter by bounty-worthiness
    bounty_findings = []
    for finding in filtered_findings:
        impact = finding.get("impact", {})
        severity = finding.get("severity", 0)
        
        if is_bounty_worthy(impact, severity, min_severity):
            bounty_findings.append(finding)
    
    report = {
        "timestamp": int(time.time()),
        "total_findings": len(findings),
        "filtered_findings": len(filtered_findings),
        "bounty_worthy": len(bounty_findings),
        "findings": bounty_findings,
        "summary": {
            "critical": len([f for f in bounty_findings if f.get("severity", 0) >= 9]),
            "high": len([f for f in bounty_findings if 7 <= f.get("severity", 0) < 9]),
            "medium": len([f for f in bounty_findings if 5 <= f.get("severity", 0) < 7])
        }
    }
    
    return report


def save_report(report: Dict[str, Any], filename: Optional[str] = None) -> Path:
    """
    Save report to file.

    Args:
        report: Report dictionary
        filename: Optional filename (auto-generated if None)

    Returns:
        Path to saved report
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    
    if filename is None:
        timestamp = report.get("timestamp", int(time.time()))
        filename = f"report_{timestamp}.json"
    
    report_path = REPORTS_DIR / filename
    
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    
    return report_path


def generate_bounty_submission(finding: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate bounty submission format.

    Args:
        finding: Finding dictionary

    Returns:
        Submission dictionary
    """
    return {
        "title": finding.get("title", "Rounding Vulnerability"),
        "contract": finding.get("address", ""),
        "severity": finding.get("severity", 0),
        "impact": finding.get("impact", {}),
        "description": finding.get("description", ""),
        "proof_of_concept": finding.get("poc", {}),
        "recommended_fix": finding.get("recommendation", ""),
        "exploitability": finding.get("exploitability", 0),
        "steps_to_reproduce": finding.get("steps", [])
    }
