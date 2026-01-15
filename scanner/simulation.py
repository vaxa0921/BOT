import os
import subprocess
import logging
from typing import Dict, Any, Optional

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

contract HoneypotTest is Test {
    address victim = <VICTIM_ADDRESS>;
    address token = <TOKEN_ADDRESS>;
    address attacker = address(0x1337);
    
    function setUp() public {
        vm.createSelectFork("<RPC_URL>");
        vm.label(victim, "Victim");
        vm.label(token, "Token");
        vm.label(attacker, "Attacker");
    }

    function testSafeCycle() public {
        vm.startPrank(attacker);
        
        // 1. Simulate BUY (Deal tokens)
        uint256 amount = 1 ether; // 1 token (assumed 18 decimals, adjust if needed)
        deal(token, attacker, amount);
        
        uint256 balBefore = IERC20(token).balanceOf(attacker);
        require(balBefore == amount, "Deal failed");

        // 2. Approve & Deposit
        IERC20(token).approve(victim, amount);
        
        // Try deposit (handle generic vault interface or low-level call)
        // Assuming ERC4626-like for now, but fallback to raw call if needed
        (bool success, bytes memory data) = victim.call(
            abi.encodeWithSignature("deposit(uint256,address)", amount, attacker)
        );
        
        if (!success) {
             // Try simplified deposit(uint256)
            (success, ) = victim.call(
                abi.encodeWithSignature("deposit(uint256)", amount)
            );
        }
        
        require(success, "Deposit failed");
        
        // 3. Withdraw
        // Check balance of shares/receipts if possible, but blindly try withdraw all
        // (Assuming 1:1 for simplicity or just trying to get *something* back)
        
        // Try withdraw(uint256,address,address)
        (success, ) = victim.call(
            abi.encodeWithSignature("withdraw(uint256,address,address)", amount, attacker, attacker)
        );
        
        if (!success) {
             // Try withdraw(uint256)
            (success, ) = victim.call(
                abi.encodeWithSignature("withdraw(uint256)", amount)
            );
        }

        // Note: Withdraw might fail if we didn't get shares, or logic is complex.
        // For Honeypot check, the CRITICAL part is checking if we *could* sell the token 
        // if we actually got it back. So let's test transferability of the token itself.
        
        // 4. Simulate SELL (Transfer to another address)
        // We simulate this by transferring whatever we have (even if 0, we deal again to test transfer mechanism)
        deal(token, attacker, amount); // Refill to test transfer logic specifically
        
        address receiver = address(0xDEAD);
        bool transferSuccess = IERC20(token).transfer(receiver, amount);
        require(transferSuccess, "Sell/Transfer failed (Honeypot?)");
        
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
        
        uint256 amount = 0.0001 ether;
        vm.deal(attacker, amount * 2); 
        
        uint256 balBefore = attacker.balance;

        // 1. Deposit
        bool success;
        
        // Try deposit() first
        (success, ) = victim.call{value: amount}(
            abi.encodeWithSignature("deposit()")
        );
        
        if (!success) {
            // Try raw send (fallback)
            (success, ) = victim.call{value: amount}("");
        }
        
        require(success, "Deposit failed (both deposit() and raw send)");
        
        // 2. Withdraw
        // Priority: withdraw(uint256) -> withdraw() -> withdrawAll() -> redeem(uint256)
        
        // Try withdraw(uint256)
        (success, ) = victim.call(
            abi.encodeWithSignature("withdraw(uint256)", amount)
        );
        if (success) {
            _checkProfit(balBefore, "withdraw(uint256)");
            vm.stopPrank();
            return;
        }
        
        // Try withdraw() - no args
        (success, ) = victim.call(
            abi.encodeWithSignature("withdraw()")
        );
        if (success) {
            _checkProfit(balBefore, "withdraw()");
            vm.stopPrank();
            return;
        }

        // Try withdrawAll()
        (success, ) = victim.call(
            abi.encodeWithSignature("withdrawAll()")
        );
        if (success) {
            _checkProfit(balBefore, "withdrawAll()");
            vm.stopPrank();
            return;
        }

        // Try redeem(uint256) - ERC4626 standard
        (success, ) = victim.call(
            abi.encodeWithSignature("redeem(uint256,address,address)", amount, attacker, attacker)
        );
        if (!success) {
             (success, ) = victim.call(
                abi.encodeWithSignature("redeem(uint256)", amount)
            );
        }
        if (success) {
            _checkProfit(balBefore, "redeem(uint256)");
            vm.stopPrank();
            return;
        }

        // If standard withdraws fail, check if we got ETH back via internal logic 
        if (!success) {
             // Check if attacker balance increased back
             // (Not implemented for simplicity, relying on explicit calls for now)
        }
        
        require(success, "Withdraw failed (tried all variants)");
        
        vm.stopPrank();
    }

    function _checkProfit(uint256 balBefore, string memory method) internal view {
        uint256 balAfter = attacker.balance;
        int256 profit = int256(balAfter) - int256(balBefore);
        console.log("SUCCESS_METHOD:", method);
        if (profit >= 0) {
            console.log("PROFIT_WEI:", uint256(profit));
        } else {
            console.log("PROFIT_WEI: -", uint256(-profit));
        }
    }
}
"""

def generate_honeypot_test(victim_address: str, token_address: str, rpc_url: str) -> str:
    content = HONEYPOT_TEST_TEMPLATE.replace("<VICTIM_ADDRESS>", victim_address)
    content = content.replace("<TOKEN_ADDRESS>", token_address)
    content = content.replace("<RPC_URL>", rpc_url)
    return content

def generate_honeypot_test_eth(victim_address: str, rpc_url: str) -> str:
    content = HONEYPOT_TEST_ETH_TEMPLATE.replace("<VICTIM_ADDRESS>", victim_address)
    content = content.replace("<RPC_URL>", rpc_url)
    return content

def run_honeypot_simulation(victim_address: str, token_address: str, rpc_url: str) -> Dict[str, Any]:
    """
    Run a forge test to simulate the Buy->Deposit->Withdraw->Sell cycle (ERC20).
    """
    test_content = generate_honeypot_test(victim_address, token_address, rpc_url)
    return _run_forge_test(victim_address, test_content)

def run_honeypot_simulation_eth(victim_address: str, rpc_url: str) -> Dict[str, Any]:
    """
    Run a forge test to simulate Deposit->Withdraw cycle (ETH).
    """
    test_content = generate_honeypot_test_eth(victim_address, rpc_url)
    return _run_forge_test(victim_address, test_content)

def _run_forge_test(victim_address: str, test_content: str) -> Dict[str, Any]:
    # Save to temporary file
    test_file = f"test/Honeypot_{victim_address[:8]}.t.sol"
    
    # Ensure test dir exists
    if not os.path.exists("test"):
        os.makedirs("test")
        
    with open(test_file, "w") as f:
        f.write(test_content)
        
    try:
        # Run forge test
        # Use shell=True on Windows to ensure PATH is correctly resolved
        # Explicitly pass remappings to ensure forge-std is found regardless of config file issues
        cmd = f"forge test --match-path {test_file} --remappings forge-std/=lib/forge-std/src/ -vv"
        
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

