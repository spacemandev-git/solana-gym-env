#!/usr/bin/env python3
"""
Demo: Trajectory Visualization for Solana Voyager Agent

This script demonstrates:
1. Running multiple episodes with trajectory tracking
2. Visualizing agent learning progress
3. Analyzing protocol discovery patterns
"""

import asyncio
import logging
import os
import shutil
from unittest.mock import patch, MagicMock
import json
import random

# Add parent directory to path
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trajectory_tracker import TrajectoryTracker
from trajectory_visualizer import TrajectoryVisualizer
from skill_manager.ts_skill_manager import TypeScriptSkillManager
from planner import LLMPlanner

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


def simulate_skill_generation(protocol: str = None):
    """Generate a mock skill for a specific protocol."""
    protocols = {
        "Jupiter": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "Orca": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
        "Raydium": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "Meteora": "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
        "Marinade": "MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD"
    }
    
    if protocol is None:
        protocol = random.choice(list(protocols.keys()))
    
    program_id = protocols.get(protocol, "11111111111111111111111111111111")
    
    return f'''
export async function executeSkill(env: any): Promise<[number, string, string | null]> {{
    // Skill for {protocol} interaction
    const success = Math.random() > 0.2;  // 80% success rate
    const txReceipt = env.simulateTransaction(success, "{program_id}");
    return [success ? 1.0 : 0.0, success ? "{protocol.lower()}_success" : "{protocol.lower()}_failed", txReceipt];
}}
'''


def simulate_episodes(num_episodes: int = 10, skills_per_episode: int = 5):
    """Simulate multiple episodes with trajectory tracking."""
    tracker = TrajectoryTracker(save_path="trajectory_data.json")
    skills_dir = "./demo_trajectory_skills"
    
    # Clean up and create skills directory
    if os.path.exists(skills_dir):
        shutil.rmtree(skills_dir)
    os.makedirs(skills_dir)
    
    # Initialize skill manager
    skill_manager = TypeScriptSkillManager(skill_root=skills_dir)
    
    # Track which protocols have been discovered globally
    discovered_protocols = set()
    
    for episode_num in range(num_episodes):
        logging.info(f"\n=== Starting Episode {episode_num + 1} ===")
        episode = tracker.start_episode()
        
        # Simulate skill generation and execution
        for skill_attempt in range(skills_per_episode):
            # Decide whether to create a new skill or use existing
            if len(skill_manager.skills) > 0 and random.random() > 0.5:
                # Use existing skill
                skill_id = random.choice(list(skill_manager.skills.keys()))
                skill_name = f"existing_skill_{skill_id}"
                logging.info(f"Using existing skill {skill_id}")
            else:
                # Generate new skill
                # Bias towards undiscovered protocols
                available_protocols = ["Jupiter", "Orca", "Raydium", "Meteora", "Marinade"]
                weights = [0.2 if p in discovered_protocols else 0.8 for p in available_protocols]
                protocol = random.choices(available_protocols, weights=weights)[0]
                
                # Record LLM call
                llm_success = random.random() > 0.1  # 90% success rate
                skill_generated = llm_success and random.random() > 0.2  # 80% of successful calls generate valid skills
                
                tracker.record_llm_call(
                    objective=f"Create skill for {protocol} interaction",
                    success=llm_success,
                    skill_generated=skill_generated,
                    error=None if llm_success else "LLM API error",
                    retry_count=random.randint(0, 2) if not skill_generated else 0
                )
                
                if skill_generated:
                    # Generate and register skill
                    skill_code = simulate_skill_generation(protocol)
                    skill_id = skill_manager.register(skill_code)
                    skill_name = f"{protocol.lower()}_skill_{skill_id}"
                    tracker.record_skill_created(skill_name)
                    logging.info(f"Created new skill for {protocol}")
                else:
                    continue
            
            # Execute skill
            file_path = skill_manager.skills[skill_id]
            result = skill_manager.execute_skill(file_path)
            
            # Parse result to determine which protocol was used
            protocols_in_tx = []
            if result.get("success") and result.get("tx_receipt_json_string"):
                try:
                    receipt = json.loads(result["tx_receipt_json_string"])
                    account_keys = receipt.get("transaction", {}).get("message", {}).get("accountKeys", [])
                    
                    # Map program IDs to protocol names
                    program_to_protocol = {
                        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter",
                        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": "Orca",
                        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium",
                        "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo": "Meteora",
                        "MarBmsSgKXdrN1egZf5sqe1TMai9K1rChYNDJgjq7aD": "Marinade"
                    }
                    
                    for key in account_keys:
                        if key in program_to_protocol:
                            protocol_name = program_to_protocol[key]
                            if protocol_name not in discovered_protocols:
                                protocols_in_tx.append(protocol_name)
                                discovered_protocols.add(protocol_name)
                except:
                    pass
            
            # Record skill attempt
            tracker.record_skill_attempt(
                skill_id=skill_id,
                skill_name=skill_name,
                success=result.get("success", False),
                reward=result.get("reward", 0.0) + len(protocols_in_tx),  # +1 for each new protocol
                done_reason=result.get("done_reason", "unknown"),
                protocols_discovered=protocols_in_tx
            )
            
            logging.info(f"Executed skill {skill_id}: success={result.get('success')}, "
                        f"protocols discovered={protocols_in_tx}")
        
        tracker.end_episode()
        logging.info(f"Episode {episode_num + 1} completed. "
                     f"Total reward: {episode.total_reward:.1f}, "
                     f"Protocols discovered: {episode.protocols_discovered}")
    
    # Clean up
    if os.path.exists(skills_dir):
        shutil.rmtree(skills_dir)
    
    return tracker


