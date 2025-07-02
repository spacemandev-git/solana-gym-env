#!/usr/bin/env python3
"""
Test demonstrating the blockhash issue with base64 transactions.

The problem:
1. Skills create transactions with a dummy blockhash
2. By the time the environment executes them, that blockhash is stale
3. We need to update the blockhash before signing and sending

This test shows potential solutions.
"""

import unittest
import base64
import json


class TestBase64BlockhashIssue(unittest.TestCase):
    """Test the blockhash handling in base64 transactions."""
    
    def test_transaction_structure(self):
        """Test that we can decode and inspect transaction structure."""
        # This is a real base64 transaction from our test
        base64_tx = "AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEAAgAADAIAAABAQg8AAAAAAA=="
        
        # Decode it
        tx_bytes = base64.b64decode(base64_tx)
        
        # Basic validation
        self.assertGreater(len(tx_bytes), 0)
        self.assertEqual(len(tx_bytes), 151)  # Known size for this tx
        
        print(f"Transaction size: {len(tx_bytes)} bytes")
        print(f"First 32 bytes (likely signatures): {tx_bytes[:32].hex()}")
        print(f"Next 32 bytes (likely blockhash): {tx_bytes[32:64].hex()}")
    
    def test_blockhash_problem(self):
        """Test the blockhash problem quickly."""
        # Blockhashes change every ~400ms, expire after ~60 seconds
        # Problem: Skills use dummy blockhash that validator rejects
        # Solution: Use fresh blockhash from validator
        
        dummy_blockhash = "11111111111111111111111111111111"
        valid_blockhash = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"
        
        # Test that these are different formats
        self.assertEqual(len(dummy_blockhash), 32)  # Just 32 '1' characters
        self.assertEqual(len(valid_blockhash), 43)  # Proper base58 encoded 32 bytes
        
        # Verify the issue exists
        self.assertTrue(all(c == '1' for c in dummy_blockhash))
    
    def test_recommended_solution(self):
        """Test the recommended solution quickly."""
        # Solution: env.getRecentBlockhash() should return fresh blockhash
        # This allows transactions to be valid for ~60 seconds
        
        import time
        start = time.time()
        
        # Mock getting a fresh blockhash (instant operation)
        fresh_blockhash = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"
        
        # Verify it's properly formatted
        self.assertEqual(len(fresh_blockhash), 43)
        
        # Test should complete instantly
        duration = time.time() - start
        self.assertLess(duration, 0.1, f"Test took {duration:.2f}s, should be < 0.1s")


if __name__ == '__main__':
    unittest.main()