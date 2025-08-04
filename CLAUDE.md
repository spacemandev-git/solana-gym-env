# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Solana Gym is a reinforcement learning environment for teaching AI agents to interact with the Solana blockchain. It adapts the NVIDIA Voyager paper to work with Solana, using a local validator (surfpool) that simulates mainnet behavior. The project implements skill-based learning where agents generate and execute TypeScript code to explore blockchain protocols.

## Development Commands

### Python Environment

```bash
# All Python commands must use uv run
uv run python voyager/voyager_clone.py     # Run full Voyager agent
uv run python voyager/simple_explorer.py   # Run simplified explorer agent
uv run python voyager_env.py               # Test environment wrapper

# Testing
uv run python -m pytest tests/             # Run all tests
uv run python -m pytest tests/test_surfpool_env.py  # Run specific test

# Component testing
uv run python -c "from voyager.surfpool_env import SurfpoolEnv; env = SurfpoolEnv(); env.reset()"
```

### TypeScript Skill Runner

```bash
# Navigate to skill runner directory
cd voyager/skill_runner

# Install dependencies
bun install

# Run tests
bun test                                    # Run all tests
bun test tests/single_transaction.test.ts  # Run specific test

# Type check
bunx tsc --noEmit

# Lint
bunx eslint . --max-warnings 0

# Execute individual skill
bun run runSkill.ts path/to/skill.ts 30000
```

## Architecture Overview

The project implements a three-layer architecture for reinforcement learning on Solana:

### Layer 0: Environment Foundation

**SurfpoolEnv** (`voyager/surfpool_env.py`): Low-level Solana environment
- Manages surfpool subprocess (local Solana validator)
- Executes and simulates transactions
- Tracks wallet balances and blockchain state
- Calculates rewards based on protocol discovery

### Layer 1: Gymnasium Interface

**SolanaVoyagerEnv** (`voyager_env.py`): Standard RL environment wrapper
- Provides Gymnasium-compatible interface
- Skill-based action space (execute, generate, inspect)
- Integrates LLM for skill generation
- Fetches real mainnet transactions for learning examples

### Layer 2: Agent Systems

**VoyagerClone** (`voyager/voyager_clone.py`): Full Voyager implementation
- Curriculum agent: Task generation and progression
- Action agent: Code generation and execution
- Critic agent: Self-reflection and improvement

**SimpleExplorer** (`voyager/simple_explorer.py`): Streamlined agent (RECOMMENDED)
- Uses OpenAI function calling API (no regex parsing)
- Direct OpenRouter integration
- More robust than action.py's code extraction

### Supporting Components

**TypeScriptSkillManager** (`voyager/skill_manager/ts_skill_manager.py`)
- Skill registration and persistent storage
- Execution via isolated Bun subprocess
- ChromaDB vector database for skill retrieval
- Enforces single-transaction constraint

### Project Structure

```
/voyager/
├── agents/           # LLM-based agents (curriculum, action, critic)
├── prompts/          # Templates for LLM prompts
├── skill_manager/    # TypeScript skill storage and retrieval
├── skill_runner/     # Bun runtime for executing TypeScript skills
└── utils/            # Helper utilities

/data/program_ids.csv # Known Solana program mappings
/skills/              # Generated TypeScript skills (runtime)
/ckpt/                # Checkpoints for different runs (runtime)
/traces/              # Execution traces and rewards (runtime)
```

## Known Issues and Solutions

### action.py Code Parsing (AVOID)

The `voyager/agents/action.py` module uses fragile regex and Babel parsing to extract code from LLM responses. Common issues:

1. **babel_generator TypeError**: Fixed by checking for `babel_generator.default`
2. **Assertion syntax errors**: Fixed by using proper `and` operators
3. **Deprecated imports**: Updated to use `langchain_openai`

**Recommendation**: Use `simple_explorer.py` instead, which leverages OpenAI's function calling API for structured responses without regex parsing.

### SimpleExplorer vs Action.py

**SimpleExplorer advantages** (voyager/simple_explorer.py:127-197):
- Structured function calling API
- No regex or code parsing needed
- More reliable message handling
- Direct tool use pattern

**Action.py limitations** (voyager/agents/action.py:99-161):
- Fragile regex patterns for code extraction
- Babel parsing failures on complex code
- Hardcoded function signature expectations

## Critical Constraints

1. **Always use `uv run`** for Python commands - the project uses UV package manager
2. **One transaction per skill** - Enforced in voyager/skill_runner/runSkill.ts for safety
3. **Local validator only** - Uses surfpool (local Solana test validator) for safe testing
4. **Prefer SimpleExplorer** - More robust than action.py's regex-based parsing
5. **Mainnet data available** - Can fetch real transactions for learning examples

## Current Development Focus

From CONTRIBUTING.md:
- Improving `simple_explorer.py` agent performance
- Target: >25 rewards in 150 iterations (current: 9)
- Focus on tool calls and transaction decompilation
- Keep implementation simple without additional LLM calls