def main():
    """Run the trajectory visualization demo."""
    logging.info("=== Solana Voyager Trajectory Visualization Demo ===\n")
    
    # Simulate episodes
    num_episodes = 10
    logging.info(f"Simulating {num_episodes} episodes...")
    tracker = simulate_episodes(num_episodes=num_episodes, skills_per_episode=8)
    
    # Save trajectory data
    tracker.save("trajectory_data.json")
    
    # Create visualizations
    visualizer = TrajectoryVisualizer(tracker)
    
    # Print metrics
    logging.info("\n=== Overall Metrics ===")
    metrics = tracker.get_metrics()
    for key, value in metrics.items():
        logging.info(f"{key}: {value:.2f}" if isinstance(value, float) else f"{key}: {value}")
    
    logging.info("\n=== Jupiter Discovery Metrics ===")
    jupiter_metrics = tracker.get_jupiter_metrics()
    if jupiter_metrics["episodes_with_jupiter"] > 0:
        logging.info(f"Episodes with Jupiter: {jupiter_metrics['episodes_with_jupiter']}")
        logging.info(f"Avg LLM calls to Jupiter: {jupiter_metrics['avg_llm_calls_to_jupiter']:.1f}")
        logging.info(f"Avg skill attempts to Jupiter: {jupiter_metrics['avg_skill_attempts_to_jupiter']:.1f}")
        logging.info(f"Avg time to Jupiter: {jupiter_metrics['avg_time_to_jupiter_seconds']:.1f}s")
    
    # Create visualizations
    logging.info("\n=== Creating Visualizations ===")
    
    # 1. Voyager-style exploration plot
    logging.info("1. Creating Voyager-style exploration performance plot...")
    visualizer.plot_voyager_style_exploration(save_path="voyager_exploration.png")
    
    # 2. Learning curve
    logging.info("2. Creating learning curve...")
    visualizer.plot_learning_curve(save_path="learning_curve.html", interactive=True)
    
    # 3. Jupiter discovery analysis
    logging.info("3. Creating Jupiter discovery analysis...")
    visualizer.plot_jupiter_discovery(save_path="jupiter_discovery.html", interactive=True)
    
    # 4. Protocol timeline
    logging.info("4. Creating protocol timeline...")
    visualizer.plot_protocol_timeline(save_path="protocol_timeline.html")
    
    # 5. Skill efficiency
    logging.info("5. Creating skill efficiency plot...")
    visualizer.plot_skill_efficiency(save_path="skill_efficiency.html")
    
    # 6. Comprehensive dashboard
    logging.info("6. Creating comprehensive dashboard...")
    visualizer.plot_comprehensive_dashboard(save_path="dashboard.html")
    
    logging.info("\n✅ Visualizations created successfully!")
    logging.info("Check the following files:")
    logging.info("- voyager_exploration.png (Voyager-style plot)")
    logging.info("- learning_curve.html (Interactive learning curve)")
    logging.info("- jupiter_discovery.html (Jupiter discovery analysis)")
    logging.info("- protocol_timeline.html (Protocol discovery timeline)")
    logging.info("- skill_efficiency.html (Skill success rates)")
    logging.info("- dashboard.html (Comprehensive dashboard)")
    logging.info("- trajectory_data.json (Raw trajectory data)")


if __name__ == "__main__":
    main()