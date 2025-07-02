import gymnasium as gym
import asyncio
import os
import logging
import traceback
import json
import shutil
from typing import Set, Dict, Any

from surfpool_env import SurfpoolEnv
from skill_manager.ts_skill_manager import TypeScriptSkillManager
from planner import LLMPlanner

# --- Constants ---
CONFIG_MAX_LLM_SKILL_TRIES = 3

import csv

KNOWN_PROGRAM_IDS: Dict[str, str] = {}

def load_program_ids_from_csv(file_path: str):
    global KNOWN_PROGRAM_IDS
    KNOWN_PROGRAM_IDS = {}
    if not os.path.exists(file_path) or os.stat(file_path).st_size == 0:
        raise FileNotFoundError(f"Program IDs CSV file not found or is empty: {file_path}")
    with open(file_path, mode='r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if 'program_address' in row and 'project_name' in row:
                KNOWN_PROGRAM_IDS[row['program_address']] = row['project_name']

# Load program IDs at startup
try:
    load_program_ids_from_csv('data/program_ids.csv')
except FileNotFoundError as e:
    logging.error(f"Failed to load program IDs: {e}")
    # Depending on criticality, you might want to exit or use a fallback
    # For now, we'll let it proceed with an empty dict if the file is missing/empty
except Exception as e:
    logging.error(f"An unexpected error occurred while loading program IDs: {e}")


class SolanaVoyagerEnv(gym.Env):
    """
    High-level Gymnasium wrapper for a Solana agent, inspired by the Voyager paper.
    The agent can choose to either execute a known skill, propose a new skill
    via an LLM, or inspect its library of skills.
    """
    metadata = {"render_modes": ["human"]}
    
    SPECIALS = {"NEW_SKILL": 0, "INSPECT_LIB": 1}

    def __init__(self, max_steps: int = 128, skill_root: str = "./skills"):
        # Layer 0: The low-level Solana environment
        self.solana_env = SurfpoolEnv()
        self.observation_space = self.solana_env.observation_space

        # Layer 1: Voyager components
        self.skills = TypeScriptSkillManager(skill_root=skill_root)
        self.planner = LLMPlanner(self.skills)

        # RL view of the world
        self.action_space = gym.spaces.Discrete(len(self.skills) + len(self.SPECIALS))
        
        self.max_steps = max_steps
        self.t = 0
        
        # Tracking for the voyager-style reward
        self.protocols_seen: Set[str] = set()

    def _update_action_space(self):
        """Updates the action space to reflect the current number of skills."""
        num_actions = len(self.skills) + len(self.SPECIALS)
        self.action_space = gym.spaces.Discrete(num_actions)

    def _protocol_labeler(self, tx_receipt: Dict[str, Any]) -> list[str]:
        """
        Identifies ALL protocols from a transaction receipt by checking for known
        program IDs in the transaction's instructions. This check is performed
        regardless of whether the transaction succeeded or failed.
        Returns a list of protocol names found in the transaction.
        """
        if not tx_receipt:
            return []

        protocols_found = []
        seen_protocols = set()  # To avoid duplicates

        try:
            # The transaction object contains account keys as strings
            account_keys = tx_receipt.get("transaction", {}).get("message", {}).get("accountKeys", [])
            if not account_keys:
                return []

            # The instructions contain indices into the account_keys list
            instructions = tx_receipt.get("transaction", {}).get("message", {}).get("instructions", [])

            for instruction in instructions:
                program_id_index = instruction.get("programIdIndex")
                if program_id_index is not None and program_id_index < len(account_keys):
                    program_id_str = account_keys[program_id_index]
                    if program_id_str in KNOWN_PROGRAM_IDS:
                        protocol = KNOWN_PROGRAM_IDS[program_id_str]
                        if protocol not in seen_protocols:
                            seen_protocols.add(protocol)
                            protocols_found.append(protocol)
            
            # Also check all account keys in case some are program IDs not in instructions
            for key in account_keys:
                if key in KNOWN_PROGRAM_IDS:
                    protocol = KNOWN_PROGRAM_IDS[key]
                    if protocol not in seen_protocols:
                        seen_protocols.add(protocol)
                        protocols_found.append(protocol)
        except Exception as e:
            logging.error(f"Error during protocol labeling: {e}")

        return protocols_found

    async def _grow_skill(self):
        """
        Generates, tests, and registers a new skill with a retry mechanism.
        """
        if self.solana_env.last_observation is None:
            return 0.0, {"error": "Cannot grow skill without an observation"}

        last_error = None
        for i in range(CONFIG_MAX_LLM_SKILL_TRIES):
            logging.info(f"Attempt {i+1}/{CONFIG_MAX_LLM_SKILL_TRIES} to generate a skill...")
            
            skill_code = self.planner.propose(
                self.solana_env.last_observation,
                error=last_error
            )
            
            try:
                file_path = self.skills.save_skill("new_skill", skill_code)
                logging.info("Testing the newly generated skill...")
                agent_pubkey = str(self.solana_env.agent_keypair.pubkey())
                result = self.skills.execute_skill(file_path, agent_pubkey=agent_pubkey)
                logging.info(f"Skill test result: {result}")

                if result.get("success"):
                    skill_id = self.skills.register(skill_code)
                    self._update_action_space()
                    info = {"new_skill_id": skill_id, "status": "success"}
                    return 1.0, info # Reward for successfully growing a skill
                else:
                    last_error = f"Skill executed but failed. Reason: {result.get('reason')}"

            except Exception as e:
                logging.error(f"Runtime error in generated skill: {e}")
                last_error = f"Runtime error: {traceback.format_exc()}"
        
        # If all tries fail
        info = {"status": "failed", "last_error": last_error}
        return 0.0, info

    def _summarise_library(self):
        """Returns a summary of the skill library."""
        # The "summary" could be a feature vector for the agent.
        # For now, we'll just return the number of skills.
        info = {"num_skills": len(self.skills)}
        # No reward for just looking.
        return 0.0, info

    async def _run_skill(self, skill_id: int):
        """
        Executes a skill, computes the reward, and handles exceptions.
        The protocol labeling happens regardless of skill success or failure.
        """
        if skill_id not in self.skills.skills:
            return 0.0, {"error": f"Skill {skill_id} not found."}

        file_path = self.skills.skills[skill_id]
        base_reward = 0.0
        info = {}

        try:
            # Pass agent pubkey and latest blockhash to skill execution
            agent_pubkey = str(self.solana_env.agent_keypair.pubkey())
            
            # Fetch latest blockhash before skill execution
            latest_blockhash_str = None
            try:
                blockhash_resp = await self.solana_env.client.get_latest_blockhash()
                latest_blockhash_str = str(blockhash_resp.value.blockhash)
            except Exception as e:
                logging.warning(f"Failed to fetch blockhash for skill: {e}")
                latest_blockhash_str = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"
            
            result = self.skills.execute_skill(file_path, agent_pubkey=agent_pubkey, latest_blockhash=latest_blockhash_str)
            info["done_reason"] = result.get("reason", result.get("done_reason"))
            if result.get("success"):
                base_reward = result.get("reward", 1.0) # Use reward from skill if provided
            else:
                base_reward = 0.0 # No base reward for failed skill execution
            
            # Get transaction data from skill result
            # Note: tx_receipt_json_string is now a base64-encoded unsigned transaction
            tx_data = result.get("tx_receipt_json_string")
        except Exception as e:
            logging.error(f"Error running skill {skill_id}: {e}")
            info["error"] = f"Exception in skill {skill_id}: {e}"
            base_reward = 0.0 # Ensure reward is 0 on failure
            tx_data = None
        
        # Process the base64 transaction if present
        receipt_str = None
        if tx_data:
            try:
                # Handle base64 transaction
                import base64
                from solders.transaction import Transaction
                
                # Decode the base64 transaction
                tx_bytes = base64.b64decode(tx_data)
                tx = Transaction.from_bytes(tx_bytes)
                
                # Sign with agent keypair
                # Fetch the latest blockhash from surfpool
                from solders.hash import Hash
                try:
                    blockhash_resp = await self.solana_env.client.get_latest_blockhash()
                    latest_blockhash = blockhash_resp.value.blockhash
                except Exception as e:
                    logging.warning(f"Failed to fetch latest blockhash: {e}. Using fallback.")
                    latest_blockhash = Hash.from_string("4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi")
                
                tx.sign([self.solana_env.agent_keypair], latest_blockhash)
                
                # Send transaction through surfpool
                # Note: surfpool_env.step returns (obs, tx_receipt, done, info)
                _, tx_receipt_json, _, send_info = await self.solana_env.step(tx)
                
                if tx_receipt_json:
                    receipt_str = tx_receipt_json
                    info["tx_sent"] = True
                elif send_info.get("possible_success"):
                    # Handle the parsing error case - transaction might have succeeded
                    info["tx_possibly_sent"] = True
                    info["tx_parse_error"] = send_info.get("error")
                    # For testing, treat as success with dummy receipt
                    receipt_str = '{"meta": {"err": null}, "transaction": {}}'
                else:
                    info["tx_error"] = send_info.get("error", "Unknown error")
                    
            except Exception as e:
                logging.error(f"Error processing base64 transaction: {e}")
                info["tx_processing_error"] = str(e)
                receipt_str = None
        
        # The final reward includes a voyager-style exploration bonus.
        # This requires the transaction receipt from the skill execution.
        final_reward = base_reward
        if receipt_str:
            receipt = json.loads(receipt_str)
            protocols = self._protocol_labeler(receipt)
            if protocols:
                info["protocols_interacted"] = protocols
                # Add bonus for each new protocol
                for proto in protocols:
                    if proto not in self.protocols_seen:
                        logging.info(f"New protocol interaction: {proto}! Adding exploration bonus.")
                        self.protocols_seen.add(proto)
                        final_reward += 1.0
                    else:
                        logging.info(f"Already interacted with {proto}. No bonus.")
        
        return final_reward, info

    async def reset(self, *, seed=None, options=None):
        self.t = 0
        self.protocols_seen.clear()
        return await self.solana_env.reset(seed=seed, options=options)

    async def step(self, action: int):
        self.t += 1
        info = {}
        extrinsic_reward = 0.0
        logging.info(f"--- Step {self.t}: Received action {action} ---")

        if action == self.SPECIALS["NEW_SKILL"]:
            extrinsic_reward, info = await self._grow_skill()
        elif action == self.SPECIALS["INSPECT_LIB"]:
            extrinsic_reward, info = self._summarise_library()
        else:
            # The action space is the number of specials + the number of skills.
            # So, the skill_id is the action minus the number of specials.
            skill_id = action - len(self.SPECIALS)
            logging.info(f"Executing skill ID: {skill_id}")
            extrinsic_reward, info = await self._run_skill(skill_id)

        terminated = self.t >= self.max_steps
        
        # The final observation is the last one from the low-level env
        obs = self.solana_env.last_observation
        
        return obs, extrinsic_reward, terminated, False, info

    def render(self, mode="human"):
        return self.solana_env.render(mode=mode)

    async def close(self):
        await self.solana_env.close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Clean up skills from previous runs
    if os.path.exists("./skills"):
        shutil.rmtree("./skills")

    async def main():
        env = SolanaVoyagerEnv()
        obs, info = await env.reset()
        logging.info("--- Voyager Env Reset ---")
        logging.info(f"Initial observation keys: {obs.keys()}")

        # 1. First action: Create a new skill
        logging.info("\n--- Step 1: Creating a new skill ---")
        obs, reward, term, trunc, info = await env.step(env.SPECIALS["NEW_SKILL"])
        logging.info(f"Action: NEW_SKILL, Reward: {reward}, Info: {info}")
        
        # 2. Second action: Execute the newly created skill
        logging.info("\n--- Step 2: Executing the new skill ---")
        if 'new_skill_id' in info:
            skill_to_run = info['new_skill_id']
            action = len(env.SPECIALS) + skill_to_run
            logging.info(f"\n--- Step 2: Executing skill {skill_to_run} with action {action} ---")
            obs, reward, term, trunc, info = await env.step(action)
            logging.info(f"Result of executing skill {skill_to_run} -> Reward: {reward}, Info: {info}")
        else:
            logging.warning("Could not execute new skill, as it was not created.")

        await env.close()

    asyncio.run(main())
