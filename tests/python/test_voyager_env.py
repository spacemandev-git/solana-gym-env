import asyncio
import unittest
import os
import shutil
import logging
import io
import sys
import textwrap

from voyager_env import SolanaVoyagerEnv

import io, sys, contextlib, unittest, json


# --- Test Configuration ---
# Capture logs to a stream to keep stdout clean
log_stream = io.StringIO()
logging.basicConfig(level=logging.INFO, format='%(message)s', stream=log_stream)

class TestSolanaVoyagerEnv(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.skill_root = "./test_skills"
        if os.path.exists(self.skill_root):
            shutil.rmtree(self.skill_root)
        os.makedirs(self.skill_root)
        self.create_dummy_skill_files()
        self.env = SolanaVoyagerEnv(skill_root=self.skill_root)
        self.obs, self.info = await self.env.reset()

    async def asyncTearDown(self):
        await self.env.close()
        if os.path.exists(self.skill_root):
            shutil.rmtree(self.skill_root)

    def create_dummy_skill_files(self):
        # Skill 0: Successful SOL Transfer
        with open(os.path.join(self.skill_root, "skill_0_transfer.ts"), "w") as f:
            f.write("""
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    // Simulate a successful transaction with a dummy program ID
    const txReceipt = env.simulateTransaction(true, "TransferProgram1111111111111111111111111111111");
    return [1.0, "SOL transfer simulated successfully.", txReceipt];
}
""")

        # Skill 1: Failing Skill
        with open(os.path.join(self.skill_root, "skill_1_fail.ts"), "w") as f:
            f.write("""
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    // Simulate a failed transaction
    const txReceipt = env.simulateTransaction(false, "FailedProgram1111111111111111111111111111111");
    return [0.0, "This skill was intended to fail for testing.", txReceipt];
}
""")

        # Skill 2: Jupiter Swap Simulation
        with open(os.path.join(self.skill_root, "skill_2_jupiter.ts"), "w") as f:
            f.write("""
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    // Simulate a successful Jupiter transaction
    const txReceipt = env.simulateTransaction(true, "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
    return [0.0, "simulated_swap_logged", txReceipt]; // Skill itself returns 0, bonus added by env
}
""")
        # Skill 3: Multi-protocol transaction simulation
        with open(os.path.join(self.skill_root, "skill_3_multi_protocol.ts"), "w") as f:
            f.write("""
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    // Simulate a successful transaction involving multiple protocols already in program_ids.csv
    const txReceipt = {
        transaction: {
            message: {
                accountKeys: [
                    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4", // Jupiter
                    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo", // Meteora DLMM
                ],
                instructions: [
                    { programIdIndex: 0 }, // Jupiter
                    { programIdIndex: 1 }, // Meteora
                ],
            },
        },
        meta: {
            err: null, // Successful transaction
            innerInstructions: [], // No inner instructions for simplicity in this test
            logMessages: ["Simulated multi-protocol transaction"],
        },
    };
    return [0.0, "Multi-protocol transaction simulated.", JSON.stringify(txReceipt)];
}
""")

    async def test_env_creation_and_reset(self):
        self.assertIsNotNone(self.obs)
        self.assertIn("wallet_balances", self.obs)

    async def test_run_successful_skill(self):
        action = 2 # Corresponds to skill_0_transfer.ts
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertAlmostEqual(reward, 1.0, msg=f"Reward should be 1.0, but was {reward}. Info: {info}")
        self.assertEqual(info.get("done_reason"), "SOL transfer simulated successfully.")

    async def test_run_failing_skill(self):
        action = 3 # Corresponds to skill_1_fail.ts
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertEqual(reward, 0.0, msg=f"Reward should be 0.0 for a failed skill, but was {reward}. Info: {info}")
        self.assertIn("intended to fail", info.get("done_reason", "")) # Check done_reason for failure message

    async def test_jupiter_swap_reward_bonus(self):
        # The skill itself returns 0, but the env adds a 1.0 bonus for new protocol
        action = 4 # Corresponds to skill_2_jupiter.ts
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertAlmostEqual(reward, 1.0, msg=f"Reward should be ~1.0 for the first Jupiter tx, but was {reward}. Info: {info}")
        self.assertIn("Jupiter", info.get("protocols_interacted", []))
        
        # The second call to the same protocol should not get a bonus
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertAlmostEqual(reward, 0.0, msg=f"Reward should be 0.0 on the second Jupiter tx, but was {reward}. Info: {info}")
        self.assertIn("Jupiter", info.get("protocols_interacted", []))

    async def test_multi_protocol_reward_bonus(self):
        # No need to modify KNOWN_PROGRAM_IDS here, it's loaded from CSV
        
        action = 5 # Corresponds to skill_3_multi_protocol.ts
        obs, reward, term, trunc, info = await self.env.step(action)
        # Expected: 0.0 (skill) + 1.0 (Jupiter) + 1.0 (Meteora) = 2.0
        self.assertAlmostEqual(reward, 2.0, msg=f"Reward should be ~2.0 for multi-protocol tx, but was {reward}. Info: {info}")
        self.assertIn("Jupiter", info.get("protocols_interacted", []))
        self.assertIn("Meteora", info.get("protocols_interacted", []))
        
        # Ensure protocols are tracked
        self.assertIn("Jupiter", self.env.protocols_seen)
        self.assertIn("Meteora", self.env.protocols_seen)

        # Second call should yield 0.0 bonus as all are seen
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertAlmostEqual(reward, 0.0, msg=f"Reward should be 0.0 on second multi-protocol tx, but was {reward}. Info: {info}")

    async def test_grow_skill_dummy(self):
        action = 0 # NEW_SKILL
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertEqual(reward, 1.0) # Expect 1.0 reward for successful skill creation
        self.assertEqual(info.get("status"), "success")
        self.assertIn("new_skill_id", info)

if __name__ == "__main__":
    # This allows running the tests with `python tests.py`
    suite = unittest.TestSuite()
    loader = unittest.TestLoader()
    # Ensure tests run in alphabetical order
    test_names = sorted(loader.getTestCaseNames(TestSolanaVoyagerEnv))
    for name in test_names:
        suite.addTest(TestSolanaVoyagerEnv(name))
    
    result = unittest.TextTestRunner(stream=sys.stdout).run(suite)
    if result.failures or result.errors:
        print("\n--- LOGS ---")
        log_stream.seek(0)
        print(log_stream.read())
    
    unittest.main()
