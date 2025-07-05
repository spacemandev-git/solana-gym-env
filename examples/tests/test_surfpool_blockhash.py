#!/usr/bin/env python3

import asyncio
from solana.rpc.async_api import AsyncClient
import json

async def test_surfpool_blockhash():
    """Test if we can fetch blockhash from Surfpool without errors"""
    client = AsyncClient("http://localhost:8899")
    
    try:
        print("Testing Surfpool RPC methods...\n")
        
        # Test 1: Get latest blockhash
        print("1. Getting latest blockhash...")
        blockhash_resp = await client.get_latest_blockhash()
        print(f"✓ Success! Blockhash: {blockhash_resp.value.blockhash}")
        print(f"  Last valid block height: {blockhash_resp.value.last_valid_block_height}")
        
        # Test 2: Get block height
        print("\n2. Getting block height...")
        height = await client.get_block_height()
        print(f"✓ Success! Block height: {height.value}")
        
        # Test 3: Get version
        print("\n3. Getting version...")
        version = await client.get_version()
        print(f"✓ Success! Version: {version.value}")
        
        # Test 4: Get balance (of a random address)
        print("\n4. Getting balance...")
        from solders.pubkey import Pubkey
        pubkey = Pubkey.from_string("11111111111111111111111111111111")
        balance = await client.get_balance(pubkey)
        print(f"✓ Success! Balance: {balance.value} lamports")
        
        # Test 5: Raw RPC call to see response format
        print("\n5. Raw RPC call to getLatestBlockhash...")
        import httpx
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                "http://localhost:8899",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getLatestBlockhash",
                    "params": []
                }
            )
            print(f"✓ Raw response:")
            print(json.dumps(response.json(), indent=2))
        
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_surfpool_blockhash())