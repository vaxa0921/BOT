"""Address alias mapping and resolution."""
import json
import os
from typing import Dict, Optional, Set
from pathlib import Path

ALIAS_FILE = Path("scanner/data/aliases.json")


def load_aliases() -> Dict[str, Set[str]]:
    """
    Load address aliases from file.

    Returns:
        Dictionary mapping canonical address to set of aliases
    """
    if not ALIAS_FILE.exists():
        return {}
    
    try:
        with open(ALIAS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Convert lists to sets
            return {
                k: set(v) if isinstance(v, list) else {v}
                for k, v in data.items()
            }
    except Exception:
        return {}


def save_aliases(aliases: Dict[str, Set[str]]) -> None:
    """
    Save address aliases to file.

    Args:
        aliases: Dictionary mapping canonical address to set of aliases
    """
    ALIAS_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert sets to lists for JSON
    data = {k: list(v) for k, v in aliases.items()}
    
    with open(ALIAS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def resolve_alias(address: str, aliases: Optional[Dict[str, Set[str]]] = None) -> str:
    """
    Resolve address to canonical form.

    Args:
        address: Address to resolve
        aliases: Optional alias dictionary (loads from file if None)

    Returns:
        Canonical address
    """
    if aliases is None:
        aliases = load_aliases()
    
    address_lower = address.lower()
    
    # Check if address is an alias
    for canonical, alias_set in aliases.items():
        if address_lower in alias_set or address_lower == canonical.lower():
            return canonical
    
    return address


def add_alias(canonical: str, alias: str) -> None:
    """
    Add an alias for an address.

    Args:
        canonical: Canonical address
        alias: Alias address
    """
    aliases = load_aliases()
    canonical_lower = canonical.lower()
    
    if canonical_lower not in aliases:
        aliases[canonical_lower] = set()
    
    aliases[canonical_lower].add(alias.lower())
    save_aliases(aliases)
