"""Configuration constants for the scanner."""
import os
from typing import List
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and value and key not in os.environ:
                os.environ[key] = value

RPC_HTTP: str = os.getenv("RPC_HTTP", "https://mainnet.base.org")
RPC_WSS: str = os.getenv("RPC_WSS", "wss://mainnet.base.org")

rpc_http_list_raw = os.getenv("RPC_HTTP_LIST", "")
rpc_wss_list_raw = os.getenv("RPC_WSS_LIST", "")

if rpc_http_list_raw:
    RPCS: List[str] = [u.strip() for u in rpc_http_list_raw.split(",") if u.strip()]
else:
    RPCS: List[str] = [RPC_HTTP]

if rpc_wss_list_raw:
    RPCS_WS: List[str] = [u.strip() for u in rpc_wss_list_raw.split(",") if u.strip()]
else:
    RPCS_WS: List[str] = [RPC_WSS]
USE_WS: bool = os.getenv("USE_WS", "1").lower() in ("1", "true", "yes")

WORKERS: int = int(os.getenv("WORKERS", "4"))
ALERT_CHECK_INTERVAL: int = 60

MAX_TX: int = 50
MIN_DRIFT_WEI: int = 100

# Provider limits / safety
MAX_LOG_RANGE_BLOCKS: int = int(os.getenv("MAX_LOG_RANGE_BLOCKS", "5"))
BLOCK_LAG: int = int(os.getenv("BLOCK_LAG", "0"))

# Backfill settings
BACKFILL_BATCH_SIZE: int = 100  # blocks per batch
BACKFILL_START_BLOCK: int = 0  # 0 = 100 blocks back from current
BACKFILL_END_BLOCK: int = 0  # 0 = current block
BACKFILL_BLOCKS_BACK: int = 43200  # 24 hours (assuming 2s block time)
REALTIME_ONLY: bool = os.getenv("REALTIME_ONLY", "0").lower() in ("1", "true", "yes")
FOT_ENABLE: bool = os.getenv("FOT_ENABLE", "1").lower() in ("1", "true", "yes")
FOT_SIM_AMOUNT_WEI: int = int(100 * 10**18)
FOT_SCREEN_AMOUNT_WEI: int = int(1000 * 10**18)
FOT_SLOT_BRUTEFORCE_MAX: int = 20
FOT_LIQUIDITY_IMPACT_BPS: int = 2000

FOT_USE_DEBUG_TRACE: bool = os.getenv("FOT_USE_DEBUG_TRACE", "").lower() in ("1", "true", "yes")
FOT_SCREEN_ONLY: bool = os.getenv("FOT_SCREEN_ONLY", "1").lower() in ("1", "true", "yes")
FOT_DEEP_CONCURRENCY: int = int(os.getenv("FOT_DEEP_CONCURRENCY", "2"))
FOT_CACHE_TTL_SEC: int = int(os.getenv("FOT_CACHE_TTL_SEC", "3600"))
FOT_ASYNC_DEEP: bool = os.getenv("FOT_ASYNC_DEEP", "1").lower() in ("1", "true", "yes")
FOT_DEEP_DEDUP_TTL_SEC: int = int(os.getenv("FOT_DEEP_DEDUP_TTL_SEC", "900"))

# Async batch settings
BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "50"))  # addresses per batch
ASYNC_CONCURRENT: int = int(os.getenv("ASYNC_CONCURRENT", "10"))  # concurrent requests

# Mode: keep only Fee-on-Transfer tests active
ONLY_FOT_MODE: bool = os.getenv("ONLY_FOT_MODE", "").lower() in ("1", "true", "yes")

# Factory Addresses
KNOWN_FACTORIES: List[str] = [
    "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",  # Uniswap V2 Factory / AlienBase V2
    "0x1F98431c8aD98523631AE4a59f267346ea31F984",  # Uniswap V3 Factory
    "0x1111111254fb6c44bAC0beD2854e76F90643097d",  # 1inch Aggregation Router
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC Proxy (Example)
    "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",  # Aerodrome Pool Factory
]
UNISWAP_V3_FACTORY: str = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

# Etherscan API (Optional)
ETHERSCAN_API_KEY: str = ""  # Leave empty if not used
BASESCAN_API_KEY: str = os.getenv("BASESCAN_API_KEY", "")

# ============================================================================
# AUTO-EXPLOIT SETTINGS (DANGER ZONE)
# ============================================================================
# Enable automatic execution of exploits on Mainnet
AUTO_EXPLOIT: bool = os.getenv("AUTO_EXPLOIT", "").lower() in ("1", "true", "yes")

# Your wallet private key (REQUIRED for auto-exploit)
# WARNING: Keep this safe! Never commit to git.
PRIVATE_KEY: str = os.getenv("PRIVATE_KEY", "") 

# Address to receive profits
MY_WALLET_ADDRESS: str = "0xE81F59678dFA84270E7d9f41608B9605a683c154"

# Gas Settings
MAX_PRIORITY_FEE: int = int(0.5 * 10**9)  # 0.5 Gwei for Base
MAX_FEE_PER_GAS: int = int(10 * 10**9)    # 10 Gwei cap

# Auto swap settings
AUTO_SWAP: bool = os.getenv("AUTO_SWAP", "").lower() in ("1", "true", "yes")
WETH_ADDRESS: str = "0x4200000000000000000000000000000000000006"  # Base WETH
UNISWAP_V3_ROUTER: str = "0xE592427A0AEce92De3Edee1F18E0157C05861564"  # Common V3 router
DEFAULT_POOL_FEES: List[int] = [500, 3000, 10000]

# Flash Loan Executor
FLASH_LOAN_EXECUTOR_ADDRESS: str = os.getenv("FLASH_LOAN_EXECUTOR_ADDRESS", "")
SLIPPAGE_BPS: int = 300  # 3%
UNISWAP_V3_QUOTER: str = "0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"

# Swap budgeting (very conservative for small balances)
GAS_BUFFER_WEI: int = int(0.0003 * 10**18)
MAX_SWAP_PCT: float = 0.25
SWAP_CHUNK_WEI: int = int(0.0002 * 10**18)
MAX_BET_SIZE_ETH: float = 0.0001
MAX_BET_SIZE_WEI: int = int(MAX_BET_SIZE_ETH * 10**18)

SKIP_VERIFIED: bool = os.getenv("SKIP_VERIFIED", "0").lower() in ("1", "true", "yes")

USE_FLASHLOAN: bool = True

# Profit guardrails
MIN_NET_PROFIT_WEI: int = int(0.00005 * 10**18)
ADAPTIVE_PROFIT_ENABLE: bool = True
ADAPTIVE_BASE_MIN_WEI: int = MIN_NET_PROFIT_WEI
ADAPTIVE_SLIPPAGE_SAFETY_BPS: int = 300
ADAPTIVE_GAS_MULTIPLIER: float = 1.5

LARGE_TRANSFER_THRESHOLD_WEI: int = int(1000 * 10**18)

# Key tokens for pricing (Base)
KEY_TOKENS: List[str] = [
    "0x4200000000000000000000000000000000000006",  # WETH
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC
]
TOP_TOKENS_DISCOVERY_BLOCKS: int = 10000
