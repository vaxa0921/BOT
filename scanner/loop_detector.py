"""Loop and repetition detector."""
from typing import Dict, List, Any, Set
from collections import Counter


def detect_loops(
    operations: List[Dict[str, Any]],
    threshold: int = 3
) -> Dict[str, Any]:
    """
    Detect loops and repetitive operations.

    Args:
        operations: List of operations
        threshold: Minimum repetitions to consider a loop

    Returns:
        Dictionary with loop detection results
    """
    # Group operations by type and parameters
    operation_patterns = []
    
    for op in operations:
        pattern = {
            "type": op.get("type", "unknown"),
            "from": op.get("from", ""),
            "to": op.get("to", ""),
            "amount": op.get("amount", 0)
        }
        operation_patterns.append(str(pattern))
    
    # Count pattern occurrences
    pattern_counts = Counter(operation_patterns)
    
    loops = []
    for pattern, count in pattern_counts.items():
        if count >= threshold:
            loops.append({
                "pattern": pattern,
                "count": count,
                "is_loop": True
            })
    
    return {
        "has_loops": len(loops) > 0,
        "loops": loops,
        "loop_count": len(loops),
        "total_operations": len(operations)
    }


def detect_repetition(
    sequence: List[Any],
    min_length: int = 2
) -> List[Dict[str, Any]]:
    """
    Detect repeating patterns in sequence.

    Args:
        sequence: Sequence to analyze
        min_length: Minimum pattern length

    Returns:
        List of detected repetitions
    """
    repetitions = []
    n = len(sequence)
    
    for length in range(min_length, n // 2 + 1):
        for start in range(n - length * 2 + 1):
            pattern = sequence[start:start + length]
            next_pattern = sequence[start + length:start + length * 2]
            
            if pattern == next_pattern:
                # Check if pattern continues
                repeat_count = 2
                for i in range(2, (n - start) // length):
                    if sequence[start + i * length:start + (i + 1) * length] == pattern:
                        repeat_count += 1
                    else:
                        break
                
                repetitions.append({
                    "pattern": pattern,
                    "start": start,
                    "length": length,
                    "repeats": repeat_count
                })
    
    return repetitions
