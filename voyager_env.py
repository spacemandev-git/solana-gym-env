import gymnasium as gym
import asyncio
import os
from typing import Set

from surfpool_env import SurfpoolEnv
from skill_library import SkillManager
from planner import LLMPlanner

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

    def _protocol_labeler(self, tx_receipt: dict) -> str | None:
        """
        Identifies the protocol from a transaction receipt.
        """
        if not tx_receipt or tx_receipt["meta"]["err"] is not None:
            return None

        # TODO: Implement robust protocol labeling by inspecting logs
        # For example, check for program IDs in log messages.
        # log_messages = tx_receipt["meta"].get("logMessages", [])
        # if any("jup" in log.lower() for log in log_messages):
        #     return "Jupiter"
        
        return "dummy_protocol" # Placeholder

    async def _grow_skill(self):
        """Generates and registers a new skill."""
        if self.solana_env.last_observation is None:
            return 0.0, {"error": "Cannot grow skill without an observation"}

        skill_code = self.planner.propose(self.solana_env.last_observation)
        skill_id = self.skills.register(skill_code)
        self._update_action_space()
        
        info = {"new_skill_id": skill_id}
        # Small reward for encouraging the creation of new skills
        extrinsic_reward = 0.1
        return extrinsic_reward, info

    def _summarise_library(self):
        """Returns a summary of the skill library."""
        # The "summary" could be a feature vector for the agent.
        # For now, we'll just return the number of skills.
        info = {"num_skills": len(self.skills)}
        # No reward for just looking.
        return 0.0, info

    async def _run_skill(self, skill_id: int):
        """Executes a skill and computes the reward."""
        if skill_id not in self.skills:
            return 0.0, {"error": f"Skill {skill_id} not found."}
            
        skill_func = self.skills[skill_id]
        
        try:
            # The skill function returns the reward and a reason for termination.
            extrinsic_reward, done_reason = await skill_func(self.solana_env)
            info = {"done_reason": done_reason}
        except Exception as e:
            print(f"Error running skill {skill_id}: {e}")
            return 0.0, {"error": str(e)}

        # The reward logic is now inside the skill.
        # Here, we can add the voyager-style exploration bonus.
        # We need the transaction receipt from the low-level env.
        receipt = self.solana_env.last_observation
        
        proto = self._protocol_labeler(receipt) if receipt and "meta" in receipt else None
        
        if proto and proto not in self.protocols_seen:
            self.protocols_seen.add(proto)
            extrinsic_reward += 1.0  # Add bonus for new protocol
            
        info["protocol"] = proto
        return extrinsic_reward, info

    async def reset(self, *, seed=None, options=None):
        self.t = 0
        self.protocols_seen.clear()
        return await self.solana_env.reset(seed=seed, options=options)

    async def step(self, action: int):
        self.t += 1
        info = {}
        extrinsic_reward = 0.0
        print(f"--- Step {self.t}: Received action {action} ---")

        if action == self.SPECIALS["NEW_SKILL"]:
            extrinsic_reward, info = await self._grow_skill()
        elif action == self.SPECIALS["INSPECT_LIB"]:
            extrinsic_reward, info = self._summarise_library()
        else:
            skill_id = action - len(self.SPECIALS)
            print(f"Calculated skill_id: {skill_id}")
            extrinsic_reward, info = await self._run_skill(skill_id)

        terminated = self.t >= self.max_steps
        
        # The final observation is the last one from the low-level env
        obs = self.solana_env.last_observation
        
        return obs, extrinsic_reward, terminated, False, info

    def render(self, mode="human"):
        return self.solana_env.render(mode=mode)

    def close(self):
        return self.solana_env.close()

if __name__ == '__main__':
    import shutil
    # Clean up skills from previous runs
    if os.path.exists("./skills"):
        shutil.rmtree("./skills")

    async def main():
        env = SolanaVoyagerEnv()
        obs, info = await env.reset()
        print("--- Voyager Env Reset ---")
        print(f"Initial observation keys: {obs.keys()}")

        # 1. First action: Create a new skill
        print("\n--- Step 1: Creating a new skill ---")
        obs, reward, term, trunc, info = await env.step(env.SPECIALS["NEW_SKILL"])
        print(f"Action: NEW_SKILL, Reward: {reward}, Info: {info}")
        
        # 2. Second action: Execute the newly created skill
        print("\n--- Step 2: Executing the new skill ---")
        if 'new_skill_id' in info:
            skill_to_run = info['new_skill_id']
            # Action should be 2 (0=NEW_SKILL, 1=INSPECT_LIB, 2=skill_0)
            action = len(env.SPECIALS) + skill_to_run
            print(f"\n--- Step 2: Executing skill {skill_to_run} with action {action} ---")
            obs, reward, term, trunc, info = await env.step(action)
            print(f"Result of executing skill {skill_to_run} -> Reward: {reward}, Info: {info}")
        else:
            print("Could not execute new skill, as it was not created.")

        env.close()

    asyncio.run(main())
