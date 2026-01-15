// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "contracts/SimpleStorage.sol";

contract InvariantTest {
    SimpleStorage s = new SimpleStorage();

    function invariant_no_rounding_drain() public {
        uint256 depositAmount = 1;
        s.set(depositAmount);
        uint256 ret = s.get();
        assert(ret <= depositAmount); // приклад інваріанта
    }
}
