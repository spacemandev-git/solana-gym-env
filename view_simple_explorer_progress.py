#!/usr/bin/env python3
"""
Simple progress viewer for simple_explorer.py runs.
Displays rewards, discovered programs, and recent agent activity from trace files.
"""

import json
import os
import glob
from datetime import datetime
import csv

def view_progress():
    # Find the most recent trace files
    trace_files = glob.glob("traces/*.json")
    reward_files = glob.glob("traces/*_reward.csv")
    
    if not trace_files:
        print("No trace files found. Run 'uv run python voyager/simple_explorer.py' first.")
        return
    
    # Get the most recent trace file
    latest_trace = max(trace_files, key=os.path.getctime)
    run_id = os.path.basename(latest_trace).replace('.json', '')
    
    print(f"\n{'='*60}")
    print(f"Simple Explorer Progress - Run ID: {run_id}")
    print(f"{'='*60}\n")
    
    # Load and analyze trace messages
    with open(latest_trace, 'r') as f:
        messages = json.load(f)
    
    # Count statistics
    tool_calls = 0
    skills_executed = 0
    skills_written = 0
    discovered_programs = set()
    errors = []
    rewards = []
    
    for msg in messages:
        if msg.get('role') == 'assistant' and msg.get('tool_calls'):
            for tool_call in msg['tool_calls']:
                tool_calls += 1
                func_name = tool_call['function']['name']
                if func_name == 'executeSkill':
                    skills_executed += 1
                elif func_name == 'writeSkill':
                    skills_written += 1
        
        elif msg.get('role') == 'tool':
            # Parse tool response for rewards and observations
            try:
                content = json.loads(msg['content'])
                if isinstance(content, dict):
                    if 'reward' in content:
                        rewards.append(content['reward'])
                    if 'info' in content and 'discovered_programs' in content['info']:
                        discovered_programs.update(content['info']['discovered_programs'])
            except (json.JSONDecodeError, TypeError):
                # Check for error messages
                if 'error' in str(msg.get('content', '')).lower():
                    errors.append(msg['content'][:100])  # First 100 chars of error
    
    # Load reward history from CSV if available
    reward_file = f"traces/{run_id}_reward.csv"
    total_reward = 0
    if os.path.exists(reward_file):
        with open(reward_file, 'r') as f:
            lines = f.readlines()
            if lines:
                last_line = lines[-1].strip()
                if last_line:
                    _, total_reward = last_line.split(',')
                    total_reward = float(total_reward)
    
    # Display statistics
    print(f"📊 **Statistics**")
    print(f"  • Total messages: {len(messages)}")
    print(f"  • Tool calls made: {tool_calls}")
    print(f"  • Skills executed: {skills_executed}")
    print(f"  • Skills written: {skills_written}")
    print(f"  • Total reward: {total_reward:.2f}")
    print(f"  • Unique programs discovered: {len(discovered_programs)}")
    if errors:
        print(f"  • Errors encountered: {len(errors)}")
    print()
    
    # Show discovered programs
    if discovered_programs:
        print(f"🎯 **Discovered Programs** ({len(discovered_programs)}):")
        for prog in list(discovered_programs)[:10]:  # Show first 10
            print(f"  • {prog}")
        if len(discovered_programs) > 10:
            print(f"  ... and {len(discovered_programs) - 10} more")
        print()
    
    # Show recent activity (last 5 tool calls)
    print(f"🔄 **Recent Activity**:")
    recent_tools = []
    for msg in reversed(messages):
        if msg.get('role') == 'assistant' and msg.get('tool_calls'):
            for tool_call in msg['tool_calls']:
                func_name = tool_call['function']['name']
                args = json.loads(tool_call['function']['arguments'])
                if func_name == 'executeSkill':
                    recent_tools.append(f"Executed skill: {args.get('skill_name')}")
                elif func_name == 'writeSkill':
                    recent_tools.append(f"Wrote skill: {args.get('skill_name')}")
                elif func_name == 'fetchTransactions':
                    recent_tools.append(f"Fetched transactions for: {args.get('program_id')[:8]}...")
                elif func_name == 'readSkills':
                    recent_tools.append("Read available skills")
                
                if len(recent_tools) >= 5:
                    break
            if len(recent_tools) >= 5:
                break
    
    for activity in recent_tools:
        print(f"  • {activity}")
    
    if errors:
        print(f"\n⚠️  **Recent Errors** (first 3):")
        for error in errors[:3]:
            print(f"  • {error}")
    
    print(f"\n{'='*60}")
    print("Tip: Run 'tail -f traces/*.json' to monitor in real-time")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    view_progress()