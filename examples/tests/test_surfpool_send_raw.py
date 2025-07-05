#!/usr/bin/env python3

import base64
import httpx
import asyncio
import json
from solders.keypair import Keypair
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solders.message import Message
from solders.hash import Hash
from solders.pubkey import Pubkey

async def test_raw_send_transaction():
    """Test raw sendTransaction to see the actual response format"""
    
    # Create a transaction
    sender = Keypair()
    transfer_ix = transfer(TransferParams(
        from_pubkey=sender.pubkey(),
        to_pubkey=Pubkey.from_string("11111111111111111111111111111111"),
        lamports=1
    ))
    
    dummy_blockhash = Hash.from_string("4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi")
    msg = Message.new_with_blockhash([transfer_ix], sender.pubkey(), dummy_blockhash)
    tx = Transaction.new_unsigned(msg)
    tx.sign([sender], dummy_blockhash)
    
    # Serialize transaction
    tx_bytes = bytes(tx)
    tx_base64 = base64.b64encode(tx_bytes).decode('ascii')
    
    print(f"Transaction base64: {tx_base64[:50]}...")
    
    # Send raw RPC request
    async with httpx.AsyncClient() as client:
        print("\nSending raw RPC request to Surfpool...")
        response = await client.post(
            "http://localhost:8899",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [tx_base64]
            }
        )
        
        print(f"\nHTTP Status: {response.status_code}")
        print(f"Raw response text:\n{response.text}")
        
        try:
            response_json = response.json()
            print(f"\nParsed JSON response:")
            print(json.dumps(response_json, indent=2))
            
            # Check if 'data' field exists in error response
            if "error" in response_json and isinstance(response_json["error"], dict):
                error_obj = response_json["error"]
                print(f"\nError object fields: {list(error_obj.keys())}")
                if "data" in error_obj:
                    print(f"'data' field exists: {error_obj['data']}")
                else:
                    print("⚠️  'data' field is MISSING from error object!")
                    
        except Exception as e:
            print(f"\nFailed to parse JSON: {e}")

if __name__ == "__main__":
    asyncio.run(test_raw_send_transaction())