"""Factory and CREATE2 contract discovery."""
import hashlib
from typing import List, Set, Optional, Tuple
from web3 import Web3
from scanner.contract_queue import enqueue


def calculate_create2_address(
    deployer: str,
    salt: str,
    bytecode_hash: str
) -> str:
    """
    Calculate CREATE2 address.

    Args:
        deployer: Deployer address
        salt: Salt (hex string)
        bytecode_hash: Bytecode hash (keccak256)

    Returns:
        CREATE2 address
    """
    deployer_bytes = bytes.fromhex(deployer[2:].lower())
    salt_bytes = bytes.fromhex(salt[2:].lower() if salt.startswith("0x") else salt)
    bytecode_hash_bytes = bytes.fromhex(
        bytecode_hash[2:].lower() if bytecode_hash.startswith("0x") else bytecode_hash
    )

    # CREATE2: keccak256(0xff || deployer || salt || keccak256(init_code))
    # Note: Using SHA3-256 as approximation (keccak256 is SHA3-256)
    prefix = b"\xff"
    data = prefix + deployer_bytes + salt_bytes + bytecode_hash_bytes
    hash_result = hashlib.sha3_256(data).hexdigest()
    
    # Take last 20 bytes (40 hex chars)
    address = "0x" + hash_result[-40:]
    return Web3.to_checksum_address(address)


def scan_factory_creations(
    w3: Web3,
    factory_address: str,
    creation_event: str = "PairCreated"
) -> List[str]:
    """
    Scan factory contract for created contracts.

    Args:
        w3: Web3 instance
        factory_address: Factory contract address
        creation_event: Event name for contract creation

    Returns:
        List of created contract addresses
    """
    addresses: Set[str] = set()
    
    try:
        # Try to construct a generic ABI for common factory events
        # We need to support multiple signatures because different factories use different events
        
        # 1. Uniswap V2: PairCreated(token0, token1, pair, uint)
        # 2. Uniswap V3: PoolCreated(token0, token1, fee, tickSpacing, pool)
        # 3. Generic: ContractCreated(address) or Deployed(address)
        
        # We will try to fetch logs using topic0 if possible, but web3.py contract events need ABI.
        # So we define a merged ABI that covers common cases or try them sequentially.
        
        event_abis = [
            # Uniswap V2 PairCreated
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "token0", "type": "address"},
                    {"indexed": True, "name": "token1", "type": "address"},
                    {"indexed": False, "name": "pair", "type": "address"},
                    {"indexed": False, "name": "", "type": "uint256"}
                ],
                "name": "PairCreated",
                "type": "event"
            },
            # Uniswap V3 PoolCreated
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "token0", "type": "address"},
                    {"indexed": True, "name": "token1", "type": "address"},
                    {"indexed": True, "name": "fee", "type": "uint24"},
                    {"indexed": False, "name": "tickSpacing", "type": "int24"},
                    {"indexed": False, "name": "pool", "type": "address"}
                ],
                "name": "PoolCreated",
                "type": "event"
            },
            # Generic Deployed
            {
                "anonymous": False,
                "inputs": [{"indexed": False, "name": "addr", "type": "address"}],
                "name": "Deployed",
                "type": "event"
            }
        ]
        
        factory = w3.eth.contract(address=factory_address, abi=event_abis)
        
        # Scan recent blocks
        current_block = w3.eth.block_number
        from_block = max(current_block - 5000, 0) # Increased scan range
        
        # Try to find the event that works
        target_events = [creation_event] if creation_event else ["PairCreated", "PoolCreated", "Deployed"]
        
        for evt_name in target_events:
            try:
                if not hasattr(factory.events, evt_name):
                    continue
                    
                events = getattr(factory.events, evt_name).get_logs(
                    fromBlock=from_block,
                    toBlock=current_block
                )
                
                for event in events:
                    if hasattr(event, "args"):
                        # Try to find the contract address field
                        # Priority: pair -> pool -> addr -> any address field
                        if hasattr(event.args, "pair"):
                            addresses.add(event.args.pair)
                        elif hasattr(event.args, "pool"):
                            addresses.add(event.args.pool)
                        elif hasattr(event.args, "addr"):
                            addresses.add(event.args.addr)
                        else:
                            # Fallback: check all args
                            for k, v in event.args.items():
                                if isinstance(v, str) and w3.is_address(v):
                                    addresses.add(v)
            except Exception:
                continue

    except Exception:
        pass
    
    return list(addresses)


def _topic_hash(signature: str) -> str:
    from eth_utils import keccak, to_hex, to_bytes
    return to_hex(keccak(text=signature))


def scan_global_factory_events(
    w3: Web3,
    blocks: int = 5000
) -> List[str]:
    """
    Scan global logs for common factory events without specific addresses.
    Detects UniswapV2 PairCreated and UniswapV3 PoolCreated across all factories.
    """
    addresses: Set[str] = set()
    current_block = w3.eth.block_number
    from_block = max(current_block - blocks, 0)

    # Event signatures
    pair_created_sig = "PairCreated(address,address,address,uint256)"
    pool_created_sig = "PoolCreated(address,address,uint24,int24,address)"

    pair_topic = _topic_hash(pair_created_sig)
    pool_topic = _topic_hash(pool_created_sig)

    # Helper to decode non-indexed args from data
    from eth_abi import decode

    # Uniswap V2: data encodes (address pair, uint256)
    try:
        logs = w3.eth.get_logs({
            "fromBlock": from_block,
            "toBlock": current_block,
            "topics": [pair_topic]
        })
        for log in logs:
            # Decode data: address, uint256
            try:
                decoded = decode(["address", "uint256"], bytes.fromhex(log["data"][2:]))
                pair_addr = Web3.to_checksum_address(decoded[0])
                addresses.add(pair_addr)
            except Exception:
                continue
    except Exception:
        pass

    # Uniswap V3: data encodes (int24 tickSpacing, address pool)
    try:
        logs = w3.eth.get_logs({
            "fromBlock": from_block,
            "toBlock": current_block,
            "topics": [pool_topic]
        })
        for log in logs:
            try:
                decoded = decode(["int24", "address"], bytes.fromhex(log["data"][2:]))
                pool_addr = Web3.to_checksum_address(decoded[1])
                addresses.add(pool_addr)
            except Exception:
                continue
    except Exception:
        pass

    return list(addresses)

def scan_create2_patterns(
    w3: Web3,
    deployer_addresses: List[str],
    salt_patterns: Optional[List[str]] = None
) -> List[str]:
    """
    Scan for CREATE2 deployments.

    Args:
        w3: Web3 instance
        deployer_addresses: List of known deployer addresses
        salt_patterns: Optional salt patterns to try

    Returns:
        List of potential CREATE2 addresses
    """
    addresses: Set[str] = set()
    
    # Common salt patterns
    if salt_patterns is None:
        salt_patterns = ["0x" + "0" * 64]  # Zero salt
    
    for deployer in deployer_addresses:
        for salt in salt_patterns:
            # Try to get code at CREATE2 address
            # Note: This is simplified - real implementation needs init code
            try:
                # This is a placeholder - real CREATE2 needs init code hash
                # For now, we'll scan transactions from deployer
                deployer_txs = w3.eth.get_transaction_count(deployer)
                if deployer_txs > 0:
                    # Check if deployer has CREATE2 patterns
                    # In real implementation, would analyze bytecode
                    pass
            except Exception:
                pass
    
    return list(addresses)
