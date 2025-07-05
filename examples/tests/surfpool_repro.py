#!/usr/bin/env python3
"""
Minimal reproduction of surfpool RPC parsing error.

Error: called `Result::unwrap()` on an `Err` value: Error("missing field `data`", line: 0, column: 0)

This error occurs when sending certain transactions through surfpool.
"""

import asyncio
import subprocess
import time
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solders.pubkey import Pubkey
from solders.hash import Hash


async def reproduce_error():
    """Reproduce the RPC parsing error with surfpool."""
    
    print("=" * 60)
    print("SURFPOOL RPC PARSING ERROR REPRODUCTION")
    print("=" * 60)
    
    # Version info
    print("\nEnvironment:")
    print("- Python: 3.12")
    print("- solana-py: 0.36.7")
    print("- surfpool: latest")
    
    # Start surfpool
    print("\n1. Starting surfpool...")
    proc = subprocess.Popen(
        ["surfpool", "start", "--no-tui"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**subprocess.os.environ, "CROSSTERM_DISABLE_RAW_MODE": "1"}
    )
    
    # Wait for it to be ready
    print("   Waiting for validator...")
    await asyncio.sleep(5)
    
    try:
        client = AsyncClient("http://localhost:8899")
        
        # Create test keypairs
        print("\n2. Creating test keypairs...")
        sender = Keypair()
        receiver = Keypair()
        print(f"   Sender: {sender.pubkey()}")
        print(f"   Receiver: {receiver.pubkey()}")
        
        # Fund sender
        print("\n3. Funding sender account...")
        airdrop_sig = await client.request_airdrop(sender.pubkey(), 2 * 10**9)
        await client.confirm_transaction(airdrop_sig.value)
        
        balance = await client.get_balance(sender.pubkey())
        print(f"   Sender balance: {balance.value / 10**9} SOL")
        
        # Get blockhash
        print("\n4. Getting recent blockhash...")
        blockhash_resp = await client.get_latest_blockhash()
        blockhash = blockhash_resp.value.blockhash
        
        # Test different transaction types
        print("\n5. Testing transactions...")
        
        # Case 1: Self-transfer (should work)
        print("\n   Case 1: Self-transfer")
        tx1 = Transaction().add(
            transfer(TransferParams(
                from_pubkey=sender.pubkey(),
                to_pubkey=sender.pubkey(),  # Self
                lamports=1000000
            ))
        )
        tx1.sign([sender], blockhash)
        
        try:
            sig1 = await client.send_transaction(tx1)
            await client.confirm_transaction(sig1.value)
            print("   ✅ Self-transfer succeeded")
        except Exception as e:
            print(f"   ❌ Self-transfer failed: {type(e).__name__}: {e}")
        
        # Case 2: Transfer to unfunded account (might fail)
        print("\n   Case 2: Transfer to unfunded account")
        tx2 = Transaction().add(
            transfer(TransferParams(
                from_pubkey=sender.pubkey(),
                to_pubkey=receiver.pubkey(),  # Unfunded
                lamports=1000000
            ))
        )
        tx2.sign([sender], blockhash)
        
        try:
            sig2 = await client.send_transaction(tx2)
            await client.confirm_transaction(sig2.value)
            print("   ✅ Transfer to unfunded account succeeded")
        except Exception as e:
            print(f"   ❌ Transfer to unfunded account failed: {type(e).__name__}: {e}")
            if "missing field `data`" in str(e):
                print("\n   🐛 BUG REPRODUCED!")
                print("   This is the RPC parsing error we're seeing.")
        
        # Case 3: Transfer to system program (might fail)
        print("\n   Case 3: Transfer to system program")
        tx3 = Transaction().add(
            transfer(TransferParams(
                from_pubkey=sender.pubkey(),
                to_pubkey=Pubkey.from_string("11111111111111111111111111111111"),
                lamports=1000000
            ))
        )
        tx3.sign([sender], blockhash)
        
        try:
            sig3 = await client.send_transaction(tx3)
            await client.confirm_transaction(sig3.value)
            print("   ✅ Transfer to system program succeeded")
        except Exception as e:
            print(f"   ❌ Transfer to system program failed: {type(e).__name__}: {e}")
            if "missing field `data`" in str(e):
                print("\n   🐛 BUG REPRODUCED!")
        
        await client.close()
        
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Stop surfpool
        print("\n6. Stopping surfpool...")
        proc.terminate()
        proc.wait(timeout=5)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("The error 'missing field `data`' occurs when:")
    print("- Sending certain types of transactions through surfpool")
    print("- The RPC response doesn't match what solana-py expects")
    print("- Possibly related to transfers to non-existent/system accounts")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(reproduce_error())