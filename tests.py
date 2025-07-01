import asyncio
import unittest
import os
import shutil
import logging
import io
import sys
import textwrap

from voyager_env import SolanaVoyagerEnv

import io, sys, contextlib, unittest

class _CleanStdout:
    def write(self, data):
        for line in data.splitlines(keepends=True):
            sys.__stdout__.write(textwrap.dedent(line).lstrip())
    def flush(self): sys.__stdout__.flush()

sys.stdout = sys.stderr = _CleanStdout()
# --- Test Configuration ---
# Capture logs to a stream to keep stdout clean
log_stream = io.StringIO()
logging.basicConfig(level=logging.INFO, format='%(message)s', stream=log_stream)

# To see logs, comment out the line above and uncomment the line below
# logging.basicConfig(level=logging.INFO, format='%(message)s')

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
        with open(os.path.join(self.skill_root, "skill_0_transfer.py"), "w") as f:
            f.write("""
import asyncio, logging, json
from solders.keypair import Keypair
from solders.system_program import transfer, TransferParams
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
async def execute_skill(env):
    try:
        agent_keypair = env.agent_keypair
        recipient = Keypair().pubkey()
        instruction = transfer(TransferParams(from_pubkey=agent_keypair.pubkey(), to_pubkey=recipient, lamports=1000))
        latest_blockhash_resp = await env.client.get_latest_blockhash()
        message = MessageV0.try_compile(payer=agent_keypair.pubkey(), instructions=[instruction], address_lookup_table_accounts=[], recent_blockhash=latest_blockhash_resp.value.blockhash)
        tx = VersionedTransaction(message, [agent_keypair])
        obs, receipt_str, terminated, info = await env.step(tx)
        receipt = json.loads(receipt_str) if receipt_str else None
        if receipt and receipt.get('meta', {}).get('err') is None:
            return 1.0, "success"
        else:
            return 0.0, f"tx_failure: {info.get('error', 'Unknown')}"
    except Exception as e:
        return 0.0, f"exception: {e}"
""")

        # Skill 1: Failing Skill
        with open(os.path.join(self.skill_root, "skill_1_fail.py"), "w") as f:
            f.write("""
import asyncio, logging
async def execute_skill(env):
    logging.info("Executing skill designed to fail.")
    raise ValueError("This skill was intended to fail for testing.")
""")

        # Skill 2: Jupiter Swap Simulation
        with open(os.path.join(self.skill_root, "skill_2_jupiter.py"), "w") as f:
            f.write("""
import asyncio, logging, json
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
JUPITER_V6_PROGRAM_ID = Pubkey.from_string("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4")
async def execute_skill(env):
    try:
        agent_keypair = env.agent_keypair
        instruction = transfer(TransferParams(from_pubkey=agent_keypair.pubkey(), to_pubkey=JUPITER_V6_PROGRAM_ID, lamports=100))
        latest_blockhash_resp = await env.client.get_latest_blockhash()
        message = MessageV0.try_compile(payer=agent_keypair.pubkey(), instructions=[instruction], address_lookup_table_accounts=[], recent_blockhash=latest_blockhash_resp.value.blockhash)
        tx = VersionedTransaction(message, [agent_keypair])
        obs, receipt_str, terminated, info = await env.step(tx)
        return 0.0, "simulated_swap_logged"
    except Exception as e:
        return 0.0, f"exception: {e}"
""")

    async def test_env_creation_and_reset(self):
        self.assertIsNotNone(self.obs)
        self.assertIn("wallet_balances", self.obs)

    async def test_run_successful_skill(self):
        action = 2 # Corresponds to skill_0_transfer.py
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertAlmostEqual(reward, 1.0, msg=f"Reward should be 1.0, but was {reward}. Info: {info}")
        self.assertEqual(info.get("done_reason"), "success")

    async def test_run_failing_skill(self):
        action = 3 # Corresponds to skill_1_fail.py
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertEqual(reward, 0.0, msg=f"Reward should be 0.0 for a failed skill, but was {reward}. Info: {info}")
        self.assertIn("intended to fail", info.get("error", ""))

    async def test_jupiter_swap_reward_bonus(self):
        # The first call to a new protocol gets a bonus
        action = 4 # Corresponds to skill_2_jupiter.py
        obs, reward, term, trunc, info = await self.env.step(action)
        # The skill itself returns 0, but the env adds a 1.0 bonus
        self.assertAlmostEqual(reward, 1.0, msg=f"Reward should be ~1.0 for the first Jupiter tx, but was {reward}. Info: {info}")
        self.assertEqual(info.get("protocol"), "Jupiter")
        
        # The second call to the same protocol should not get a bonus
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertAlmostEqual(reward, 0.0, msg=f"Reward should be 0.0 on the second Jupiter tx, but was {reward}. Info: {info}")

    async def test_grow_skill_dummy(self):
        action = 0 # NEW_SKILL
        obs, reward, term, trunc, info = await self.env.step(action)
        self.assertGreater(reward, 0)
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


if __name__ == "__main__":
    from clean_logging import setup_clean_logging
    setup_clean_logging()
    unittest.main()
