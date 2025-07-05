# Plan to Fix Solana Voyager Env Issues

## 1. Problem Summary

The `SolanaVoyagerEnv` is experiencing persistent issues with incorrect reward calculation and protocol tracking. This stems from a breakdown in the cross-language communication (Python to TypeScript) and subsequent data propagation within the environment.

**Failing Tests and Symptoms:**

- **`test_grow_skill_dummy`**: Fails with `AssertionError: 0.0 != 1.0`. Expected reward for a successfully grown skill is 1.0, but the test receives 0.0.
- **`test_jupiter_swap_reward_bonus`**: Fails with `AssertionError: 'Jupiter' not found in []`. The `protocols_interacted` list in the info dictionary is empty, indicating that the protocol labeler is not correctly identifying protocols from transaction receipts.
- **`test_multi_protocol_reward_bonus`**: Fails with `AssertionError: 1.0 != 2.0` and `Info: {'done_reason': None}`. The reward is incorrect (only 1.0 instead of 2.0 for two new protocols), and the `done_reason` is missing. This confirms issues with both multi-hit protocol labeling and data propagation.
- **`test_run_failing_skill`**: Fails with `AssertionError: 1.0 != 0.0` and `Info: {'done_reason': None}`. A failing skill is incorrectly yielding a reward of 1.0 instead of 0.0, and the `done_reason` is missing.
- **`test_run_successful_skill`**: Fails with `AssertionError: None != 'SOL transfer simulated successfully.'`. The `done_reason` is `None`, indicating that the success message from the skill is not being propagated.

## 2. Root Cause Analysis

The core of the problem lies in the inconsistent and incomplete data flow of skill execution results (reward, done reason, transaction receipt) from the TypeScript `runSkill.ts` script back to the Python `SolanaVoyagerEnv`.

- **`runSkill.ts` output format:** While `runSkill.ts` was modified to return a JSON object with `reward`, `done_reason`, and `tx_receipt_json_string`, there might be subtle issues in its exact output format or how it handles errors, leading to `None` values or incorrect data being received by Python.
- **`skill_manager/ts_skill_manager.py` parsing:** The `execute_skill` method in `TypeScriptSkillManager` is responsible for parsing the JSON output from `runSkill.ts`. If this parsing is not robust, or if it expects certain keys that are not always present, it could lead to missing data.
- **`voyager/solana_voyager_env.py` logic:**
  - **`_grow_skill`**: The condition for a successful skill creation (`if reward > 0:`) might be too simplistic or the `reward` value itself is not correctly reflecting the skill's success.
  - **`_run_skill`**: This method is not correctly extracting and utilizing all fields from the `skill_result` dictionary returned by `ts_skill_manager.execute_skill`. Specifically, `base_reward` is not always `0.0` for failing skills, and `info["done_reason"]` and `info["error"]` are often `None` or incorrect. The `tx_receipt_json_string` might also be `None` or malformed, preventing `_protocol_labeler` from functioning.
  - **`_protocol_labeler`**: While updated to scan all instructions, if the input `tx_receipt` is invalid or `None`, it will fail to identify protocols.
- **Test Setup (`tests/python/test_voyager_env.py`):**
  - The dummy TypeScript skills created in `create_dummy_skill_files` might not be consistently returning the expected `[reward, done_reason, tx_receipt_json_string]` tuple, especially for `tx_receipt_json_string` and its `meta.err` field.
  - The `test_multi_protocol_reward_bonus` test was attempting to modify `KNOWN_PROGRAM_IDS` directly, which is incorrect as it's a global constant loaded from CSV. This has been addressed in the previous step by removing the modification and adjusting the dummy skill to use existing program IDs.

## 3. Detailed Plan

The plan will focus on verifying the data flow at each step and ensuring robust error handling and data extraction.

### Phase 1: Verify `runSkill.ts` Output

