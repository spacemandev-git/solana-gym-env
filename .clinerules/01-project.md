# Solana Voyager Gym — Core Migration Rules

_Last updated: 2025-07-01_

## 1 Language & Runtime

- **All new skills MUST be written in TypeScript** and `export async function executeSkill(env)`.  
  ⤷ No Python skills may be merged after **Week 2** of the migration timeline.

- **Bun v1.x is the only approved runtime**.  
  ⤷ Compilation budget ≤ 5 s; execution budget ≤ 10 s (enforced by `runSkill.ts`).

- Deprecate the Python `SkillManager` after the TS manager passes CI; keep legacy Python skills only in `skills/legacy_py/` for reference.

## 2 Subsystem Responsibilities

| Owner Box           | Mandatory Scope                                       | Forbidden Scope                        |
| ------------------- | ----------------------------------------------------- | -------------------------------------- |
| **Sandbox Service** | REST `/start /ready /shutdown`, Surfpool lifecycle    | Running LLM or skill code              |
| **Gym Adapter**     | Convert RPC → tensor obs; enforce 15 s step timeout   | Skill compilation/execution            |
| **Skill Runner**    | Compile & run TS (`runSkill <file> <timeoutMs>`)      | Managing validator or RPC              |
| **RAG Store**       | `put()` & `query()` over NumPy vectors (`vecs.npy`)   | Network DBs (pgvector, Weaviate, etc.) |
| **Planner**         | Build prompt, 4-try repair loop, emit TS              | Direct RPC or filesystem calls         |
| **Voyager Wrapper** | Discrete actions, reward shaping, CSV program-ID load | Embedding generation                   |

## 3 Protocol Labeling

- Load `data/program_ids.csv` at runtime; **do not hard-code program IDs** in source files.
- Fail CI if the CSV is missing or empty.

## 3-b Protocol Labeling (critical bug-fix)

- The labeler **MUST scan every instruction in a transaction receipt** and collect _all_ program-IDs present,
  not just the first match.
- For each program-ID found:
  • map → project name via `data/program_ids.csv`  
   • if that project has **not** been seen earlier in the _current episode_, add +1 exploration bonus.
- A single transaction can therefore yield **multiple +1 bonuses** when it legitimately touches multiple new
  programs (max one bonus per unseen program).
- CI test will fail if `_protocol_labeler()` stops after the first match or ignores additional IDs.

> Rationale: current implementation exits early; unit-tests expect detection of multiple new protocols.

## 4 RAG Vector Store

- Use **NumPy in-memory matrix** for embeddings; persist to `rag_store/vecs.npy`.
- `query()` must return top-k via brute-force cosine; no external services.

## 5 Testing & CI

- PR **must** pass:

  - `pytest` (Python)
  - `bun test` & `bunx eslint . --max-warnings 0` (TS)
  - End-to-end dummy episode: reward > 0

- Any PR adding a new skill **must** include:
  - One-paragraph description ≤ 80 tokens
  - Unit test in `tests/ts/`

# Additional Notes

- Never touch core data uploaded in CSVs. Attempt to handle quirks & missing data via post processing. If absolutely needed, request the user to modify the CSV.
