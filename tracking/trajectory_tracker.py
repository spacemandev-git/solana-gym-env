"""
Trajectory Tracker for Solana Voyager Agent

Tracks and visualizes agent learning trajectories including:
- AI/LLM calls
- Skill generation attempts
- Skill execution results
- Protocol discoveries
- Rewards over time
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
import logging


@dataclass
class TransactionDetails:
    """Detailed information about a transaction."""
    signature: str
    slot: int
    compute_units_consumed: int
    fee: int  # in lamports
    num_accounts: int
    num_instructions: int
    instructions: List[Dict[str, Any]]  # Simplified instruction info
    account_keys: List[str]
    success: bool
    log_messages: List[str]
    block_time: Optional[int] = None
    
@dataclass
class SkillAttempt:
    """Record of a single skill execution attempt."""
    timestamp: float
    skill_id: int
    skill_name: str
    success: bool
    reward: float
    done_reason: str
    protocols_discovered: List[str] = field(default_factory=list)
    error: Optional[str] = None
    transaction_details: Optional[TransactionDetails] = None


@dataclass
class LLMCall:
    """Record of an LLM API call for skill generation."""
    timestamp: float
    objective: str
    success: bool
    skill_generated: bool
    error: Optional[str] = None
    retry_count: int = 0


@dataclass
class Episode:
    """Complete episode trajectory."""
    episode_id: int
    start_time: float
    end_time: Optional[float] = None
    total_reward: float = 0.0
    llm_calls: List[LLMCall] = field(default_factory=list)
    skill_attempts: List[SkillAttempt] = field(default_factory=list)
    protocols_discovered: List[str] = field(default_factory=list)
    skills_created: List[str] = field(default_factory=list)
    
    @property
    def duration(self) -> float:
        """Episode duration in seconds."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time
    
    @property
    def llm_efficiency(self) -> float:
        """Ratio of successful skill generations to total LLM calls."""
        if not self.llm_calls:
            return 0.0
        successful = sum(1 for call in self.llm_calls if call.skill_generated)
        return successful / len(self.llm_calls)


