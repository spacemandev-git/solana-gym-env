import gymnasium as gym
import asyncio
import os
import logging
import traceback
import json
from typing import Set, Dict, Any

from surfpool_env import SurfpoolEnv
from skill_library import SkillManager
from planner import LLMPlanner

# --- Constants ---
CONFIG_MAX_LLM_SKILL_TRIES = 3

import csv

# Mapping of known program IDs to protocol names
# This will be populated from data/program_ids.csv at runtime
KNOWN_PROGRAM_IDS: Dict[str, str] = {}

def load_program_ids_from_csv(file_path: str) -> Dict[str, str]:
    """Loads program IDs and their corresponding project names from a CSV file."""
    program_ids = {}
    if not os.path.exists(file_path):
        logging.warning(f"Program IDs CSV file not found: {file_path}")
        return program_ids

    with open(file_path, mode='r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            program_address = row.get("program_address")
            project_name = row.get("project_name")
            if program_address and project_name:
                program_ids[program_address] = project_name
    return program_ids


class SolanaVoyagerEnv(gym.Env):
    """
    High-level Gymnasium wrapper for a Solana agent, inspired by the Voyager paper.
    The agent can choose to either execute a known skill, propose a new skill
    via an LLM, or inspect its library of skills.
    """
    metadata = {"render_modes": ["human"]}
    
    SPECIALS = {"NEW_SKILL": 0, "INSPECT_LIB": 1}

    def __init__(self, max_steps: int = 128, skill_root: str = "./skills", program_ids_csv: str = "data/program_ids.csv"):
        # Layer 0: The low-level Solana environment
        self.solana_env = SurfpoolEnv()
        self.observation_space = self.solana_env.observation_space

        # Layer 1: Voyager components
        self.skills = SkillManager(skill_root=skill_root)
        self.planner = LLMPlanner(self.skills)

        # Load KNOWN_PROGRAM_IDS at initialization
        global KNOWN_PROGRAM_IDS
        KNOWN_PROGRAM_IDS = load_program_ids_from_csv(program_ids_csv)
        if not KNOWN_PROGRAM_IDS:
            raise RuntimeError(f"Failed to load KNOWN_PROGRAM_IDS from {program_ids_csv}. It might be missing or empty.")

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

    def _protocol_labeler(self, tx_receipt: Dict[str, Any]) -> Set[str]:
        """
        Identifies all unique protocols from a transaction receipt by checking for known
        program IDs in the transaction's instructions and inner instructions.
        Only considers protocols from successful transactions.
        Returns a set of identified protocol names.
        """
        identified_protocols: Set[str] = set()

        if not tx_receipt:
            return identified_protocols

        # Check if the transaction itself failed
        if tx_receipt.get("meta", {}).get("err") is not None:
            logging.info("Transaction failed, skipping protocol labeling.")
            return identified_protocols

        try:
            account_keys = tx_receipt.get("transaction", {}).get("message", {}).get("accountKeys", [])
            if not account_keys:
                return identified_protocols

            # Helper to extract program IDs from instructions
            def extract_program_ids(instructions_list):
                for instruction in instructions_list:
                    program_id_index = instruction.get("programIdIndex")
                    if program_id_index is not None and program_id_index < len(account_keys):
                        program_id_str = account_keys[program_id_index]
                        if program_id_str in KNOWN_PROGRAM_IDS:
                            identified_protocols.add(KNOWN_PROGRAM_IDS[program_id_str])
                    # Also check account keys directly, as some protocols might be identified by other keys
                    for key in account_keys:
                        if key in KNOWN_PROGRAM_IDS:
                            identified_protocols.add(KNOWN_PROGRAM_IDS[key])

            # Process top-level instructions
            instructions = tx_receipt.get("transaction", {}).get("message", {}).get("instructions", [])
            extract_program_ids(instructions)

            # Process inner instructions
            inner_instructions = tx_receipt.get("meta", {}).get("innerInstructions", [])
            for inner_ix_entry in inner_instructions:
                extract_program_ids(inner_ix_entry.get("instructions", []))

        except Exception as e:
            logging.error(f"Error during protocol labeling: {e}")

        return identified_protocols

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
                # For _grow_skill, we need to load the skill and then execute it
                # to test its functionality. The skill_func here is a direct
                # callable that expects the env and returns the new tuple.
                skill_func_path = self.skills.save_skill("temp_test_skill", skill_code)
            except Exception as e:
                logging.error(f"Syntax error in generated skill: {e}")
                last_error = f"Syntax error: {e}"
                continue

            try:
                logging.info("Testing the newly generated skill...")
                # Execute the skill using the manager, which now returns the full result
                skill_result = self.skills.execute_skill(skill_func_path)
                
                reward = skill_result.get("reward", 0.0)
                done_reason = skill_result.get("done_reason", "unknown")
                tx_receipt_json_string = skill_result.get("tx_receipt_json_string")

                logging.info(f"Skill test result: reward={reward}, reason='{done_reason}'")

                # A skill is considered successful if it yields a positive reward
                if reward > 0:
                    skill_id = self.skills.register(skill_code)
                    self._update_action_space()
                    info = {"new_skill_id": skill_id, "status": "success"}
                    return 1.0, info # Reward for successfully growing a skill
                else:
                    last_error = f"Skill executed but failed. Reason: {done_reason}"
                    if not skill_result.get("success"): # If runSkill.ts itself reported failure
                        last_error += f" Skill runner reported failure: {skill_result.get('reason', 'No reason provided')}"

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
        if skill_id not in self.skills:
            return 0.0, {"error": f"Skill {skill_id} not found."}

        file_path = self.skills[skill_id]
        base_reward = 0.0
        info = {}
        
        try:
            # Execute the skill using the manager, which now returns the full result
            skill_result = self.skills.execute_skill(file_path)
            
            base_reward = skill_result.get("reward", 0.0)
            info["done_reason"] = skill_result.get("done_reason", "unknown")
            tx_receipt_json_string = skill_result.get("tx_receipt_json_string")

            # If the skill itself reported a non-success or 0 reward, set an error message
            if not skill_result.get("success") or base_reward == 0.0:
                info["error"] = f"Skill execution failed or yielded no reward. Reason: {info['done_reason']}. Runner status: {skill_result.get('reason', 'N/A')}"
                # base_reward is already 0.0 if skill_result.get("reward") was 0.0
        except Exception as e:
            logging.error(f"Error running skill {skill_id}: {e}")
            info["error"] = f"Exception in skill {skill_id}: {e}"
            base_reward = 0.0 # Ensure reward is 0 on failure
        
        final_reward = base_reward

        if tx_receipt_json_string:
            try:
                receipt = json.loads(tx_receipt_json_string)
                # _protocol_labeler now returns a set of protocols
                new_protocols = self._protocol_labeler(receipt) 
                
                if new_protocols:
                    info["protocols_interacted"] = list(new_protocols) # For logging/info purposes
                    for proto in new_protocols:
                        if proto not in self.protocols_seen:
                            logging.info(f"New protocol interaction: {proto}! Adding exploration bonus.")
                            self.protocols_seen.add(proto)
                            final_reward += 1.0
                        else:
                            logging.info(f"Already interacted with {proto}. No bonus.")
            except json.JSONDecodeError:
                logging.error(f"Failed to decode transaction receipt JSON: {tx_receipt_json_string}")
            except Exception as e:
                logging.error(f"Error processing transaction receipt: {e}")
        
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
