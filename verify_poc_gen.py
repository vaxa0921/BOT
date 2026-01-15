import os
import sys
import json
from scanner.real_poc_generator import generate_fork_poc

# Mock exploit steps
exploit_steps = [
    {
        "description": "Initial deposit",
        "function": "deposit",
        "args": [1000],
        "value": 0
    },
    {
        "description": "Withdraw half",
        "function": "withdraw",
        "args": [500],
        "value": 0
    }
]

# Use a dummy address
contract_address = "0x0000000000000000000000000000000000000000"

# Generate PoC
# We expect this to fail execution because the address is dummy and RPC might fail or return nothing,
# but the file generation should succeed.
print("Generating PoC...")
result = generate_fork_poc(contract_address, exploit_steps, fork_url="https://eth.llamarpc.com")

print("Result keys:", result.keys())
print("Success:", result["success"])
if "test_file" in result:
    print("Test file generated at:", result["test_file"])
    if os.path.exists(result["test_file"]):
        print("File content:")
        with open(result["test_file"], "r") as f:
            print(f.read())
    else:
        print("File not found!")

if result["error"]:
    print("Error (expected if no RPC/contract):", result["error"])
