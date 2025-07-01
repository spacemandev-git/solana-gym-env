import gymnasium as gym
import asyncio
import os
import logging
import traceback
import json
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

    def _protocol_labeler(self, tx_receipt: Dict[str, Any]) -> str | None:
        """
        Identifies the protocol from a transaction receipt by checking for known
        program IDs in the transaction's instructions. This check is performed
        regardless of whether the transaction succeeded or failed.
        """
        if not tx_receipt:
            return None

        try:
            # The transaction object contains account keys as strings
            account_keys = tx_receipt.get("transaction", {}).get("message", {}).get("accountKeys", [])
            if not account_keys:
                return None

            # The instructions contain indices into the account_keys list
            instructions = tx_receipt.get("transaction", {}).get("message", {}).get("instructions", [])

            for instruction in instructions:
                program_id_index = instruction.get("programIdIndex")
                if program_id_index is not None and program_id_index < len(account_keys):
                    program_id_str = account_keys[program_id_index]
                    if program_id_str in KNOWN_PROGRAM_IDS:
                        return KNOWN_PROGRAM_IDS[program_id_str]
                for key in account_keys:
                    if key in KNOWN_PROGRAM_IDS:
                        return KNOWN_PROGRAM_IDS[key]
        except Exception as e:
            logging.error(f"Error during protocol labeling: {e}")

        return None

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
                result = self.skills.execute_skill(file_path)
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
            result = self.skills.execute_skill(file_path)
            info["done_reason"] = result.get("reason")
            if result.get("success"):
                base_reward = 1.0 # Base reward for successful skill execution
            else:
                base_reward = 0.0 # No base reward for failed skill execution
        except Exception as e:
            logging.error(f"Error running skill {skill_id}: {e}")
            info["error"] = f"Exception in skill {skill_id}: {e}"
            base_reward = 0.0 # Ensure reward is 0 on failure
        
        # The final reward includes a voyager-style exploration bonus.
        # This requires the transaction receipt from the last observation,
        # which is set by the env.step() call inside the skill.
        final_reward = base_reward
        # receipt_str = self.solana_env.last_observation
        # Reset observation to prevent state leakage
        # self.solana_env.last_observation = None

        receipt_str = self.solana_env.last_tx_receipt
        if receipt_str:
            receipt = json.loads(receipt_str)
            proto = self._protocol_labeler(receipt)
            if proto:
                info["protocol"] = proto
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
