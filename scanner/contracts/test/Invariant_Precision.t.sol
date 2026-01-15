// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

import "forge-std/Test.sol";

interface ITarget {
    function totalSupply() external view returns (uint256);
    function balanceOf(address) external view returns (uint256);
}

contract Invariant_Precision is Test {
    ITarget target;

    function setUp() public {
        // address set dynamically by runner via env
        address addr = vm.envAddress("TARGET");
        target = ITarget(addr);
    }

    function invariant_noDustCreation() public {
        uint256 sum = 0;
        address[5] memory users = [
            address(0x1),
            address(0x2),
            address(0x3),
            address(0x4),
            address(0x5)
        ];

        for (uint i = 0; i < users.length; i++) {
            sum += target.balanceOf(users[i]);
        }

        // LOW impact: precision drift / dust
        assertLe(sum, target.totalSupply());
    }
}
