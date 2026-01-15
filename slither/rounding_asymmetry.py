"""Slither detector for rounding asymmetry."""
from typing import List
from slither.detectors.abstract_detector import (
    AbstractDetector,
    DetectorClassification
)


class RoundingAsymmetryDetector(AbstractDetector):
    """Detector for rounding asymmetry in arithmetic operations."""

    ARGUMENT = "rounding-asymmetry"
    HELP = "Detect rounding asymmetry in arithmetic operations"
    IMPACT = DetectorClassification.HIGH

    def detect_contract(self, contract) -> List[str]:
        """
        Detect rounding asymmetry in contract.

        Args:
            contract: Contract to analyze

        Returns:
            List of findings
        """
        results: List[str] = []
        for function in contract.functions:
            for node in function.nodes:
                if node.expression:
                    expr = str(node.expression)
                    # простий heuristic для MUL/DIV
                    if "*" in expr and "/" in expr:
                        finding = (
                            f"{contract.name}.{function.name}: "
                            f"possible rounding asymmetry"
                        )
                        results.append(finding)
        return results
