# Voyager: Autonomous Solana Exploration

> **An implementation of the NVIDIA Voyager paper adapted for Solana blockchain exploration, where AI agents learn to autonomously discover and interact with DeFi protocols through self-generated TypeScript skills.**

## Overview

This project adapts the groundbreaking [Voyager paper](https://voyager.minedojo.org/) from Minecraft to the Solana blockchain. Instead of exploring a 3D world, our agents explore the DeFi ecosystem, discovering new protocols and building a library of reusable skills.

### Key Features

- **Self-Learning**: Agents generate their own TypeScript code to interact with Solana
- **Skill Library**: Accumulated knowledge persists across episodes
- **Protocol Discovery**: Rewards for finding new program instructions
- **Safe Environment**: Runs against local Solana test validator (surfpool)
- **Progress Tracking**: Comprehensive CSV logging and agent message tracking

## Architecture

```
┌─────────────────────────────────────────┐
│         Voyager Agent System            │
├─────────────────────────────────────────┤
│  • Curriculum Agent: Proposes tasks     │
│  • Action Agent: Generates TypeScript   │
│  • Critic Agent: Evaluates success      │
│  • Skill Manager: Stores & retrieves    │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│      TypeScript Skill Runner (Bun)      │
├─────────────────────────────────────────┤
│  • Executes generated TypeScript code   │
│  • Returns serialized transactions      │
│  • Enforces single transaction limit    │
└────────────────┬───────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│    Surfpool (Local Solana Validator)    │
├─────────────────────────────────────────┤
│  • Pre-funded test accounts             │
│  • Mainnet fork with real programs      │
│  • Safe sandbox for experimentation     │
└─────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.8+ with [uv](https://github.com/astral-sh/uv)
- [Bun](https://bun.sh) v1.1.42+
- [Surfpool](https://github.com/novy4/surfpool) (Solana test environment)
- OpenRouter API key for LLM access

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd voyager

# Install Python dependencies
uv pip install -e .
uv pip install -r requirements.txt
uv pip install langchain-community

# Install TypeScript dependencies
cd voyager/skill_runner && bun install
cd ../..

# Set up environment variables
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY & OPENAI_API_KEY
```

### Running the Voyager

```bash
# Run the main Voyager learning loop
uv run python -m voyager.voyager_clone

# Or run the simpler explorer (recommended for better reliability)
uv run python -m voyager.simple_explorer

# View progress (in another terminal)
python view_progress.py
```

## How It Works

### 1. **Task Generation**

The Curriculum Agent observes the current state and proposes tasks that will discover new program instructions:

- Starts with simple SOL transfers
- Progresses to token operations
- Explores DeFi protocols systematically

### 2. **Code Generation**

The Action Agent uses an LLM to generate TypeScript code that:

- Builds Solana transactions
- Returns base64-encoded serialized transactions
- Handles only ONE transaction per skill (enforced)

### 3. **Skill Execution**

Generated code runs in an isolated Bun environment:

```typescript
// Example generated skill
async function buildTransaction() {
  const connection = new web3.Connection("http://127.0.0.1:8899");
  const wallet = new web3.PublicKey(AGENT_WALLET_ADDRESS);

  // Generate a random recipient
  const recipient = web3.Keypair.generate().publicKey;

  // Build transfer instruction
  const transaction = new web3.Transaction();
  transaction.add(
    web3.SystemProgram.transfer({
      fromPubkey: wallet,
      toPubkey: recipient,
      lamports: 0.1 * web3.LAMPORTS_PER_SOL,
    })
  );

  // Set blockhash and serialize
  const { blockhash } = await connection.getLatestBlockhash();
  transaction.recentBlockhash = blockhash;
  transaction.feePayer = wallet;

  return Buffer.from(
    transaction.serialize({
      requireAllSignatures: false,
    })
  ).toString("base64");
}
```

### 4. **Evaluation & Learning**

- Critic Agent evaluates task success
- Successful skills are added to the library
- Rewards given for discovering new (program_id, instruction) pairs

## Progress Tracking

The system tracks comprehensive metrics in CSV format:

```bash
# View latest run progress
python view_progress.py

# Output includes:
# - Success rate per task
# - Total rewards earned
# - Unique instructions discovered
# - Programs explored
# - Agent conversation logs
```

### Tracked Metrics

- `iteration`: Sequential task number
- `task`: Task description
- `task_success`: Boolean success indicator
- `reward`: Points for new instruction discovery
- `discovered_programs`: Unique program count
- `unique_instructions`: Total instruction types found
- `sol_balance`: Current wallet balance
- `error`: Error messages if failed
- `critique`: Feedback from critic agent

## 🎮 Key Differences from Original Voyager

| Aspect      | Minecraft Voyager          | Solana Voyager                |
| ----------- | -------------------------- | ----------------------------- |
| Environment | 3D voxel world             | Blockchain programs           |
| Actions     | Movement, crafting, combat | Transaction building          |
| Skills      | JavaScript game commands   | TypeScript web3.js code       |
| Rewards     | Items, achievements        | Program instruction discovery |
| Safety      | Game sandbox               | Local test validator          |

## Development

### Key Components

- `voyager_clone.py`: Main agent orchestration
- `surfpool_env.py`: Low-level Solana environment
- `agents/`: Curriculum, Action, and Critic agents
- `skill_manager/`: TypeScript skill storage and retrieval
- `skill_runner/`: Bun runtime for executing skills
- `prompts/`: LLM prompt templates
- `progress_tracker.py`: CSV logging system

### Important Constraints

1. **Single Transaction Per Skill**: Each skill can only execute ONE transaction
2. **No Airdrops**: Environment uses pre-funded accounts on local validator
3. **Serialized Output**: Skills must return base64-encoded transactions
4. **No CLI Access**: All operations must use web3.js programmatically

## 🤝 Contributing

1. **Improve Prompts**: Help curriculum agent suggest better tasks
2. **Add Program Mappings**: Update `data/program_ids.csv`
3. **Enhance Rewards**: Design rewards for specific DeFi operations
4. **Fix Bugs**: Check issues and submit PRs

## 📚 References

- [Voyager: An Open-Ended Embodied Agent](https://voyager.minedojo.org/)
- [Surfpool](https://surfpool.run)

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

**Ready to watch AI explore Solana?** Run the voyager agent and observe as it discovers how to use Solana!
