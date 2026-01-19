from typing import Dict, Any, Optional
from web3 import Web3

def detect_sync_loss(w3: Web3, contract_address: str) -> Dict[str, Any]:
    """
    Detect Skimming/Sync Loss vulnerability in Uniswap V2-like pairs.
    Checks if token balance > reserve.
    """
    result = {"vulnerable": False, "type": "sync_loss", "details": ""}
    
    # Common ABI for UniV2 Pair
    abi = [
        {"constant":True,"inputs":[],"name":"getReserves","outputs":[{"name":"_reserve0","type":"uint112"},{"name":"_reserve1","type":"uint112"},{"name":"_blockTimestampLast","type":"uint32"}],"type":"function"},
        {"constant":True,"inputs":[],"name":"token0","outputs":[{"name":"","type":"address"}],"type":"function"},
        {"constant":True,"inputs":[],"name":"token1","outputs":[{"name":"","type":"address"}],"type":"function"},
    ]
    
    erc20_abi = [
         {"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"}
    ]

    try:
        pair = w3.eth.contract(address=contract_address, abi=abi)
        
        # Check if it's a pair
        try:
            r0, r1, _ = pair.functions.getReserves().call()
            t0 = pair.functions.token0().call()
            t1 = pair.functions.token1().call()
        except Exception:
            return result # Not a pair

        # Check Token 0
        token0 = w3.eth.contract(address=t0, abi=erc20_abi)
        bal0 = token0.functions.balanceOf(contract_address).call()
        
        if bal0 > r0:
            diff = bal0 - r0
            # Significant difference check (e.g. > 1%) or just any skim?
            # Usually skim attacks profit from any difference, but gas matters.
            if diff > 1000: # minimal dust filter
                result["vulnerable"] = True
                result["details"] = f"Token0 Balance ({bal0}) > Reserve0 ({r0}). Skimmable: {diff}"
                result["skim_amount"] = diff
                result["token"] = t0
                return result

        # Check Token 1
        token1 = w3.eth.contract(address=t1, abi=erc20_abi)
        bal1 = token1.functions.balanceOf(contract_address).call()
        
        if bal1 > r1:
            diff = bal1 - r1
            if diff > 1000:
                result["vulnerable"] = True
                result["details"] = f"Token1 Balance ({bal1}) > Reserve1 ({r1}). Skimmable: {diff}"
                result["skim_amount"] = diff
                result["token"] = t1
                return result

    except Exception:
        pass

    return result

