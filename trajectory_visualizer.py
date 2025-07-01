"""
Trajectory Visualizer for Solana Voyager Agent

Creates visual representations of agent learning trajectories.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from trajectory_tracker import TrajectoryTracker, Episode
import json


class TrajectoryVisualizer:
    """Creates visualizations of agent learning trajectories."""
    
    def __init__(self, tracker: TrajectoryTracker):
        self.tracker = tracker
        
        # Color scheme for protocols
        self.protocol_colors = {
            "Jupiter": "#FE6E00",
            "Orca": "#8B4AE2", 
            "Raydium": "#00D18C",
            "Meteora": "#FFD700",
            "Marinade": "#1E90FF",
            "Default": "#808080"
        }
    
    def plot_learning_curve(self, save_path: Optional[str] = None, 
                          interactive: bool = True) -> None:
        """Plot cumulative reward over time across episodes."""
        if interactive:
            fig = self._plot_learning_curve_plotly()
            if save_path:
                fig.write_html(save_path)
            fig.show()
        else:
            self._plot_learning_curve_matplotlib(save_path)
    
    def plot_jupiter_discovery(self, save_path: Optional[str] = None,
                             interactive: bool = True) -> None:
        """Plot metrics for Jupiter protocol discovery."""
        jupiter_metrics = self.tracker.get_jupiter_metrics()
        
        if jupiter_metrics["episodes_with_jupiter"] == 0:
            print("No episodes with Jupiter discovery found.")
            return
        
        if interactive:
            fig = self._plot_jupiter_discovery_plotly(jupiter_metrics)
            if save_path:
                fig.write_html(save_path)
            fig.show()
        else:
            self._plot_jupiter_discovery_matplotlib(jupiter_metrics, save_path)
    
    def plot_protocol_timeline(self, episode_id: Optional[int] = None,
                             save_path: Optional[str] = None) -> None:
        """Plot timeline of protocol discoveries in an episode."""
        if episode_id is None:
            # Use last episode with protocols
            for ep in reversed(self.tracker.episodes):
                if ep.protocols_discovered:
                    episode = ep
                    break
            else:
                print("No episodes with protocol discoveries found.")
                return
        else:
            episode = next((ep for ep in self.tracker.episodes 
                          if ep.episode_id == episode_id), None)
            if not episode:
                print(f"Episode {episode_id} not found.")
                return
        
        fig = self._create_protocol_timeline(episode)
        if save_path:
            fig.write_html(save_path)
        fig.show()
    
    def plot_skill_efficiency(self, save_path: Optional[str] = None) -> None:
        """Plot skill success rates and LLM efficiency over episodes."""
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=("Skill Success Rate", "LLM Efficiency"),
            vertical_spacing=0.15
        )
        
        # Calculate metrics per episode
        episodes = []
        success_rates = []
        llm_efficiencies = []
        
        for ep in self.tracker.episodes:
            if ep.skill_attempts:
                success_rate = sum(1 for a in ep.skill_attempts if a.success) / len(ep.skill_attempts)
                success_rates.append(success_rate)
            else:
                success_rates.append(0)
            
            episodes.append(ep.episode_id)
            llm_efficiencies.append(ep.llm_efficiency)
        
        # Success rate
        fig.add_trace(
            go.Scatter(x=episodes, y=success_rates, mode='lines+markers',
                      name='Success Rate', line=dict(color='green', width=2)),
            row=1, col=1
        )
        
        # LLM efficiency
        fig.add_trace(
            go.Scatter(x=episodes, y=llm_efficiencies, mode='lines+markers',
                      name='LLM Efficiency', line=dict(color='blue', width=2)),
            row=2, col=1
        )
        
        fig.update_xaxes(title_text="Episode", row=2, col=1)
        fig.update_yaxes(title_text="Rate", row=1, col=1)
        fig.update_yaxes(title_text="Efficiency", row=2, col=1)
        
        fig.update_layout(
            title="Agent Learning Efficiency",
            height=600,
            showlegend=False
        )
        
        if save_path:
            fig.write_html(save_path)
        fig.show()
    
    def plot_voyager_style_exploration(self, save_path: Optional[str] = None) -> None:
        """Create Voyager-style exploration performance visualization."""
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        # Left plot: Unique protocols discovered over iterations
        unique_protocols = set()
        unique_protocols_timeline = []
        iteration_count = 0
        
        for ep in self.tracker.episodes:
            for attempt in ep.skill_attempts:
                iteration_count += 1
                for protocol in attempt.protocols_discovered:
                    unique_protocols.add(protocol)
                unique_protocols_timeline.append(len(unique_protocols))
        
        iterations = list(range(1, iteration_count + 1))
        ax1.plot(iterations, unique_protocols_timeline, 'b-', linewidth=2.5)
        ax1.fill_between(iterations, 0, unique_protocols_timeline, alpha=0.3, color='blue')
        ax1.set_xlabel('Iteration', fontsize=14)
        ax1.set_ylabel('Unique Protocols Discovered', fontsize=14)
        ax1.set_title('Protocol Discovery Progress', fontsize=16)
        ax1.grid(True, alpha=0.3)
        
        # Add protocol discovery annotations
        protocol_first_discovery = {}
        iter_idx = 0
        for ep in self.tracker.episodes:
            for attempt in ep.skill_attempts:
                iter_idx += 1
                for protocol in attempt.protocols_discovered:
                    if protocol not in protocol_first_discovery:
                        protocol_first_discovery[protocol] = iter_idx
        
        # Annotate major protocol discoveries
        for protocol, iter_num in sorted(protocol_first_discovery.items(), 
                                       key=lambda x: x[1])[:5]:  # Top 5 earliest
            y_val = unique_protocols_timeline[iter_num - 1] if iter_num <= len(unique_protocols_timeline) else len(unique_protocols)
            ax1.annotate(protocol, 
                        xy=(iter_num, y_val),
                        xytext=(iter_num + 5, y_val + 0.5),
                        arrowprops=dict(arrowstyle='->', 
                                      color=self.protocol_colors.get(protocol, 'gray'),
                                      lw=1.5),
                        fontsize=10,
                        bbox=dict(boxstyle="round,pad=0.3", 
                                facecolor=self.protocol_colors.get(protocol, 'gray'),
                                alpha=0.3))
        
        # Right plot: Skill success rate over episodes
        success_rates = []
        skill_counts = []
        
        for ep in self.tracker.episodes:
            if ep.skill_attempts:
                success_rate = sum(1 for a in ep.skill_attempts if a.success) / len(ep.skill_attempts)
                success_rates.append(success_rate * 100)
                skill_counts.append(len(ep.skills_created))
            else:
                success_rates.append(0)
                skill_counts.append(0)
        
        episodes = list(range(1, len(self.tracker.episodes) + 1))
        
        # Create bar plot for skill counts
        ax2_twin = ax2.twinx()
        bars = ax2.bar(episodes, skill_counts, alpha=0.3, color='green', label='Skills Created')
        
        # Overlay success rate line
        line = ax2_twin.plot(episodes, success_rates, 'r-', linewidth=2.5, 
                            marker='o', markersize=6, label='Success Rate')[0]
        
        ax2.set_xlabel('Episode', fontsize=14)
        ax2.set_ylabel('Skills Created', fontsize=14, color='green')
        ax2_twin.set_ylabel('Success Rate (%)', fontsize=14, color='red')
        ax2.set_title('Skill Creation and Success Rate', fontsize=16)
        ax2.grid(True, alpha=0.3)
        
        # Color the y-axis labels
        ax2.tick_params(axis='y', labelcolor='green')
        ax2_twin.tick_params(axis='y', labelcolor='red')
        
        # Add legend
        lines = [bars, line]
        labels = ['Skills Created', 'Success Rate']
        ax2.legend(lines, labels, loc='upper left')
        
        plt.suptitle('Solana Voyager Agent - Exploration Performance', fontsize=18)
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.show()
    
    def plot_comprehensive_dashboard(self, save_path: Optional[str] = None) -> None:
        """Create a comprehensive dashboard of agent performance."""
        fig = make_subplots(
            rows=3, cols=2,
            subplot_titles=(
                "Cumulative Rewards", "Protocols Discovered",
                "LLM Calls per Episode", "Skills Created",
                "Success Rate Trend", "Time to Jupiter Discovery"
            ),
            vertical_spacing=0.1,
            horizontal_spacing=0.1,
            specs=[[{"type": "scatter"}, {"type": "bar"}],
                   [{"type": "bar"}, {"type": "scatter"}],
                   [{"type": "scatter"}, {"type": "box"}]]
        )
        
        # 1. Cumulative rewards
        cumulative_rewards = []
        total = 0
        for ep in self.tracker.episodes:
            total += ep.total_reward
            cumulative_rewards.append(total)
        
        fig.add_trace(
            go.Scatter(x=list(range(1, len(self.tracker.episodes) + 1)),
                      y=cumulative_rewards, mode='lines+markers',
                      name='Cumulative Reward', line=dict(color='green')),
            row=1, col=1
        )
        
        # 2. Protocols discovered
        protocol_counts = {}
        for ep in self.tracker.episodes:
            for protocol in ep.protocols_discovered:
                protocol_counts[protocol] = protocol_counts.get(protocol, 0) + 1
        
        if protocol_counts:
            fig.add_trace(
                go.Bar(x=list(protocol_counts.keys()),
                      y=list(protocol_counts.values()),
                      marker_color=[self.protocol_colors.get(p, self.protocol_colors["Default"]) 
                                   for p in protocol_counts.keys()]),
                row=1, col=2
            )
        
        # 3. LLM calls per episode
        llm_calls = [len(ep.llm_calls) for ep in self.tracker.episodes]
        fig.add_trace(
            go.Bar(x=list(range(1, len(self.tracker.episodes) + 1)),
                  y=llm_calls, marker_color='lightblue'),
            row=2, col=1
        )
        
        # 4. Skills created over time
        cumulative_skills = []
        total_skills = 0
        for ep in self.tracker.episodes:
            total_skills += len(ep.skills_created)
            cumulative_skills.append(total_skills)
        
        fig.add_trace(
            go.Scatter(x=list(range(1, len(self.tracker.episodes) + 1)),
                      y=cumulative_skills, mode='lines+markers',
                      line=dict(color='purple')),
            row=2, col=2
        )
        
        # 5. Success rate trend
        success_rates = []
        for ep in self.tracker.episodes:
            if ep.skill_attempts:
                rate = sum(1 for a in ep.skill_attempts if a.success) / len(ep.skill_attempts)
                success_rates.append(rate)
            else:
                success_rates.append(0)
        
        fig.add_trace(
            go.Scatter(x=list(range(1, len(success_rates) + 1)),
                      y=success_rates, mode='lines+markers',
                      line=dict(color='orange')),
            row=3, col=1
        )
        
        # 6. Time to Jupiter (box plot)
        jupiter_metrics = self.tracker.get_jupiter_metrics()
        if jupiter_metrics["episodes_with_jupiter"] > 0:
            times = [ep["time_to_jupiter"] for ep in jupiter_metrics["jupiter_episodes"]]
            fig.add_trace(
                go.Box(y=times, name="Time to Jupiter", marker_color='#FE6E00'),
                row=3, col=2
            )
        
        # Update layout
        fig.update_layout(
            title="Solana Voyager Agent Performance Dashboard",
            height=900,
            showlegend=False
        )
        
        # Update axes
        fig.update_xaxes(title_text="Episode", row=1, col=1)
        fig.update_xaxes(title_text="Protocol", row=1, col=2)
        fig.update_xaxes(title_text="Episode", row=2, col=1)
        fig.update_xaxes(title_text="Episode", row=2, col=2)
        fig.update_xaxes(title_text="Episode", row=3, col=1)
        
        fig.update_yaxes(title_text="Reward", row=1, col=1)
        fig.update_yaxes(title_text="Count", row=1, col=2)
        fig.update_yaxes(title_text="LLM Calls", row=2, col=1)
        fig.update_yaxes(title_text="Skills", row=2, col=2)
        fig.update_yaxes(title_text="Success Rate", row=3, col=1)
        fig.update_yaxes(title_text="Time (seconds)", row=3, col=2)
        
        if save_path:
            fig.write_html(save_path)
        fig.show()
    
    def _plot_learning_curve_plotly(self) -> go.Figure:
        """Create interactive learning curve with Plotly."""
        fig = go.Figure()
        
        # Cumulative reward
        cumulative_rewards = []
        episode_ids = []
        total = 0
        
        for ep in self.tracker.episodes:
            total += ep.total_reward
            cumulative_rewards.append(total)
            episode_ids.append(ep.episode_id)
        
        fig.add_trace(go.Scatter(
            x=episode_ids,
            y=cumulative_rewards,
            mode='lines+markers',
            name='Cumulative Reward',
            line=dict(color='green', width=2),
            marker=dict(size=8)
        ))
        
        # Add protocol discovery markers
        for ep in self.tracker.episodes:
            for attempt in ep.skill_attempts:
                if attempt.protocols_discovered:
                    for protocol in attempt.protocols_discovered:
                        idx = episode_ids.index(ep.episode_id)
                        fig.add_annotation(
                            x=ep.episode_id,
                            y=cumulative_rewards[idx],
                            text=protocol,
                            showarrow=True,
                            arrowhead=2,
                            arrowsize=1,
                            arrowwidth=2,
                            arrowcolor=self.protocol_colors.get(protocol, self.protocol_colors["Default"]),
                            ax=0,
                            ay=-40
                        )
        
        fig.update_layout(
            title="Agent Learning Curve",
            xaxis_title="Episode",
            yaxis_title="Cumulative Reward",
            hovermode='x unified'
        )
        
        return fig
    
    def _plot_jupiter_discovery_plotly(self, jupiter_metrics: Dict) -> go.Figure:
        """Create interactive Jupiter discovery visualization."""
        episodes = jupiter_metrics["jupiter_episodes"]
        
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "LLM Calls to Jupiter", "Skill Attempts to Jupiter",
                "Time to Jupiter (seconds)", "Protocols Before Jupiter"
            )
        )
        
        # Extract data
        episode_ids = [ep["episode_id"] for ep in episodes]
        llm_calls = [ep["llm_calls_to_jupiter"] for ep in episodes]
        skill_attempts = [ep["skill_attempts_to_jupiter"] for ep in episodes]
        times = [ep["time_to_jupiter"] for ep in episodes]
        
        # 1. LLM calls
        fig.add_trace(
            go.Bar(x=episode_ids, y=llm_calls, name="LLM Calls",
                  marker_color='lightblue'),
            row=1, col=1
        )
        
        # 2. Skill attempts
        fig.add_trace(
            go.Bar(x=episode_ids, y=skill_attempts, name="Skill Attempts",
                  marker_color='lightgreen'),
            row=1, col=2
        )
        
        # 3. Time to discovery
        fig.add_trace(
            go.Scatter(x=episode_ids, y=times, mode='lines+markers',
                      name="Time", line=dict(color='red')),
            row=2, col=1
        )
        
        # 4. Protocols before Jupiter
        protocols_before = [len(ep["protocols_before_jupiter"]) for ep in episodes]
        fig.add_trace(
            go.Bar(x=episode_ids, y=protocols_before, name="Other Protocols",
                  marker_color='purple'),
            row=2, col=2
        )
        
        # Add average lines
        avg_llm = jupiter_metrics["avg_llm_calls_to_jupiter"]
        avg_attempts = jupiter_metrics["avg_skill_attempts_to_jupiter"]
        avg_time = jupiter_metrics["avg_time_to_jupiter_seconds"]
        
        fig.add_hline(y=avg_llm, line_dash="dash", line_color="blue",
                     annotation_text=f"Avg: {avg_llm:.1f}", row=1, col=1)
        fig.add_hline(y=avg_attempts, line_dash="dash", line_color="green",
                     annotation_text=f"Avg: {avg_attempts:.1f}", row=1, col=2)
        fig.add_hline(y=avg_time, line_dash="dash", line_color="red",
                     annotation_text=f"Avg: {avg_time:.1f}s", row=2, col=1)
        
        fig.update_layout(
            title="Jupiter Protocol Discovery Analysis",
            showlegend=False,
            height=600
        )
        
        return fig
    
    def _create_protocol_timeline(self, episode: Episode) -> go.Figure:
        """Create timeline visualization of protocol discoveries."""
        fig = go.Figure()
        
        # Group attempts by protocol
        protocol_attempts = {}
        for attempt in episode.skill_attempts:
            for protocol in attempt.protocols_discovered:
                if protocol not in protocol_attempts:
                    protocol_attempts[protocol] = []
                protocol_attempts[protocol].append(attempt)
        
        # Create timeline
        y_pos = 0
        for protocol, attempts in protocol_attempts.items():
            times = [(a.timestamp - episode.start_time) for a in attempts]
            rewards = [a.reward for a in attempts]
            
            # Add scatter plot for this protocol
            fig.add_trace(go.Scatter(
                x=times,
                y=[y_pos] * len(times),
                mode='markers+text',
                name=protocol,
                marker=dict(
                    size=[r * 20 + 10 for r in rewards],  # Size based on reward
                    color=self.protocol_colors.get(protocol, self.protocol_colors["Default"]),
                    line=dict(width=2, color='black')
                ),
                text=[f"R:{r:.1f}" for r in rewards],
                textposition="top center",
                hovertemplate=f"{protocol}<br>Time: %{{x:.1f}}s<br>Reward: %{{text}}<extra></extra>"
            ))
            y_pos += 1
        
        # Add LLM call markers
        llm_times = [(call.timestamp - episode.start_time) for call in episode.llm_calls]
        if llm_times:
            fig.add_trace(go.Scatter(
                x=llm_times,
                y=[-1] * len(llm_times),
                mode='markers',
                name='LLM Calls',
                marker=dict(symbol='diamond', size=8, color='gray'),
                hovertemplate="LLM Call<br>Time: %{x:.1f}s<extra></extra>"
            ))
        
        fig.update_layout(
            title=f"Protocol Discovery Timeline - Episode {episode.episode_id}",
            xaxis_title="Time (seconds)",
            yaxis=dict(
                tickmode='array',
                tickvals=list(range(-1, len(protocol_attempts))),
                ticktext=['LLM Calls'] + list(protocol_attempts.keys())
            ),
            height=400 + len(protocol_attempts) * 50,
            hovermode='closest'
        )
        
        return fig
    
    def _plot_learning_curve_matplotlib(self, save_path: Optional[str]) -> None:
        """Create static learning curve with matplotlib."""
        fig, ax = plt.subplots(figsize=(10, 6))
        
        cumulative_rewards = []
        total = 0
        
        for ep in self.tracker.episodes:
            total += ep.total_reward
            cumulative_rewards.append(total)
        
        episodes = list(range(1, len(self.tracker.episodes) + 1))
        ax.plot(episodes, cumulative_rewards, 'g-', linewidth=2, marker='o')
        
        ax.set_xlabel('Episode')
        ax.set_ylabel('Cumulative Reward')
        ax.set_title('Agent Learning Curve')
        ax.grid(True, alpha=0.3)
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.show()
    
    def _plot_jupiter_discovery_matplotlib(self, jupiter_metrics: Dict, 
                                         save_path: Optional[str]) -> None:
        """Create static Jupiter discovery visualization."""
        episodes = jupiter_metrics["jupiter_episodes"]
        
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        fig.suptitle('Jupiter Protocol Discovery Analysis')
        
        episode_ids = [ep["episode_id"] for ep in episodes]
        
        # LLM calls
        axes[0, 0].bar(episode_ids, [ep["llm_calls_to_jupiter"] for ep in episodes])
        axes[0, 0].axhline(y=jupiter_metrics["avg_llm_calls_to_jupiter"], 
                          color='r', linestyle='--', label='Average')
        axes[0, 0].set_title('LLM Calls to Jupiter')
        axes[0, 0].set_xlabel('Episode')
        axes[0, 0].legend()
        
        # Skill attempts
        axes[0, 1].bar(episode_ids, [ep["skill_attempts_to_jupiter"] for ep in episodes])
        axes[0, 1].axhline(y=jupiter_metrics["avg_skill_attempts_to_jupiter"],
                          color='r', linestyle='--', label='Average')
        axes[0, 1].set_title('Skill Attempts to Jupiter')
        axes[0, 1].set_xlabel('Episode')
        axes[0, 1].legend()
        
        # Time to discovery
        axes[1, 0].plot(episode_ids, [ep["time_to_jupiter"] for ep in episodes], 'ro-')
        axes[1, 0].axhline(y=jupiter_metrics["avg_time_to_jupiter_seconds"],
                          color='r', linestyle='--', label='Average')
        axes[1, 0].set_title('Time to Jupiter Discovery (seconds)')
        axes[1, 0].set_xlabel('Episode')
        axes[1, 0].legend()
        
        # Protocols before
        axes[1, 1].bar(episode_ids, [len(ep["protocols_before_jupiter"]) for ep in episodes])
        axes[1, 1].set_title('Protocols Discovered Before Jupiter')
        axes[1, 1].set_xlabel('Episode')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.show()