class TrajectoryTracker:
    """Tracks agent learning trajectories across episodes."""
    
    def __init__(self, save_path: Optional[str] = None):
        self.episodes: List[Episode] = []
        self.current_episode: Optional[Episode] = None
        self.save_path = save_path
        self._episode_counter = 0
        
    def start_episode(self) -> Episode:
        """Start tracking a new episode."""
        self._episode_counter += 1
        self.current_episode = Episode(
            episode_id=self._episode_counter,
            start_time=time.time()
        )
        self.episodes.append(self.current_episode)
        logging.info(f"Started tracking episode {self._episode_counter}")
        return self.current_episode
    
    def end_episode(self):
        """End the current episode."""
        if self.current_episode:
            self.current_episode.end_time = time.time()
            logging.info(f"Ended episode {self.current_episode.episode_id} - "
                        f"Duration: {self.current_episode.duration:.2f}s, "
                        f"Total reward: {self.current_episode.total_reward}")
            if self.save_path:
                self.save()
            self.current_episode = None
    
    def record_llm_call(self, objective: str, success: bool, 
                       skill_generated: bool, error: Optional[str] = None,
                       retry_count: int = 0):
        """Record an LLM API call."""
        if not self.current_episode:
            logging.warning("No active episode to record LLM call")
            return
            
        call = LLMCall(
            timestamp=time.time(),
            objective=objective,
            success=success,
            skill_generated=skill_generated,
            error=error,
            retry_count=retry_count
        )
        self.current_episode.llm_calls.append(call)
        
    def record_skill_attempt(self, skill_id: int, skill_name: str,
                           success: bool, reward: float, done_reason: str,
                           protocols_discovered: List[str] = None,
                           error: Optional[str] = None,
                           transaction_details: Optional[TransactionDetails] = None):
        """Record a skill execution attempt."""
        if not self.current_episode:
            logging.warning("No active episode to record skill attempt")
            return
            
        attempt = SkillAttempt(
            timestamp=time.time(),
            skill_id=skill_id,
            skill_name=skill_name,
            success=success,
            reward=reward,
            done_reason=done_reason,
            protocols_discovered=protocols_discovered or [],
            error=error,
            transaction_details=transaction_details
        )
        self.current_episode.skill_attempts.append(attempt)
        self.current_episode.total_reward += reward
        
        # Track new protocol discoveries
        for protocol in (protocols_discovered or []):
            if protocol not in self.current_episode.protocols_discovered:
                self.current_episode.protocols_discovered.append(protocol)
    
    def record_skill_created(self, skill_name: str):
        """Record creation of a new skill."""
        if not self.current_episode:
            logging.warning("No active episode to record skill creation")
            return
            
        self.current_episode.skills_created.append(skill_name)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get aggregate metrics across all episodes."""
        if not self.episodes:
            return {}
            
        total_llm_calls = sum(len(ep.llm_calls) for ep in self.episodes)
        total_skill_attempts = sum(len(ep.skill_attempts) for ep in self.episodes)
        total_protocols = len(set(
            protocol 
            for ep in self.episodes 
            for protocol in ep.protocols_discovered
        ))
        
        successful_attempts = sum(
            1 for ep in self.episodes
            for attempt in ep.skill_attempts
            if attempt.success
        )
        
        return {
            "total_episodes": len(self.episodes),
            "total_llm_calls": total_llm_calls,
            "total_skill_attempts": total_skill_attempts,
            "total_protocols_discovered": total_protocols,
            "success_rate": successful_attempts / total_skill_attempts if total_skill_attempts > 0 else 0,
            "avg_llm_calls_per_episode": total_llm_calls / len(self.episodes),
            "avg_reward_per_episode": sum(ep.total_reward for ep in self.episodes) / len(self.episodes),
        }
    
    def get_jupiter_metrics(self) -> Dict[str, Any]:
        """Get metrics specifically for Jupiter protocol discovery."""
        jupiter_episodes = []
        
        for ep in self.episodes:
            for i, attempt in enumerate(ep.skill_attempts):
                if "Jupiter" in attempt.protocols_discovered:
                    # Found Jupiter!
                    llm_calls_before = len([
                        call for call in ep.llm_calls 
                        if call.timestamp <= attempt.timestamp
                    ])
                    skill_attempts_before = i + 1
                    
                    jupiter_episodes.append({
                        "episode_id": ep.episode_id,
                        "llm_calls_to_jupiter": llm_calls_before,
                        "skill_attempts_to_jupiter": skill_attempts_before,
                        "time_to_jupiter": attempt.timestamp - ep.start_time,
                        "protocols_before_jupiter": [
                            p for a in ep.skill_attempts[:i] 
                            for p in a.protocols_discovered
                        ]
                    })
                    break
        
        if jupiter_episodes:
            avg_llm_calls = sum(ep["llm_calls_to_jupiter"] for ep in jupiter_episodes) / len(jupiter_episodes)
            avg_attempts = sum(ep["skill_attempts_to_jupiter"] for ep in jupiter_episodes) / len(jupiter_episodes)
            avg_time = sum(ep["time_to_jupiter"] for ep in jupiter_episodes) / len(jupiter_episodes)
            
            return {
                "episodes_with_jupiter": len(jupiter_episodes),
                "avg_llm_calls_to_jupiter": avg_llm_calls,
                "avg_skill_attempts_to_jupiter": avg_attempts,
                "avg_time_to_jupiter_seconds": avg_time,
                "jupiter_episodes": jupiter_episodes
            }
        
        return {"episodes_with_jupiter": 0}
    
    def save(self, path: Optional[str] = None):
        """Save trajectory data to JSON file."""
        save_path = path or self.save_path
        if not save_path:
            logging.warning("No save path specified")
            return
            
        data = {
            "episodes": [self._episode_to_dict(ep) for ep in self.episodes],
            "metrics": self.get_metrics(),
            "jupiter_metrics": self.get_jupiter_metrics(),
            "timestamp": datetime.now().isoformat()
        }
        
        with open(save_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        logging.info(f"Saved trajectory data to {save_path}")
    
    def load(self, path: str):
        """Load trajectory data from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        
        self.episodes = []
        for ep_data in data["episodes"]:
            episode = Episode(
                episode_id=ep_data["episode_id"],
                start_time=ep_data["start_time"],
                end_time=ep_data.get("end_time"),
                total_reward=ep_data["total_reward"],
                protocols_discovered=ep_data["protocols_discovered"],
                skills_created=ep_data["skills_created"]
            )
            
            # Reconstruct LLM calls
            for call_data in ep_data["llm_calls"]:
                episode.llm_calls.append(LLMCall(**call_data))
            
            # Reconstruct skill attempts
            for attempt_data in ep_data["skill_attempts"]:
                # Handle transaction details if present
                tx_details = attempt_data.get("transaction_details")
                if tx_details:
                    attempt_data["transaction_details"] = TransactionDetails(**tx_details)
                episode.skill_attempts.append(SkillAttempt(**attempt_data))
            
            self.episodes.append(episode)
        
        self._episode_counter = len(self.episodes)
        logging.info(f"Loaded {len(self.episodes)} episodes from {path}")
    
    def _episode_to_dict(self, episode: Episode) -> Dict[str, Any]:
        """Convert episode to dictionary for serialization."""
        return {
            "episode_id": episode.episode_id,
            "start_time": episode.start_time,
            "end_time": episode.end_time,
            "total_reward": episode.total_reward,
            "duration": episode.duration,
            "protocols_discovered": episode.protocols_discovered,
            "skills_created": episode.skills_created,
            "llm_calls": [asdict(call) for call in episode.llm_calls],
            "skill_attempts": [asdict(attempt) for attempt in episode.skill_attempts],
            "llm_efficiency": episode.llm_efficiency
        }