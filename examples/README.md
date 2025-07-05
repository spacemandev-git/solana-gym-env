# Solana Gym Examples

This directory contains example code demonstrating various features of Solana Gym.

## 📂 Structure

### demos/
Demo scripts showing key functionality:
- `demo_skill_generation.py` - Demonstrates LLM-based skill generation
- `demo_trajectory_visualization.py` - Shows how to visualize agent trajectories
- `demo_transaction_complexity.py` - Analyzes transaction complexity metrics
- `quick_trajectory_demo.py` - Quick demo of trajectory tracking
- `sample_trajectory_data.json` - Sample trajectory data for testing
- `demo_trajectory_with_transactions.json` - Detailed transaction tracking example

### tests/
Test scripts for specific components:
- `test_surfpool_*.py` - Various Surfpool integration tests
- `surfpool_repro.py` - Reproduction script for Surfpool issues

## 🚀 Running Examples

```bash
# Run a demo
uv run python examples/demos/demo_skill_generation.py

# Run a test
uv run python examples/tests/test_surfpool_send_base58.py
```

## 📊 Sample Data

The JSON files in `demos/` contain sample trajectory data showing:
- Protocol discoveries
- Skill execution attempts
- Reward attribution
- Transaction details

Use these as references for the expected data format when implementing your own tracking.