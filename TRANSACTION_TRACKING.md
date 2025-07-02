# Transaction Complexity Tracking

This document describes the transaction complexity tracking system added to the Solana Voyager agent.

## Overview

The transaction tracking system captures detailed information about every transaction executed by the agent, including:
- Transaction signatures and slots
- Compute units consumed
- Fees paid (in SOL)
- Number of accounts involved
- Number and types of instructions
- Success/failure status
- Log messages

## Components

### 1. Enhanced Trajectory Tracker (`trajectory_tracker.py`)

Added `TransactionDetails` dataclass to capture:
```python
@dataclass
class TransactionDetails:
    signature: str
    slot: int
    compute_units_consumed: int
    fee: int  # in lamports
    num_accounts: int
    num_instructions: int
    instructions: List[Dict[str, Any]]
    account_keys: List[str]
    success: bool
    log_messages: List[str]
    block_time: Optional[int] = None
```

### 2. Transaction Parser (`transaction_parser.py`)

Provides utilities for:
- Parsing Solana transaction receipts
- Extracting compute units from log messages
- Identifying instruction types and programs
- Calculating transaction complexity scores
- Formatting human-readable summaries

### 3. Enhanced Visualizations (`trajectory_visualizer.py`)

New visualization methods:

#### `plot_transaction_complexity()`
Creates a 4-panel analysis showing:
- Transaction complexity over time
- Compute units distribution
- Fee analysis (box plot)
- Instruction count distribution

#### `create_transaction_browser()`
Interactive browser with:
- Filterable transaction list
- Detailed metrics for each transaction
- Instruction breakdown
- Expandable log viewer
- Filters by episode, success status, and complexity

### 4. Integration (`voyager_env_with_tracking.py`)

Enhanced VoyagerEnv that:
- Tracks all LLM calls and skill attempts
- Parses transaction receipts automatically
- Records transaction details with each skill execution
- Saves comprehensive trajectory data

## Usage

### Basic Usage

```python
from voyager_env_with_tracking import VoyagerEnvWithTracking

# Create environment with tracking enabled
env = VoyagerEnvWithTracking(
    solana_env=solana_env,
    skill_runner=skill_runner,
    skill_manager=skill_manager,
    planner=planner,
    surfpool_env=surfpool_env,
    enable_tracking=True
)

# Run episodes - tracking happens automatically
await env.reset()
# ... run steps ...
await env.close()  # Saves trajectory data

# Access tracker for visualization
tracker = env.get_tracker()
```

### Visualization

```python
from trajectory_visualizer import TrajectoryVisualizer

# Create visualizer
viz = TrajectoryVisualizer(tracker)

# Generate transaction complexity analysis
viz.plot_transaction_complexity("tx_complexity.html")

# Create interactive transaction browser
viz.create_transaction_browser("tx_browser.html")
```

### Demo

Run the demo to see all features:
```bash
uv run demo_transaction_complexity.py
```

This creates:
- `transaction_complexity_analysis.html`: Multi-panel analysis
- `transaction_browser.html`: Interactive transaction browser
- `voyager_with_transactions.png`: Voyager-style plot
- `comprehensive_dashboard.html`: Full dashboard

## Transaction Complexity Score

The complexity score is calculated based on:
- Number of instructions (×10 points)
- Number of accounts (×5 points)
- Compute units (normalized, max 50 points)
- Cross-program invocations (×20 points each)
- Unique programs (×15 points each)

This helps identify the most complex transactions and patterns in agent behavior.

## Benefits

1. **Performance Analysis**: Track compute unit usage and fees over time
2. **Debugging**: Detailed transaction logs and instruction breakdowns
3. **Pattern Recognition**: Identify which skills create complex transactions
4. **Cost Optimization**: Analyze fee patterns and optimize skill implementations
5. **Learning Insights**: Correlate transaction complexity with learning progress

## Future Enhancements

- Real-time transaction monitoring
- Automated complexity alerts
- Transaction replay capabilities
- Cost prediction models
- Integration with Solana Explorer links