"""
Transaction Parser for Solana Voyager Agent

Parses Solana transaction receipts to extract detailed information
for transaction complexity analysis.
"""

import json
from typing import Dict, Any, List, Optional
from tracking.trajectory_tracker import TransactionDetails


def parse_transaction_receipt(tx_receipt_json: str) -> Optional[TransactionDetails]:
    """
    Parse a Solana transaction receipt and extract detailed information.
    
    Args:
        tx_receipt_json: JSON string of the transaction receipt
        
    Returns:
        TransactionDetails object with parsed information
    """
    if not tx_receipt_json:
        return None
        
    try:
        receipt = json.loads(tx_receipt_json)
    except json.JSONDecodeError:
        return None
    
    # Extract basic transaction info
    tx = receipt.get("transaction", {})
    meta = receipt.get("meta", {})
    
    # Get transaction message
    message = tx.get("message", {})
    account_keys = message.get("accountKeys", [])
    instructions = message.get("instructions", [])
    
    # Parse instructions
    parsed_instructions = []
    for idx, ix in enumerate(instructions):
        program_id_index = ix.get("programIdIndex", 0)
        program_id = account_keys[program_id_index] if program_id_index < len(account_keys) else "Unknown"
        
        parsed_ix = {
            "index": idx,
            "program_id": program_id,
            "accounts": [account_keys[i] for i in ix.get("accounts", []) if i < len(account_keys)],
            "data": ix.get("data", ""),
            "stackHeight": ix.get("stackHeight")
        }
        
        # Try to identify instruction type from known program IDs
        parsed_ix["type"] = _identify_instruction_type(program_id, ix.get("data", ""))
        parsed_instructions.append(parsed_ix)
    
    # Extract compute units from log messages
    compute_units = _extract_compute_units(meta.get("logMessages", []))
    
    # Create TransactionDetails object
    return TransactionDetails(
        signature=receipt.get("signature", "unknown"),
        slot=receipt.get("slot", 0),
        compute_units_consumed=compute_units,
        fee=meta.get("fee", 0),
        num_accounts=len(account_keys),
        num_instructions=len(instructions),
        instructions=parsed_instructions,
        account_keys=account_keys,
        success=meta.get("err") is None,
        log_messages=meta.get("logMessages", []),
        block_time=receipt.get("blockTime")
    )


def _extract_compute_units(log_messages: List[str]) -> int:
    """Extract compute units consumed from log messages."""
    for msg in log_messages:
        if "consumed" in msg and "compute units" in msg.lower():
            # Example: "Program consumed 12345 compute units"
            parts = msg.split()
            for i, part in enumerate(parts):
                if part == "consumed" and i + 1 < len(parts):
                    try:
                        return int(parts[i + 1])
                    except ValueError:
                        continue
    return 0


def _identify_instruction_type(program_id: str, data: str) -> str:
    """Identify instruction type based on program ID and data."""
    # Common Solana program IDs
    KNOWN_PROGRAMS = {
        "11111111111111111111111111111111": "System Program",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "Token Program",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "Associated Token Program",
        "ComputeBudget111111111111111111111111111111": "Compute Budget Program",
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter Aggregator V6",
        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca Whirlpools",
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium AMM V4",
        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": "Raydium CLMM",
        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "Meteora DLMM",
        "MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD": "Marinade"
    }
    
    if program_id in KNOWN_PROGRAMS:
        return KNOWN_PROGRAMS[program_id]
    
    # Try to guess based on common patterns
    if "111111" in program_id:
        return "System Program"
    elif "Token" in program_id:
        return "Token Program"
    elif "JUP" in program_id:
        return "Jupiter"
    elif "whirL" in program_id:
        return "Orca"
    elif "Raydium" in program_id or "675kPX" in program_id:
        return "Raydium"
    elif "CAM" in program_id:
        return "Raydium CLMM"
    elif "LBU" in program_id:
        return "Meteora"
    elif "Mar" in program_id:
        return "Marinade"
    
    return "Unknown Program"


def format_transaction_summary(tx_details: TransactionDetails) -> str:
    """Format transaction details into a human-readable summary."""
    if not tx_details:
        return "No transaction details available"
    
    summary = f"""
Transaction Summary:
-------------------
Signature: {tx_details.signature[:8]}...{tx_details.signature[-8:]}
Slot: {tx_details.slot:,}
Success: {"✓" if tx_details.success else "✗"}
Fee: {tx_details.fee / 1e9:.6f} SOL
Compute Units: {tx_details.compute_units_consumed:,}
Accounts: {tx_details.num_accounts}
Instructions: {tx_details.num_instructions}

Instruction Breakdown:
"""
    
    for i, ix in enumerate(tx_details.instructions):
        summary += f"\n  {i+1}. {ix['type']}"
        if ix['accounts']:
            summary += f" ({len(ix['accounts'])} accounts)"
    
    return summary


def get_transaction_complexity_score(tx_details: TransactionDetails) -> float:
    """
    Calculate a complexity score for the transaction.
    
    Score is based on:
    - Number of instructions
    - Number of unique accounts
    - Compute units consumed
    - Cross-program invocations
    """
    if not tx_details:
        return 0.0
    
    # Base score from instruction count
    score = tx_details.num_instructions * 10
    
    # Add points for account complexity
    score += tx_details.num_accounts * 5
    
    # Add points for compute units (normalized)
    score += min(tx_details.compute_units_consumed / 10000, 50)
    
    # Add points for cross-program invocations
    unique_programs = set()
    for ix in tx_details.instructions:
        if ix.get('stackHeight', 0) > 1:
            score += 20  # Cross-program invocation
        unique_programs.add(ix.get('type', 'Unknown'))
    
    score += len(unique_programs) * 15
    
    return round(score, 2)