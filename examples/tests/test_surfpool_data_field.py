#!/usr/bin/env python3

import base64
import base58
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solders.message import Message
from solders.hash import Hash
from solders.pubkey import Pubkey

# Connect to surfpool
client = Client("http://localhost:8899")

# Create a transaction (this one has an invalid blockhash)
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

# Print transaction details
tx_bytes = bytes(tx)
tx_base64 = base64.b64encode(tx_bytes).decode('ascii')
tx_base58 = base58.b58encode(tx_bytes).decode('ascii')

print(f"Sender pubkey: {sender.pubkey()}")
print(f"Transaction size: {len(tx_bytes)} bytes")
print(f"\nSerialized transaction (base64):\n{tx_base64}")
print(f"\nSerialized transaction (base58):\n{tx_base58}")

# Attempt to send transaction
try:
    print("\nSending transaction via solana-py...")
    result = client.send_transaction(tx)
    print(f"Success: {result}")
except Exception as e:
    print(f"Error type: {type(e).__name__}")
    print(f"Error message: {e}")
    
    # Check if it's the "missing field `data`" error
    if "missing field `data`" in str(e):
        print("\n⚠️  This is the known Surfpool 'missing field data' issue!")
        print("The transaction was likely processed but the response parsing failed.")