def detect_uninitialized_reward(w3: Web3, contract_address: str) -> Dict[str, Any]:
    """
    Detect Uninitialized Reward Rate vulnerability in Staking/Farming contracts.
    Checks if totalSupply == 0 but rewardRate > 0.
    """
    result = {"vulnerable": False, "type": "uninitialized_reward", "details": ""}
    
    # Common ABI elements for Staking/MasterChef
    abi = [
        {"constant":True,"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"type":"function"},
        {"constant":True,"inputs":[],"name":"rewardRate","outputs":[{"name":"","type":"uint256"}],"type":"function"},
        {"constant":True,"inputs":[],"name":"periodFinish","outputs":[{"name":"","type":"uint256"}],"type":"function"},
        {"constant":True,"inputs":[],"name":"rewardPerToken","outputs":[{"name":"","type":"uint256"}],"type":"function"},
    ]
    
    try:
        contract = w3.eth.contract(address=contract_address, abi=abi)
        
        # Check totalSupply
        try:
            ts = contract.functions.totalSupply().call()
        except Exception:
            return result # No totalSupply, likely not a staking contract
            
        if ts != 0:
            return result # Not empty, so not "uninitialized" in the strict sense

        # Check rewardRate
        try:
            rr = contract.functions.rewardRate().call()
        except Exception:
            return result
            
        if rr > 0:
            # Confirm it's active
            try:
                pf = contract.functions.periodFinish().call()
                current_block = w3.eth.get_block('latest')
                ts_now = current_block['timestamp']
                if pf < ts_now:
                    return result # Rewards finished
            except Exception:
                pass # periodFinish might not exist, ignore

            # If we are here: TS=0, RR>0.
            # Check if rewardPerToken blows up or returns massive value
            try:
                rpt = contract.functions.rewardPerToken().call()
                # If RPT is huge or calculation works, this is a prime target for "First Depositor" getting ALL rewards instantly
                result["vulnerable"] = True
                result["details"] = f"TotalSupply=0, RewardRate={rr}. First staker may drain rewards."
                result["reward_rate"] = rr
            except Exception:
                # If it reverts, it might be division by zero (which is also a bug, but maybe not profitable unless handled)
                pass

    except Exception:
        pass
        
    return result

def detect_timestamp_dependence(w3: Web3, contract_address: str) -> Dict[str, Any]:
    """
    Detect Sequencer Path Independence / Timestamp Mismatch vulnerability.
    Checks for TIMESTAMP (0x42) usage in contracts with withdraw/execute functions.
    """
    result = {"vulnerable": False, "type": "timestamp_dependence", "details": ""}
    try:
        code = w3.eth.get_code(contract_address)
        if not code:
            return result
            
        # TIMESTAMP opcode is 0x42
        has_timestamp = b'\x42' in code
        
        # Check for withdraw/execute selectors
        # withdraw(uint256) -> 2e1a7d4d
        # withdraw() -> 3ccfd60b
        # execute() -> 61461954
        # claim() -> 4e71d92d
        # refund() -> 590e1ae3
        withdraw_sigs = [
            b'\x2e\x1a\x7d\x4d',
            b'\x3c\xcf\xd6\x0b',
            b'\x61\x46\x19\x54',
            b'\x4e\x71\xd9\x2d',
            b'\x59\x0e\x1a\xe3'
        ]
        
        has_withdraw = any(sig in code for sig in withdraw_sigs)
        
        if has_timestamp and has_withdraw:
            result["vulnerable"] = True
            result["details"] = "Found TIMESTAMP (0x42) and withdraw/execute function. Potential Flashblock/Timestamp vulnerability."
            return result
            
    except Exception:
        pass
        
    return result

def detect_ghost_liquidity(w3: Web3, contract_address: str) -> Dict[str, Any]:
    """
    Detect Ghost Liquidity / Missing address(0) check in initialization.
    Tries to call initialize(address(0)) to see if it succeeds.
    """
    result = {"vulnerable": False, "type": "ghost_liquidity", "details": ""}
    
    # Common init selectors
    # initialize(address) -> c4d66de8
    # init(address) -> 2fc25143
    # setup(address) -> 9b9ad821
    selectors = [
        "0xc4d66de8", # initialize(address)
        "0x2fc25143", # init(address)
        "0x9b9ad821", # setup(address)
    ]
    
    # Payload: selector + 32 bytes of zeros (address(0))
    payload_tail = b'\x00' * 32
    
    for sel in selectors:
        try:
            data = bytes.fromhex(sel[2:]) + payload_tail
            # Simulate call
            w3.eth.call({
                "to": contract_address,
                "data": data
            })
            # If no exception, it succeeded!
            result["vulnerable"] = True
            result["details"] = f"Function {sel} accepts address(0) without revert. Ghost Liquidity risk."
            result["selector"] = sel
            return result
        except Exception:
            continue
            
    return result

def detect_l1_l2_alias(w3: Web3, contract_address: str) -> Dict[str, Any]:
    """
    Detect L1-to-L2 Alias Address vulnerability.
    Checks if owner/admin is an address with no code/nonce on Base (L2).
    """
    result = {"vulnerable": False, "type": "l1_l2_alias", "details": ""}
    
    # Check owner
    # owner() -> 8da5cb5b
    try:
        owner_addr = None
        try:
            c = w3.eth.contract(address=contract_address, abi=[{"inputs":[],"name":"owner","outputs":[{"type":"address"}],"type":"function"}])
            owner_addr = c.functions.owner().call()
        except Exception:
            pass
            
        if not owner_addr:
            try:
                c = w3.eth.contract(address=contract_address, abi=[{"inputs":[],"name":"admin","outputs":[{"type":"address"}],"type":"function"}])
                owner_addr = c.functions.admin().call()
            except Exception:
                pass
        
        if owner_addr and owner_addr != "0x0000000000000000000000000000000000000000":
            # Check if owner exists on L2
            code = w3.eth.get_code(owner_addr)
            nonce = w3.eth.get_transaction_count(owner_addr)
            
            if code == b'' and nonce == 0:
                result["vulnerable"] = True
                result["details"] = f"Owner {owner_addr} has no code/nonce on Base. Potential L1-L2 Alias issue."
                result["owner"] = owner_addr
                return result
                
    except Exception:
        pass
        
    return result

def detect_replay_vulnerability(w3: Web3, contract_address: str) -> Dict[str, Any]:
    """
    Detect potential Cross-Chain Replay vulnerability (EIP-712 missing CHAINID).
    Checks if contract has 'permit' selector but lacks CHAINID (0x46) opcode.
    """
    result = {"vulnerable": False, "type": "replay_vulnerability", "details": ""}
    try:
        code = w3.eth.get_code(contract_address)
        if not code:
            return result
            
        # Selectors for permit
        # permit(address,address,uint256,uint256,uint8,bytes32,bytes32) -> d505accf
        has_permit = b'\xd5\x05\xac\xcf' in code
        
        # CHAINID opcode is 0x46
        has_chainid = b'\x46' in code
        
        if has_permit and not has_chainid:
            result["vulnerable"] = True
            result["details"] = "Found 'permit' function but missing CHAINID (0x46) opcode. Vulnerable to Cross-Chain Replay."
            return result
            
    except Exception:
        pass
        
    return result


def detect_public_payout_config(w3: Web3, contract_address: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"vulnerable": False, "type": "public_payout_config", "details": ""}
    try:
        addr = Web3.to_checksum_address(contract_address)
    except Exception:
        return result

    try:
        code = w3.eth.get_code(addr)
        if not code:
            return result
    except Exception:
        return result

    attacker = "0x1337000000000000000000000000000000000000"
    attacker_bytes = bytes.fromhex(attacker[2:].rjust(64, "0"))

    candidates = [
        "setRecipient(address)",
        "setReceiver(address)",
        "setBeneficiary(address)",
        "setPayout(address)",
        "setFeeRecipient(address)",
        "setTreasury(address)",
        "setOwner(address)",
    ]

    for sig in candidates:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + attacker_bytes
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential public payout configuration."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            return result
        except Exception:
            continue

    return result

def detect_sequencer_fee_manipulation(w3: Web3, contract_address: str) -> Dict[str, Any]:
    """
    Detect Sequencer Fee Manipulation vulnerability.
    Checks for GASPRICE (0x3a) or BASEFEE (0x48) usage combined with CALL (0xf1) in bytecode.
    """
    result = {"vulnerable": False, "type": "sequencer_fee", "details": ""}
    try:
        code = w3.eth.get_code(contract_address)
        if not code:
            return result
        
        # 0x3a is GASPRICE, 0x48 is BASEFEE, 0xf1 is CALL
        has_gasprice = b'\x3a' in code
        has_basefee = b'\x48' in code
        has_call = b'\xf1' in code
        
        # Additional filter: Must have BALANCE (0x31) or RETURNDATASIZE (0x3d) to imply refund logic
        has_balance = b'\x31' in code
        has_returndatasize = b'\x3d' in code
        
        if (has_gasprice or has_basefee) and has_call and (has_balance or has_returndatasize):
             result["vulnerable"] = True
             result["details"] = "Found GASPRICE/BASEFEE + CALL + BALANCE/RETURNDATASIZE in bytecode."
             return result
             
    except Exception:
        pass
        
    return result

def detect_self_destruct_reincarnation(w3: Web3, contract_address: str) -> Dict[str, Any]:
    """
    Detect Self-Destruct vulnerability.
    Checks for SELFDESTRUCT (0xff) AND presence of known public selectors.
    If CREATE2 (0xf5) is also present, flags as Reincarnation.
    """
    result = {"vulnerable": False, "type": "self_destruct_reincarnation", "details": ""}
    try:
        code = w3.eth.get_code(contract_address)
        if not code:
            return result
            
        # 0xf5 is CREATE2, 0xff is SELFDESTRUCT, 0xf4 is DELEGATECALL
        has_create2 = b'\xf5' in code
        has_selfdestruct = b'\xff' in code
        
        if not has_selfdestruct:
            return result

        # Check for known selectors to ensure it's likely exploitable/public
        # kill, destroy, suicide, close, die, shutdown
        known_selectors = [
            bytes.fromhex("41c0e1b5"), # kill()
            bytes.fromhex("83197ef0"), # destroy()
            bytes.fromhex("cbf0b0c0"), # suicide()
            bytes.fromhex("43d726d6"), # close()
            bytes.fromhex("35f46994"), # die()
            bytes.fromhex("0c55699c")  # shutdown()
        ]
        
        has_selector = any(sel in code for sel in known_selectors)
        
        if not has_selector:
            # If no known selector found, it's likely internal or protected or unknown name.
            # Skip to reduce false positives/unexploitable noise.
            return result

        if has_create2:
            result["vulnerable"] = True
            result["details"] = "Found SELFDESTRUCT and CREATE2 with known selector. Potential Reincarnation factory."
            return result
            
        # Also flag if just SELFDESTRUCT with known selector (simple self-destruct)
        result["vulnerable"] = True
        result["details"] = "Found SELFDESTRUCT with known selector."
        return result

    except Exception:
        pass
        
    return result

def detect_unprotected_initialize(w3: Web3, contract_address: str) -> Dict[str, Any]:
    """
    Detects if a contract has an 'initialize' function that is public and uncalled.
    (Simple static check for selector presence, dynamic check via simulation required later).
    Selector: initialize() -> 0x8129fc1c
    """
    result = {"vulnerable": False, "type": "unprotected_initialize", "details": ""}
    try:
        code = w3.eth.get_code(contract_address)
        if not code:
            return result
            
        # initialize() selector
        if bytes.fromhex("8129fc1c") in code:
             # Just a hint for the simulator to try calling it
             # We mark it as 'potential' so the simulator picks it up
             # The simulator will determine if it's actually callable/profitable.
             # For now, we don't flag it as vulnerable to avoid spam, 
             # but we could return a specific type to trigger a custom simulation.
             pass

    except Exception:
        pass
    return result


def detect_public_owner_change(w3: Web3, contract_address: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"vulnerable": False, "type": "public_owner_change", "details": ""}
    try:
        addr = Web3.to_checksum_address(contract_address)
    except Exception:
        return result

    try:
        code = w3.eth.get_code(addr)
        if not code:
            return result
    except Exception:
        return result

    attacker = "0x1337000000000000000000000000000000000000"
    attacker_bytes = bytes.fromhex(attacker[2:].rjust(64, "0"))

    candidates = [
        "transferOwnership(address)",
        "setOwner(address)",
        "setAdmin(address)",
        "setGovernor(address)",
        "setController(address)",
    ]

    for sig in candidates:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + attacker_bytes
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential public owner change."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            return result
        except Exception:
            continue

    return result


def detect_public_fee_change(w3: Web3, contract_address: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"vulnerable": False, "type": "public_fee_change", "details": ""}
    try:
        addr = Web3.to_checksum_address(contract_address)
    except Exception:
        return result

    try:
        code = w3.eth.get_code(addr)
        if not code:
            return result
    except Exception:
        return result

    fee_value = (10**9).to_bytes(32, "big")

    candidates = [
        "setFee(uint256)",
        "setWithdrawalFee(uint256)",
        "setPerformanceFee(uint256)",
        "setManagementFee(uint256)",
    ]

    for sig in candidates:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + fee_value
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential public fee configuration."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            result["fee_value"] = int.from_bytes(fee_value, "big")
            return result
        except Exception:
            continue

    return result


def detect_unrestricted_mint(w3: Web3, contract_address: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"vulnerable": False, "type": "unrestricted_mint", "details": ""}
    try:
        addr = Web3.to_checksum_address(contract_address)
    except Exception:
        return result

    try:
        code = w3.eth.get_code(addr)
        if not code:
            return result
    except Exception:
        return result

    attacker = "0x1337000000000000000000000000000000000000"
    attacker_bytes = bytes.fromhex(attacker[2:].rjust(64, "0"))
    amount = (10**24).to_bytes(32, "big")

    two_arg_sigs = [
        "mint(address,uint256)",
        "mintTo(address,uint256)",
    ]

    one_arg_sigs = [
        "mint(uint256)",
    ]

    for sig in two_arg_sigs:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + attacker_bytes + amount
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential unrestricted mint."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            result["amount"] = int.from_bytes(amount, "big")
            return result
        except Exception:
            continue

    for sig in one_arg_sigs:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + amount
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential unrestricted mint."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            result["amount"] = int.from_bytes(amount, "big")
            return result
        except Exception:
            continue

    return result


def detect_public_token_sweep(w3: Web3, contract_address: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"vulnerable": False, "type": "public_token_sweep", "details": ""}
    try:
        addr = Web3.to_checksum_address(contract_address)
    except Exception:
        return result

    try:
        code = w3.eth.get_code(addr)
        if not code:
            return result
    except Exception:
        return result

    attacker = "0x1337000000000000000000000000000000000000"
    attacker_bytes = bytes.fromhex(attacker[2:].rjust(64, "0"))
    amount = (10**24).to_bytes(32, "big")

    address_only_sigs = [
        "sweepToken(address)",
        "recoverERC20(address)",
    ]

    address_amount_sigs = [
        "recoverERC20(address,uint256)",
        "rescueFunds(address,uint256)",
    ]

    for sig in address_only_sigs:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + attacker_bytes
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential public token sweep."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            return result
        except Exception:
            continue

    for sig in address_amount_sigs:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + attacker_bytes + amount
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential public token sweep."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            result["amount"] = int.from_bytes(amount, "big")
            return result
        except Exception:
            continue

    return result


def detect_public_guardian_config(w3: Web3, contract_address: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"vulnerable": False, "type": "public_guardian_config", "details": ""}
    try:
        addr = Web3.to_checksum_address(contract_address)
    except Exception:
        return result

    try:
        code = w3.eth.get_code(addr)
        if not code:
            return result
    except Exception:
        return result

    attacker = "0x1337000000000000000000000000000000000000"
    attacker_bytes = bytes.fromhex(attacker[2:].rjust(64, "0"))
    enabled = (1).to_bytes(32, "big")

    address_only_sigs = [
        "setGuardian(address)",
        "setEmergencyAdmin(address)",
    ]

    bool_sigs = [
        "setPause(bool)",
        "setEmergencyPause(bool)",
        "setGuardianPause(bool)",
    ]

    for sig in address_only_sigs:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + attacker_bytes
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential public guardian configuration."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            return result
        except Exception:
            continue

    for sig in bool_sigs:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + enabled
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential public pause/guardian toggle."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            return result
        except Exception:
            continue

    return result


def detect_public_limit_config(w3: Web3, contract_address: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"vulnerable": False, "type": "public_limit_config", "details": ""}
    try:
        addr = Web3.to_checksum_address(contract_address)
    except Exception:
        return result

    try:
        code = w3.eth.get_code(addr)
        if not code:
            return result
    except Exception:
        return result

    new_limit = (10**36).to_bytes(32, "big")

    candidates = [
        "setDepositLimit(uint256)",
        "setCap(uint256)",
        "setSupplyCap(uint256)",
        "setBorrowCap(uint256)",
    ]

    for sig in candidates:
        try:
            selector = Web3.keccak(text=sig)[:4]
            if selector not in code:
                continue
            data = selector + new_limit
            w3.eth.call({"to": addr, "data": data})
            result["vulnerable"] = True
            result["details"] = f"{sig} callable without revert; potential public limit configuration."
            result["signature"] = sig
            result["selector"] = "0x" + selector.hex()
            result["limit"] = int.from_bytes(new_limit, "big")
            return result
        except Exception:
            continue

    return result
