# Implementation Plan: Single Transaction Enforcement

## Overview
Enforce the constraint that each skill can only execute ONE transaction, making this explicit throughout the system.

## Implementation Steps

### 1. Update Mock Environment (skill_runner/runSkill.ts)
- Add transaction counter to track attempts
- Throw error if skill tries to send multiple transactions
- Add clear error message explaining the constraint

### 2. Update Planner Prompts (planner/planner.py)
- Add explicit single-transaction constraint to system prompt
- Provide examples of how to handle multi-step operations
- Emphasize skill chaining for complex workflows

### 3. Create Validation Tests
- Test that single transaction succeeds
- Test that multiple transaction attempts fail with clear error
- Test error message clarity
- Test that transaction counter resets properly

### 4. Update Documentation
- ✅ CLAUDE.md updated with constraint
- Add examples to skill templates
- Update any existing skill examples

### 5. Add Runtime Validation
- TypeScript: Track transaction count in mock environment
- Python: Validate skill output format
- Add logging for debugging

## Test Cases

### Test 1: Single Transaction Success
```typescript
// Should succeed
export async function executeSkill(env: any) {
    const tx = await env.simulateTransaction();
    return [1.0, "success", JSON.stringify(tx)];
}
```

### Test 2: Multiple Transaction Failure
```typescript
// Should fail with clear error
export async function executeSkill(env: any) {
    const tx1 = await env.simulateTransaction();
    const tx2 = await env.simulateTransaction(); // This should throw
    return [1.0, "success", JSON.stringify(tx2)];
}
```

### Test 3: Null Transaction Allowed
```typescript
// Should succeed (no transaction is valid)
export async function executeSkill(env: any) {
    // Just observe, don't transact
    return [0.0, "observed", null];
}
```

## Implementation Details

### Mock Environment Changes
```typescript
// Add to surfpoolEnv mock
let transactionCount = 0;

simulateTransaction: async () => {
    transactionCount++;
    if (transactionCount > 1) {
        throw new Error(
            "SINGLE_TRANSACTION_LIMIT: Skills can only execute ONE transaction. " +
            "To perform multiple operations, create separate skills and chain them. " +
            "This transaction attempt was blocked."
        );
    }
    // ... existing logic
}

// Reset counter for each skill execution
```

### Planner Prompt Addition
```python
SINGLE_TRANSACTION_CONSTRAINT = """
CRITICAL CONSTRAINT: Each skill MUST execute exactly ONE transaction.
- If you need multiple transactions, create SEPARATE skills
- Chain skills together by calling them in sequence
- The skill return type supports only ONE transaction receipt

Examples:
- WRONG: Swap tokens then stake in one skill (2 transactions)
- RIGHT: Create a "swapTokens" skill and a separate "stakeTokens" skill

If a skill attempts multiple transactions, it will fail with an error.
"""
```

## Success Criteria
1. Mock environment prevents multiple transactions with clear error
2. All tests pass
3. Planner generates single-transaction skills
4. Error messages guide users to proper solution (skill chaining)
5. No regression in existing functionality

## Rollout Plan
1. Implement mock environment changes
2. Write and run tests  
3. Update planner prompts
4. Test end-to-end with skill generation
5. Update any existing multi-transaction examples