1.  **Action 1.1: Inspect `runSkill.ts` raw output.**
    - The temporary `console.log` has been added to `skill_runner/runSkill.ts`.
    - Execute a single test (e.g., `uv run python -m unittest tests.python.test_voyager_env.TestSolanaVoyagerEnv.test_run_successful_skill`) and capture the full terminal output.
    - Analyze the `RAW_OUTPUT_START:...:RAW_OUTPUT_END` string to confirm the exact JSON structure and content (especially `success`, `reward`, `done_reason`, `tx_receipt_json_string`). This will be the definitive source of truth for what `runSkill.ts` is actually sending.

### Phase 2: Refine Python-side Data Handling

1.  **Action 2.1: Refine `skill_manager/ts_skill_manager.py`'s `execute_skill` parsing.**

    - Based on the confirmed `runSkill.ts` output from Phase 1, ensure that `execute_skill` correctly and safely extracts all expected fields from the parsed JSON. Use `.get(key, default_value)` to prevent `KeyError` if a field is missing.

2.  **Action 2.2: Update `voyager/solana_voyager_env.py`'s `_run_skill` and `_grow_skill` logic.**
    - **`_run_skill`**:
      - Ensure `base_reward = skill_result.get("reward", 0.0)` is correctly assigning the reward.
      - Ensure `info["done_reason"] = skill_result.get("done_reason", "unknown")` is correctly assigning the done reason.
      - Refine the error setting: `info["error"]` should be set if `skill_result.get("success")` is `False` OR if `base_reward` is `0.0` AND `info["done_reason"]` indicates a failure (e.g., contains "fail" or "error").
      - Verify that `tx_receipt_json_string` is correctly passed to `json.loads` and then to `_protocol_labeler`.
    - **`_grow_skill`**:
      - Re-verify the condition `if reward > 0:` for registering a new skill. This should be sufficient if `pass.ts` correctly returns `1.0`.
      - Ensure `info["status"]` is correctly set to "success" or "failed".

### Phase 3: Test Environment and Cleanup

1.  **Action 3.1: Review and adjust dummy skills in `tests/python/test_voyager_env.py`.**

    - Confirm that `pass.ts` returns `[1.0, "SOL transfer simulated successfully.", valid_success_tx_receipt_json]`.
    - Confirm that `fail.ts` returns `[0.0, "This skill was intended to fail for testing.", valid_failed_tx_receipt_json]`.
    - Confirm that `jupiter.ts` returns `[0.0, "simulated_swap_logged", valid_jupiter_tx_receipt_json]`.
    - Confirm that `multi_protocol.ts` returns `[0.0, "Multi-protocol transaction simulated.", valid_multi_protocol_tx_receipt_json]` with existing program IDs.
    - Ensure the `valid_..._tx_receipt_json` strings include the `meta.err` field correctly for success (`null`) and failure (non-`null`).

2.  **Action 3.2: Remove temporary debug `console.log` from `runSkill.ts`.**

3.  **Action 3.3: Re-run all Python tests.**

## 4. Visual Explanation of Corrected Data Flow

```mermaid
graph TD
    A[SolanaVoyagerEnv (Python)] -->|Calls skill| B(SkillManager (Python))
    B -->|Executes skill file via subprocess| C(runSkill.ts (TypeScript))
    C -->|Imports and runs| D[TypeScript Skill (e.g., pass.ts)]
    D -->|Returns [reward, done_reason, tx_receipt_json]| C
    C -->|Outputs JSON: {success, reward, done_reason, tx_receipt_json} to stdout| B
    B -->|Parses JSON, returns Dict to| A
    A -->|Extracts reward, done_reason, tx_receipt_json from Dict| E[_run_skill / _grow_skill (Python)]
    E -->|Uses reward & done_reason for direct logic| F[Reward & Status Logic]
    E -->|Passes tx_receipt_json to| G{_protocol_labeler (Python)}
    G -->|Checks tx_receipt.meta.err for SUCCESS & extracts ALL program IDs| H{Is Transaction Successful? + Extract Protocols}
    H -- Yes --> I[Add each NEW protocol to protocols_seen & apply +1 bonus]
    H -- No --> J[No bonus, no protocol added]
    F & I --> K[Final Reward & Info]
```

This plan aims to systematically debug and correct the data flow and logic, ensuring that all information from the TypeScript skill execution is correctly processed by the Python environment.
