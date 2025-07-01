#!/usr/bin/env python3
"""
Quick Trajectory Demo - Generate sample data and visualizations
"""

import json
import time
import random
import os
import matplotlib.pyplot as plt

# Add parent directory to path
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trajectory_tracker import TrajectoryTracker, SkillAttempt, LLMCall
from trajectory_visualizer import TrajectoryVisualizer


def generate_sample_trajectory_data():
    """Generate sample trajectory data for visualization."""
    tracker = TrajectoryTracker()
    
    protocols = ["Jupiter", "Orca", "Raydium", "Meteora", "Marinade"]
    discovered = set()
    
    # Simulate 8 episodes
    for ep_num in range(8):
        episode = tracker.start_episode()
        
        # Vary the number of attempts per episode
        num_attempts = random.randint(5, 12)
        
        for attempt_num in range(num_attempts):
            # Simulate LLM calls (30% of attempts involve new skill generation)
            if random.random() < 0.3 or len(discovered) == 0:
                # Record LLM call
                llm_call = LLMCall(
                    timestamp=time.time() + 0.1,
                    objective="Generate skill for DeFi interaction",
                    success=random.random() > 0.1,
                    skill_generated=random.random() > 0.2,
                    retry_count=random.randint(0, 2)
                )
                episode.llm_calls.append(llm_call)
                
                if llm_call.skill_generated:
                    episode.skills_created.append(f"skill_{len(episode.skills_created)}")
            
            # Choose protocol (bias towards undiscovered)
            if discovered and random.random() < 0.7:
                # Use existing protocol
                protocol = random.choice(list(discovered))
                new_protocols = []
            else:
                # Try new protocol
                remaining = [p for p in protocols if p not in discovered]
                if remaining:
                    protocol = random.choice(remaining)
                    if random.random() > 0.3:  # 70% chance of actually discovering
                        new_protocols = [protocol]
                        discovered.add(protocol)
                    else:
                        new_protocols = []
                else:
                    protocol = random.choice(protocols)
                    new_protocols = []
            
            # Create skill attempt
            success = random.random() > 0.2  # 80% success rate
            base_reward = 1.0 if success else 0.0
            discovery_reward = len(new_protocols)
            
            attempt = SkillAttempt(
                timestamp=time.time() + attempt_num * 0.5,
                skill_id=random.randint(0, max(0, len(episode.skills_created) - 1)),
                skill_name=f"{protocol.lower()}_swap",
                success=success,
                reward=base_reward + discovery_reward,
                done_reason="success" if success else "failed",
                protocols_discovered=new_protocols
            )
            
            episode.skill_attempts.append(attempt)
            episode.total_reward += attempt.reward
            
            # Track discovered protocols in episode
            for p in new_protocols:
                if p not in episode.protocols_discovered:
                    episode.protocols_discovered.append(p)
        
        episode.end_time = time.time() + num_attempts * 0.5
        
        # Add some variance to make it interesting
        if ep_num == 3:  # Episode with Jupiter discovery
            # Ensure Jupiter is discovered in this episode
            for attempt in episode.skill_attempts[:3]:
                if "Jupiter" not in discovered:
                    attempt.protocols_discovered = ["Jupiter"]
                    discovered.add("Jupiter")
                    episode.protocols_discovered.append("Jupiter")
                    break
    
    tracker.end_episode()
    return tracker


def main():
    """Generate sample data and create visualizations."""
    print("=== Quick Trajectory Visualization Demo ===\n")
    
    # Generate sample data
    print("Generating sample trajectory data...")
    tracker = generate_sample_trajectory_data()
    
    # Save data
    tracker.save("sample_trajectory_data.json")
    print(f"✓ Saved trajectory data with {len(tracker.episodes)} episodes")
    
    # Print metrics
    print("\n=== Metrics ===")
    metrics = tracker.get_metrics()
    print(f"Total episodes: {metrics['total_episodes']}")
    print(f"Total LLM calls: {metrics['total_llm_calls']}")
    print(f"Total skill attempts: {metrics['total_skill_attempts']}")
    print(f"Protocols discovered: {metrics['total_protocols_discovered']}")
    print(f"Success rate: {metrics['success_rate']:.1%}")
    
    jupiter_metrics = tracker.get_jupiter_metrics()
    if jupiter_metrics["episodes_with_jupiter"] > 0:
        print(f"\nJupiter discovered in {jupiter_metrics['episodes_with_jupiter']} episodes")
        print(f"Avg attempts to Jupiter: {jupiter_metrics['avg_skill_attempts_to_jupiter']:.1f}")
    
    # Create visualizations
    print("\n=== Creating Visualizations ===")
    visualizer = TrajectoryVisualizer(tracker)
    
    # 1. Voyager-style plot (most important)
    print("Creating Voyager-style exploration plot...")
    visualizer.plot_voyager_style_exploration(save_path="voyager_style_demo.png")
    print("✓ Saved: voyager_style_demo.png")
    
    # 2. Interactive dashboard
    print("Creating comprehensive dashboard...")
    visualizer.plot_comprehensive_dashboard(save_path="trajectory_dashboard.html")
    print("✓ Saved: trajectory_dashboard.html")
    
    # 3. Jupiter analysis
    print("Creating Jupiter discovery analysis...")
    visualizer.plot_jupiter_discovery(save_path="jupiter_analysis.html")
    print("✓ Saved: jupiter_analysis.html")
    
    print("\n✅ Demo complete! Check the generated files:")
    print("- voyager_style_demo.png (Main visualization)")
    print("- trajectory_dashboard.html (Interactive dashboard)")
    print("- jupiter_analysis.html (Jupiter discovery analysis)")
    print("- sample_trajectory_data.json (Raw data)")


if __name__ == "__main__":
    main()