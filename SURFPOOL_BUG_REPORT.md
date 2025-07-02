# Surfpool RPC Response Parsing Error

## Issue Description

When sending transactions that result in errors through surfpool, the Python solana-py client crashes with a panic instead of handling the error gracefully:

```
thread '<unnamed>' panicked at crates/rpc-responses/src/lib.rs:363:84:
called `Result::unwrap()` on an `Err` value: Error("missing field `data`", line: 0, column: 0)
```

This happens when surfpool returns an error response that solana-py's parser cannot handle.

## Environment

- surfpool: latest
- solana-py: 0.36.7
- Python: 3.12
- OS: macOS

## Quick Test - No Code Needed!

Just run these two curl commands to see the difference:

### 1. Test with Surfpool (missing 'data' field):
```bash
curl -s -X POST http://localhost:8899 -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"sendTransaction","params":["4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"]}' | jq .
```

Response:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32002,
    "message": "Transaction simulation failed: Blockhash not found: 0 log messages:\n"
  },
  "id": 1
}
```

### 2. Test with Devnet (includes 'data' field):
```bash
curl -s -X POST https://api.devnet.solana.com -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"sendTransaction","params":["4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"]}' | jq .
```

Response:
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32002,
    "message": "Transaction simulation failed: Blockhash not found",
    "data": {
      "accounts": null,
      "err": "BlockhashNotFound",
      "innerInstructions": null,
      "logs": [],
      "replacementBlockhash": null,
      "returnData": null,
      "unitsConsumed": 0
    }
  },
  "id": 1
}
```

**The Issue**: Surfpool is missing the `"data"` field that Solana includes in error responses.

## Why This Matters

When solana-py tries to parse surfpool's error response (without the 'data' field), it crashes with:
```
thread '<unnamed>' panicked at crates/rpc-responses/src/lib.rs:363:84:
called `Result::unwrap()` on an `Err` value: Error("missing field `data`", line: 0, column: 0)
```

Instead of getting a nice error message like "Blockhash not found", Python developers get a panic crash.

### Root Cause

The error happens in solana-py's Rust-based response parser:
```
File "solana/rpc/providers/core.py", line 96, in _parse_raw
    parsed = parser.from_json(raw)  # This is a Rust function via PyO3
```

The parser expects a "data" field that isn't present in error responses, causing a panic instead of a proper error.

## Hypothesis

This appears to be a bug in solana-py's response parser, not necessarily in surfpool. However, there might be a subtle difference in how surfpool formats error responses compared to standard Solana RPC nodes that triggers this bug.

## The Fix

Surfpool should include the `"data"` field in error responses to match Solana's RPC format. Even if some fields are null/empty, the structure should match.

## Questions

1. **For Surfpool Team**: Does surfpool format error responses differently than standard Solana RPC nodes?
2. **For solana-py Team**: Should the response parser handle error responses without panicking?
3. Could this be related to how surfpool handles specific error types?

## Workaround

For now, we catch the panic exception and treat it as a generic error, but this prevents us from getting the actual error message.

## Suggested Fix

Either:
1. solana-py should handle error responses gracefully without panicking
2. surfpool could format error responses to match what solana-py expects
3. Document the expected error response format

Thank you for looking into this! Both surfpool and solana-py are great tools and this seems like a simple compatibility issue.