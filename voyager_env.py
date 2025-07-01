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

# Mapping of known program IDs to protocol names
# (This would be expanded in a real scenario)
KNOWN_PROGRAM_IDS: Dict[str, str] = {
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter",
    "MeteoRb91wabcB2m8T8T16cfj2hD6yB2a2d7s65": "Meteora",
    # Add more program IDs here
}


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
        self.skills = SkillManager(skill_root=skill_root)
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
                skill_func = self.skills.load_skill_from_code(skill_code)
            except Exception as e:
                logging.error(f"Syntax error in generated skill: {e}")
                last_error = f"Syntax error: {e}"
                continue

            try:
                logging.info("Testing the newly generated skill...")
                reward, reason = await skill_func(self.solana_env)
                logging.info(f"Skill test result: reward={reward}, reason='{reason}'")

                if reward > 0:
                    skill_id = self.skills.register(skill_code)
                    self._update_action_space()
                    info = {"new_skill_id": skill_id, "status": "success"}
                    return 1.0, info
                else:
                    last_error = f"Skill executed but failed. Reason: {reason}"

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

        skill_func = self.skills[skill_id]
        base_reward = 0.0
        info = {}

        try:
            base_reward, done_reason = await skill_func(self.solana_env)
            info["done_reason"] = done_reason
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
