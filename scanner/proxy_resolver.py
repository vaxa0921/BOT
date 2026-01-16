"""Proxy to implementation resolver."""
from typing import Optional, Dict, Any
from web3 import Web3
import time

_IMPL_CACHE: Dict[str, Any] = {}


def get_implementation_address(
    w3: Web3,
    proxy_address: str,
    proxy_type: str = "eip1967"
) -> Optional[str]:
    """
    Get implementation address from proxy.

    Args:
        w3: Web3 instance
        proxy_address: Proxy contract address
        proxy_type: Proxy type (eip1967, eip1822, minimal, transparent)

    Returns:
        Implementation address or None
    """
    key = f"{proxy_type}:{proxy_address.lower()}"
    now = time.time()
    cached = _IMPL_CACHE.get(key)
    if cached is not None:
        impl_cached, ts_cached = cached
        if now - ts_cached < 3600:
            return impl_cached

    try:
        if proxy_type == "eip1967":
            # EIP-1967 storage slots
            implementation_slot = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
            admin_slot = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
            
            impl_bytes = w3.eth.get_storage_at(proxy_address, implementation_slot)
            if impl_bytes and impl_bytes != b"\x00" * 32:
                impl_address = "0x" + impl_bytes[-20:].hex()
                impl = Web3.to_checksum_address(impl_address)
                _IMPL_CACHE[key] = (impl, now)
                return impl
        
        elif proxy_type == "eip1822":
            # EIP-1822 UUPS
            impl_slot = "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7"
            impl_bytes = w3.eth.get_storage_at(proxy_address, impl_slot)
            if impl_bytes and impl_bytes != b"\x00" * 32:
                impl_address = "0x" + impl_bytes[-20:].hex()
                impl = Web3.to_checksum_address(impl_address)
                _IMPL_CACHE[key] = (impl, now)
                return impl
        
        elif proxy_type == "minimal":
            # Minimal proxy (clone) - implementation is in bytecode
            code = w3.eth.get_code(proxy_address).hex()
            if len(code) > 22:  # Has implementation address
                # Implementation address is typically at position 10-29
                impl_address = "0x" + code[10:50]
                impl = Web3.to_checksum_address(impl_address)
                _IMPL_CACHE[key] = (impl, now)
                return impl
        
        # Try to call implementation() function
        try:
            abi = [{"constant": True, "inputs": [], "name": "implementation", "outputs": [{"name": "", "type": "address"}], "type": "function"}]
            contract = w3.eth.contract(address=proxy_address, abi=abi)
            impl = contract.functions.implementation().call()
            if impl:
                _IMPL_CACHE[key] = (impl, now)
            return impl
        except Exception:
            pass
            
    except Exception:
        pass
    
    _IMPL_CACHE[key] = (None, now)
    return None


def resolve_proxy(w3: Web3, address: str) -> Dict[str, Any]:
    """
    Resolve proxy to implementation.

    Args:
        w3: Web3 instance
        address: Contract address

    Returns:
        Dictionary with proxy info
    """
    result = {
        "is_proxy": False,
        "proxy_type": None,
        "implementation": None,
        "admin": None
    }
    
    # Try different proxy types
    for proxy_type in ["eip1967", "eip1822", "minimal"]:
        impl = get_implementation_address(w3, address, proxy_type)
        if impl:
            result["is_proxy"] = True
            result["proxy_type"] = proxy_type
            result["implementation"] = impl
            break
    
    return result
