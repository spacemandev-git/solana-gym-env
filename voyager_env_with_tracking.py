"""
Enhanced Voyager Environment with Transaction Tracking

This version includes:
- Trajectory tracking for agent learning
- Transaction complexity analysis
- Detailed transaction parsing
"""

import json
import logging
from typing import Optional, Dict, Any, Tuple

from voyager_env import VoyagerEnv
from trajectory_tracker import TrajectoryTracker
from transaction_parser import parse_transaction_receipt


class VoyagerEnvWithTracking(VoyagerEnv):
    """Voyager environment with integrated trajectory and transaction tracking."""
    
    def __init__(self, solana_env, skill_runner, skill_manager, planner, 
                 surfpool_env, max_steps=10, enable_tracking=True):
        super().__init__(solana_env, skill_runner, skill_manager, planner, 
                        surfpool_env, max_steps)
        
        self.enable_tracking = enable_tracking
        self.tracker = TrajectoryTracker() if enable_tracking else None
        self.current_episode = None
        
    async def reset(self, *, seed=None, options=None):
        """Reset environment and start new episode tracking."""
        result = await super().reset(seed=seed, options=options)
        
        if self.enable_tracking and self.tracker:
            # End previous episode if exists
            if self.current_episode:
                self.tracker.end_episode()
            
            # Start new episode
            self.current_episode = self.tracker.start_episode()
            logging.info(f"Started tracking episode {self.current_episode.episode_id}")
        
        return result
    
    async def _grow_skill(self) -> Tuple[float, Dict[str, Any]]:
        """Grow a new skill with LLM call tracking."""
        # Get current observation
        observation = self.solana_env.last_observation
        
        # Record LLM call start
        if self.enable_tracking and self.tracker:
            objective = "Generate new DeFi interaction skill"
        
        # Generate skill using planner
        skill_code = self.planner.propose(observation)
        
        if skill_code is None:
            logging.error("Failed to grow skill from LLM.")
            if self.enable_tracking and self.tracker:
                self.tracker.record_llm_call(
                    objective=objective,
                    success=False,
                    skill_generated=False,
                    error="Failed to generate skill code"
                )
            return 0.0, {"error": "Failed to grow skill from LLM"}
        
        # Record successful LLM call
        if self.enable_tracking and self.tracker:
            self.tracker.record_llm_call(
                objective=objective,
                success=True,
                skill_generated=True
            )
        
        # Save skill
        skill_name = self.skill_manager.save_skill(skill_code)
        logging.info(f"Grew and saved new skill: {skill_name}")
        
        # Record skill creation
        if self.enable_tracking and self.tracker:
            self.tracker.record_skill_created(skill_name)
        
        return 0.0, {"skill_grown": skill_name}
    
    async def _run_skill(self, skill_id: int) -> Tuple[float, Dict[str, Any]]:
        """Execute a skill with transaction tracking."""
        total_skills = self.skill_manager.get_skill_count()
        
        if skill_id < 0 or skill_id >= total_skills:
            logging.warning(f"Invalid skill ID: {skill_id}. Total skills: {total_skills}")
            return 0.0, {"error": f"Invalid skill ID {skill_id}"}
        
        skill_code = self.skill_manager.get_skill_code(skill_id)
        skill_name = self.skill_manager.get_skill_name(skill_id)
        
        if skill_code is None:
            logging.error(f"Failed to retrieve skill code for ID {skill_id}")
            return 0.0, {"error": f"Failed to retrieve skill {skill_id}"}
        
        logging.info(f"Retrieved skill {skill_name} (ID: {skill_id})")
        
        # Execute skill
        reward, done_reason, tx_receipt_json = await self.skill_runner.run_skill(
            skill_code, skill_id, self.surfpool_env
        )
        
        logging.info(f"Skill execution result - Reward: {reward}, Done reason: {done_reason}")
        
        info = {
            "skill_id": skill_id,
            "skill_name": skill_name,
            "done_reason": done_reason
        }
        
        # Parse transaction details if available
        tx_details = None
        if tx_receipt_json:
            tx_details = parse_transaction_receipt(tx_receipt_json)
            if tx_details:
                logging.info(f"Transaction details - CUs: {tx_details.compute_units_consumed:,}, "
                           f"Fee: {tx_details.fee / 1e9:.6f} SOL, "
                           f"Instructions: {tx_details.num_instructions}")
        
        # Process for protocol discovery
        final_reward = reward
        protocols_discovered = []
        
        if tx_receipt_json:
            protocols = self._protocol_labeler(json.loads(tx_receipt_json))
            if protocols:
                info["protocols_interacted"] = protocols
                protocols_discovered = protocols
                
                # Add bonus for each new protocol
                for proto in protocols:
                    if proto not in self.protocols_seen:
                        logging.info(f"New protocol interaction: {proto}! Adding exploration bonus.")
                        self.protocols_seen.add(proto)
                        final_reward += 1.0
                    else:
                        logging.info(f"Already interacted with {proto}. No bonus.")
        
        # Record skill attempt with transaction details
        if self.enable_tracking and self.tracker:
            self.tracker.record_skill_attempt(
                skill_id=skill_id,
                skill_name=skill_name,
                success=reward > 0,
                reward=final_reward,
                done_reason=done_reason,
                protocols_discovered=protocols_discovered,
                transaction_details=tx_details
            )
        
        return final_reward, info
    
    async def close(self):
        """Close environment and save trajectory data."""
        if self.enable_tracking and self.tracker:
            if self.current_episode:
                self.tracker.end_episode()
            
            # Save trajectory data
            self.tracker.save("trajectory_data.json")
            logging.info("Saved trajectory data to trajectory_data.json")
        
        await super().close()
    
    def get_tracker(self) -> Optional[TrajectoryTracker]:
        """Get the trajectory tracker instance."""
        return self.tracker