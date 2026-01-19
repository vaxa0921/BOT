from web3 import Web3
from typing import Dict, Any, List, Optional
import logging
from eth_utils import to_checksum_address, keccak

logger = logging.getLogger(__name__)

# Base Mainnet Factories and Init Hashes
FACTORIES = {
    "AlienBase V2": {
        "address": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        "init_hash": "0x96e8ac4277198e1780e857922770e1f98e90cf961ef2e181f27508134db381d4"
    },
    "SushiSwap V2": {
        "address": "0x71524B4f93c58fcbF659783284E38825f0622859",
        "init_hash": "0xe18a34eb0e04b04f7a0ac29a6e80748dca96319b42c54d679cb821dca90c6303"
    },
    "BaseSwap": {
        "address": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB",
        "init_hash": "0xe18a34eb0e04b04f7a0ac29a6e80748dca96319b42c54d679cb821dca90c6303"
    },
    "Uniswap V3": {
        "address": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "init_hash": "0xe34f199b19b2b4f47f68442619d555527d244f78a3297ea89325f843f87b8b54"
    }
}

COMMON_BASES = {
    "WETH": "0x4200000000000000000000000000000000000006",
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "DAI": "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    "cbETH": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22"
}

def check_phantom_collision(w3: Web3, phantom_addr: str) -> Dict[str, Any]:
    """
    Check if a phantom address corresponds to a future contract deployment (CREATE2).
    """
    try:
        phantom_addr = to_checksum_address(phantom_addr)
    except Exception:
        return {"recoverable": False}
    
    # 1. Identify what tokens this address holds
    # We scan for common tokens because we likely don't know ALL tokens it holds.
    held_tokens = []
    
    # Also check if it holds ETH (WETH equivalent for V2 pairs)
    try:
        if w3.eth.get_balance(phantom_addr) > 0:
            if COMMON_BASES["WETH"] not in held_tokens:
                held_tokens.append(COMMON_BASES["WETH"])
    except Exception:
        pass

    for name, addr in COMMON_BASES.items():
        try:
            token = w3.eth.contract(address=addr, abi=[{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"}])
            bal = token.functions.balanceOf(phantom_addr).call()
            if bal > 0:
                held_tokens.append(addr)
        except Exception:
            pass
            
    # 2. Generate Candidate Pairs
    # We want to check Pair(HeldToken, BaseToken)
    candidates = []
    
    bases = list(COMMON_BASES.values())
    
    # If we found no tokens, we can try brute-forcing Bases vs Bases
    tokens_to_check = list(set(held_tokens + bases))
    
    for i in range(len(tokens_to_check)):
        for j in range(i + 1, len(tokens_to_check)):
            t0 = tokens_to_check[i]
            t1 = tokens_to_check[j]
            candidates.append((t0, t1))

    # 3. Check Factories
    for t0, t1 in candidates:
        token0, token1 = (t0, t1) if int(t0, 16) < int(t1, 16) else (t1, t0)
        
        for name, data in FACTORIES.items():
            # UniV2 / AlienBase Logic
            if "Uniswap V3" in name:
                # V3 needs fee tiers: 500, 3000, 10000
                fees = [500, 3000, 10000]
                for fee in fees:
                    try:
                        addr = _compute_v3_address(data["address"], token0, token1, fee, data["init_hash"])
                        if addr == phantom_addr:
                            return {
                                "recoverable": True,
                                "factory": name,
                                "type": "create2_collision",
                                "token0": token0,
                                "token1": token1,
                                "fee": fee,
                                "details": f"Address is pre-computed {name} Pool ({token0[:6]}.../{token1[:6]}... Fee {fee}). Deploy to claim!"
                            }
                    except Exception:
                        continue
            else:
                # V2 Standard
                try:
                    addr = _compute_v2_address(data["address"], token0, token1, data["init_hash"])
                    if addr == phantom_addr:
                         return {
                            "recoverable": True,
                            "factory": name,
                            "type": "create2_collision",
                            "token0": token0,
                            "token1": token1,
                            "details": f"Address is pre-computed {name} Pair ({token0[:6]}.../{token1[:6]}...). Deploy to claim!"
                        }
                except Exception:
                    continue

    return {"recoverable": False}

def _compute_v2_address(factory, token0, token1, init_hash):
    # keccak256(abi.encodePacked(token0, token1))
    packed = bytes.fromhex(token0[2:]) + bytes.fromhex(token1[2:])
    salt = keccak(packed)
    
    # keccak256(0xff ++ factory ++ salt ++ init_hash)
    pre = bytes.fromhex("ff") + bytes.fromhex(factory[2:]) + salt + bytes.fromhex(init_hash[2:])
    return to_checksum_address("0x" + keccak(pre).hex()[-40:])

def _compute_v3_address(factory, token0, token1, fee, init_hash):
    from eth_abi import encode
    salt = keccak(encode(['address', 'address', 'uint24'], [token0, token1, fee]))
    
    pre = bytes.fromhex("ff") + bytes.fromhex(factory[2:]) + salt + bytes.fromhex(init_hash[2:])
    return to_checksum_address("0x" + keccak(pre).hex()[-40:])
