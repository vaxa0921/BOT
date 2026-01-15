"""Real impact calculation with TVL, percentage loss, gas cost."""
from typing import Dict, Any, List, Optional
from web3 import Web3
from scanner.config import (
    MAX_FEE_PER_GAS,
    WETH_ADDRESS,
    UNISWAP_V3_QUOTER,
    DEFAULT_POOL_FEES,
    KEY_TOKENS,
    SLIPPAGE_BPS,
    SWAP_CHUNK_WEI,
    UNISWAP_V3_FACTORY,
    TOP_TOKENS_DISCOVERY_BLOCKS
)


def calculate_real_impact(
    w3: Web3,
    contract_address: str,
    exploit_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Calculate real impact of exploit.

    Args:
        w3: Web3 instance
        contract_address: Contract address
        exploit_result: Exploit execution results

    Returns:
        Dictionary with impact calculations
    """
    # Get contract TVL
    tvl = get_tvl(w3, contract_address)
    
    # Calculate stolen amount
    stolen_wei = exploit_result.get("profit", 0)
    
    # Calculate percentage loss
    percentage_loss = 0.0
    if tvl > 0:
        percentage_loss = (stolen_wei / tvl) * 100
    
    # Calculate gas cost
    gas_cost = calculate_gas_cost(exploit_result.get("gas_used", 0))
    
    # Net profit (stolen - gas)
    net_profit = stolen_wei - gas_cost
    
    # Forecast ETH PnL for roundtrip (using chunk size)
    asset_addr = get_asset_address(w3, contract_address)
    forecast_pnl_eth = 0
    if asset_addr:
        forecast_pnl_eth = forecast_roundtrip_eth_pnl(w3, asset_addr, SWAP_CHUNK_WEI)
    
    return {
        "contract": contract_address,
        "tvl_wei": tvl,
        "stolen_wei": stolen_wei,
        "percentage_loss": percentage_loss,
        "gas_cost_wei": gas_cost,
        "net_profit_wei": net_profit,
        "impact_level": _classify_impact(stolen_wei, percentage_loss),
        "forecast_pnl_eth_wei": forecast_pnl_eth
    }


def get_tvl(
    w3: Web3,
    contract_address: str
) -> int:
    """
    Get Total Value Locked for contract.

    Args:
        w3: Web3 instance
        contract_address: Contract address

    Returns:
        TVL in wei
    """
    # Try vault-like methods first
    try:
        abi = [
            {"inputs": [], "name": "totalAssets", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
            {"inputs": [], "name": "asset", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
            {"inputs": [], "name": "token", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
        ]
        c = w3.eth.contract(address=contract_address, abi=abi)
        total_assets = c.functions.totalAssets().call(block_identifier="pending")
        if total_assets > 0:
            return int(total_assets)
    except Exception:
        pass
    # ETH balance
    tvl = w3.eth.get_balance(contract_address, block_identifier="pending")
    # ERC20 balances
    erc20_abi = [
        {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
    ]
    # Try asset()/token()
    asset_addr = get_asset_address(w3, contract_address)
    token_list = list(KEY_TOKENS)
    # Dynamically discover top tokens via Uniswap V3
    try:
        discovered = discover_top_tokens_via_uniswap_v3(w3, limit=100)
        for t in discovered:
            if t not in token_list:
                token_list.append(t)
    except Exception:
        pass
    if asset_addr:
        token_list.append(asset_addr)
    for token in token_list:
        try:
            t = w3.eth.contract(address=token, abi=erc20_abi)
            tvl += int(t.functions.balanceOf(contract_address).call(block_identifier="pending"))
        except Exception:
            continue
    return tvl

def calculate_safe_min_amount_out(
    amount_in_wei: int,
    expected_amount_out_wei: int,
    gas_cost_wei: int = 0,
    min_profit_wei: int = 0
) -> int:
    """
    Calculate strict minAmountOut to ensure profitability.
    Ensures that we don't buy if the price moves such that we lose money.
    
    Formula: minAmountOut = max(
        expected_amount_out_wei * (1 - SLIPPAGE_BPS/10000),
        amount_in_wei + gas_cost_wei + min_profit_wei
    )
    """
    slippage_out = int(expected_amount_out_wei * (1 - SLIPPAGE_BPS / 10000))
    breakeven_out = amount_in_wei + gas_cost_wei + min_profit_wei
    
    # If standard slippage allows price to drop BELOW breakeven, we must raise the floor to breakeven.
    return max(slippage_out, breakeven_out)


def calculate_gas_cost(
    gas_used: int,
    gas_price_wei: int = None
) -> int:
    """
    Calculate gas cost in wei.

    Args:
        gas_used: Gas used
        gas_price_gwei: Gas price in gwei

    Returns:
        Gas cost in wei
    """
    price = gas_price_wei if gas_price_wei is not None else MAX_FEE_PER_GAS
    return gas_used * price


def calculate_tvl_percentage_loss(
    tvl: int,
    stolen: int
) -> float:
    """
    Calculate percentage of TVL lost.

    Args:
        tvl: Total Value Locked
        stolen: Amount stolen

    Returns:
        Percentage loss
    """
    if tvl == 0:
        return 0.0
    return (stolen / tvl) * 100


def _classify_impact(
    stolen_wei: int,
    percentage_loss: float
) -> str:
    """
    Classify impact level.

    Args:
        stolen_wei: Amount stolen in wei
        percentage_loss: Percentage of TVL lost

    Returns:
        Impact classification
    """
    if stolen_wei >= 10**20 or percentage_loss >= 50:
        return "CRITICAL"
    elif stolen_wei >= 10**19 or percentage_loss >= 10:
        return "HIGH"
    elif stolen_wei >= 10**18 or percentage_loss >= 1:
        return "MEDIUM"
    else:
        return "LOW"


def get_token_price_in_weth(
    w3: Web3,
    token: str,
    amount_in_wei: int
) -> int:
    quoter_abi = [
        {"inputs":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"pure","type":"function"}
    ]
    quoter = w3.eth.contract(address=UNISWAP_V3_QUOTER, abi=quoter_abi)
    best = 0
    for fee in DEFAULT_POOL_FEES:
        try:
            out = quoter.functions.quoteExactInputSingle(token, WETH_ADDRESS, fee, amount_in_wei, 0).call()
            if out > best:
                best = out
        except Exception:
            continue
    return best


def get_asset_address(
    w3: Web3,
    contract_address: str
) -> str:
    abi = [
        {"inputs": [], "name": "asset", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "token", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    ]
    try:
        c = w3.eth.contract(address=contract_address, abi=abi)
        try:
            return c.functions.asset().call()
        except Exception:
            return c.functions.token().call()
    except Exception:
        return ""


def forecast_roundtrip_eth_pnl(
    w3: Web3,
    token: str,
    eth_in_wei: int
) -> int:
    quoter_abi = [
        {"inputs":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"pure","type":"function"}
    ]
    q = w3.eth.contract(address=UNISWAP_V3_QUOTER, abi=quoter_abi)
    best_out_token = 0
    for fee in DEFAULT_POOL_FEES:
        try:
            out = q.functions.quoteExactInputSingle(WETH_ADDRESS, token, fee, eth_in_wei, 0).call()
            if out > best_out_token:
                best_out_token = out
        except Exception:
            continue
    if best_out_token == 0:
        return 0
    out_token_after_slip = int(best_out_token * (10000 - SLIPPAGE_BPS) // 10000)
    best_back_eth = 0
    for fee in DEFAULT_POOL_FEES:
        try:
            back = q.functions.quoteExactInputSingle(token, WETH_ADDRESS, fee, out_token_after_slip, 0).call()
            if back > best_back_eth:
                best_back_eth = back
        except Exception:
            continue
    if best_back_eth == 0:
        return 0
    back_eth_after_slip = int(best_back_eth * (10000 - SLIPPAGE_BPS) // 10000)
    return back_eth_after_slip - eth_in_wei


def discover_top_tokens_via_uniswap_v3(
    w3: Web3,
    limit: int = 100
) -> List[str]:
    factory_abi = [
        {"anonymous":False,"inputs":[
            {"indexed":True,"internalType":"address","name":"token0","type":"address"},
            {"indexed":True,"internalType":"address","name":"token1","type":"address"},
            {"indexed":False,"internalType":"uint24","name":"fee","type":"uint24"},
            {"indexed":False,"internalType":"int24","name":"tickSpacing","type":"int24"},
            {"indexed":False,"internalType":"address","name":"pool","type":"address"}
        ],"name":"PoolCreated","type":"event"}
    ]
    factory = w3.eth.contract(address=UNISWAP_V3_FACTORY, abi=factory_abi)
    latest = w3.eth.block_number
    start = max(latest - TOP_TOKENS_DISCOVERY_BLOCKS, 0)
    try:
        logs = factory.events.PoolCreated().get_logs(fromBlock=start, toBlock=latest)
        freq: Dict[str, int] = {}
        for ev in logs:
            t0 = ev["args"]["token0"]
            t1 = ev["args"]["token1"]
            freq[t0] = freq.get(t0, 0) + 1
            freq[t1] = freq.get(t1, 0) + 1
        # Sort tokens by frequency
        top = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [addr for addr, _ in top[:limit]]
    except Exception:
        return []


def create_loss_proof_snapshot(
    w3: Web3,
    contract_address: str,
    block_before: int,
    block_after: int
) -> Dict[str, Any]:
    """
    Create snapshot of loss proof.

    Args:
        w3: Web3 instance
        contract_address: Contract address
        block_before: Block before exploit
        block_after: Block after exploit

    Returns:
        Snapshot with proof data
    """
    balance_before = w3.eth.get_balance(contract_address, block_identifier=block_before)
    balance_after = w3.eth.get_balance(contract_address, block_identifier=block_after)
    
    loss = balance_before - balance_after
    
    return {
        "contract": contract_address,
        "block_before": block_before,
        "block_after": block_after,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "loss": loss,
        "proof": {
            "block_before": block_before,
            "block_after": block_after,
            "balance_before_hex": hex(balance_before),
            "balance_after_hex": hex(balance_after)
        }
    }
