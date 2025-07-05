#!/usr/bin/env python3

import base64
import base58
import httpx
import asyncio
import json
from solders.keypair import Keypair
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solders.message import Message
from solders.hash import Hash
from solders.pubkey import Pubkey

async def test_send_with_encoding():
    """Test sendTransaction with different encoding options"""
    
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
    tx_base58 = base58.b58encode(tx_bytes).decode('ascii')
    
    async with httpx.AsyncClient() as client:
        # Test 1: Base64 encoding (should be default)
        print("1. Testing with base64 encoding (default)...")
        response = await client.post(
            "http://localhost:8899",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [tx_base64]
            }
        )
        response_json = response.json()
        print(f"Response: {json.dumps(response_json, indent=2)}")
        if "error" in response_json:
            print(f"Error fields: {list(response_json['error'].keys())}")
        
        # Test 2: Base64 encoding with explicit encoding parameter
        print("\n2. Testing with explicit base64 encoding...")
        response = await client.post(
            "http://localhost:8899",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "sendTransaction",
                "params": [tx_base64, {"encoding": "base64"}]
            }
        )
        response_json = response.json()
        print(f"Response: {json.dumps(response_json, indent=2)}")
        if "error" in response_json:
            print(f"Error fields: {list(response_json['error'].keys())}")
            
        # Test 3: Base58 encoding (Surfpool seems to expect this?)
        print("\n3. Testing with base58 encoding...")
        response = await client.post(
            "http://localhost:8899",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "sendTransaction",
                "params": [tx_base58, {"encoding": "base58"}]
            }
        )
        response_json = response.json()
        print(f"Response: {json.dumps(response_json, indent=2)}")
        if "error" in response_json:
            print(f"Error fields: {list(response_json['error'].keys())}")
            if "data" not in response_json["error"]:
                print("⚠️  'data' field is MISSING!")

if __name__ == "__main__":
    asyncio.run(test_send_with_encoding())