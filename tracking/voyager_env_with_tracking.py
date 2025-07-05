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

from voyager_env import SolanaVoyagerEnv
from trajectory_tracker import TrajectoryTracker
from transaction_parser import parse_transaction_receipt


class VoyagerEnvWithTracking(SolanaVoyagerEnv):
    """Voyager environment with integrated trajectory and transaction tracking."""
    
    def __init__(self, max_steps: int = 128, skill_root: str = "./skills", enable_tracking=True):
        super().__init__(max_steps=max_steps, skill_root=skill_root)
        
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
        # Track LLM call start
        objective = "Generate new DeFi interaction skill"
        
        # Call parent's _grow_skill method
        reward, info = await super()._grow_skill()
        
        # Track the LLM call result
        if self.enable_tracking and self.tracker:
            if "error" in info:
                self.tracker.record_llm_call(
                    objective=objective,
                    success=False,
                    skill_generated=False,
                    error=info["error"]
                )
            elif "skill_grown" in info:
                self.tracker.record_llm_call(
                    objective=objective,
                    success=True,
                    skill_generated=True
                )
                # Record skill creation
                self.tracker.record_skill_created(info["skill_grown"])
        
        return reward, info
    
    async def _run_skill(self, skill_id: int) -> Tuple[float, Dict[str, Any]]:
        """Execute a skill with transaction tracking."""
        # Call parent's _run_skill method to get proper transaction handling
        final_reward, info = await super()._run_skill(skill_id)
        
        # Extract relevant information for tracking
        skill_name = self.skills.get_skill_name(skill_id) if skill_id < len(self.skills.skills) else f"skill_{skill_id}"
        done_reason = info.get("done_reason", "unknown")
        protocols_discovered = info.get("protocols_interacted", [])
        
        # Parse transaction details if available
        tx_details = None
        # The parent method doesn't directly expose the receipt, but we can check if a transaction was sent
        if info.get("tx_sent") or info.get("tx_possibly_sent"):
            # For now, we'll track without full transaction details
            # In the future, we could modify the parent to expose the receipt
            tx_details = None
        
        # Record skill attempt with tracking
        if self.enable_tracking and self.tracker:
            self.tracker.record_skill_attempt(
                skill_id=skill_id,
                skill_name=skill_name,
                success=final_reward > 0,
                reward=final_reward,
                done_reason=done_reason,
                protocols_discovered=protocols_discovered,
                transaction_details=tx_details
            )
            
            logging.info(f"Tracked skill attempt: {skill_name}, reward: {final_reward}, protocols: {protocols_discovered}")
        
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