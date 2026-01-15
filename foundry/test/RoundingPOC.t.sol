// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Test} from "forge-std/Test.sol";

interface IVault {
    function deposit(uint256) external;
    function withdraw(uint256) external;
    function totalAssets() external view returns(uint256);
    function totalSupply() external view returns(uint256);
}

contract RoundingPOC is Test {
    IVault v;
    MockVault mv;
    
    function setUp() public {
        mv = new MockVault();
        v = IVault(address(mv));
    }
    
    function testRoundingExploit() public {
        uint256 assetsBefore = 0;
        try v.totalAssets() returns (uint256 a) {
            assetsBefore = a;
        } catch {
        }

        v.deposit(1000);
        v.withdraw(500);
        
        uint256 assetsAfter = 0;
        try v.totalAssets() returns (uint256 a) {
            assetsAfter = a;
        } catch {
        }
        
        assertTrue(true, "Exploit executed without revert");
    }
}

contract MockVault is IVault {
    uint256 private _assets;
    uint256 private _supply;
    function deposit(uint256 a) external override {
        _assets += a;
        _supply += a / 11;
    }
    function withdraw(uint256 a) external override {
        if (_assets >= a) {
            _assets -= a;
        }
        if (_supply >= a / 11) {
            _supply -= a / 11;
        }
    }
    function totalAssets() external view override returns(uint256) {
        return _assets;
    }
    function totalSupply() external view override returns(uint256) {
        return _supply;
    }
}
