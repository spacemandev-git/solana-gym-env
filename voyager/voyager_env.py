import gymnasium as gym
import asyncio
import os
import logging
import traceback
import json
import shutil
import base58
import base64
from typing import List, Set, Dict, Any
import pdb

from voyager.surfpool_env import SurfpoolEnv
from skill_manager.ts_skill_manager import TypeScriptSkillManager
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solders.transaction import Transaction

# --- Constants ---
CONFIG_MAX_LLM_SKILL_TRIES = 3

class SolanaVoyagerEnv(gym.Env):
    """
    High-level Gymnasium wrapper for a Solana agent, inspired by the Voyager paper.
    The agent can choose to either execute a known skill, propose a new skill
    via an LLM, or inspect its library of skills.
    """
    metadata = {"render_modes": ["human"]}
    
    SPECIALS = {"NEW_SKILL": 0, "INSPECT_LIB": 1, "FETCH_TX_EXAMPLES": 2}

    def __init__(self, max_steps: int = 128, skill_root: str = "./skills", protocols: List[str] = None):
        # Layer 0: The low-level Solana environment
        self.solana_env = SurfpoolEnv()
        self.observation_space = self.solana_env.observation_space

        # Layer 1: Voyager components
        self.skills = TypeScriptSkillManager(skill_root=skill_root)
        self.planner = EnhancedLLMPlanner(self.skills, agent_pubkey=str(self.solana_env.agent_keypair.pubkey()), protocols=protocols)

        self.max_steps = max_steps
        self.t = 0
        
        # Tracking for the voyager-style reward
        self.protocols_seen: Set[str] = set()
        # Track unique instructions per program for instruction-level rewards
        # Format: {program_id: {instruction_discriminator, ...}}
        self.program_instructions_seen: Dict[str, Set[str]] = {}
        
        # Separate RPC client for fetching transaction details (can use mainnet)
        # This allows us to fetch real transaction examples even in local surfpool
        self.tx_fetch_rpc_url = os.getenv("SOLANA_TX_FETCH_RPC_URL", "https://api.mainnet-beta.solana.com")
        self.tx_fetch_client = AsyncClient(self.tx_fetch_rpc_url)

    def _update_action_space(self):
        """Updates the action space to reflect the current number of skills."""
        self.action_space = gym.spaces.Dict({
            "action_type": gym.spaces.Discrete(len(self.skills) + len(self.SPECIALS)),
            "program_id": gym.spaces.Text(max_length=44)  # Base58 program address
        })

    async def _grow_skill(self):
        """
        Generates, tests, and registers a new skill with a retry mechanism.
        """
        if self.solana_env.last_observation is None:
            return 0.0, {"error": "Cannot grow skill without an observation"}

        last_error = None
        
        for i in range(CONFIG_MAX_LLM_SKILL_TRIES):
            logging.info(f"Attempt {i+1}/{CONFIG_MAX_LLM_SKILL_TRIES} to generate a skill...")
            
            skill_code = self.planner.propose(
                self.solana_env.last_observation,
                error=last_error
            )
            
            try:
                file_path = self.skills.save_skill("new_skill", skill_code)
                logging.info("Testing the newly generated skill...")
                agent_pubkey = str(self.solana_env.agent_keypair.pubkey())
                result = self.skills.execute_skill(file_path, agent_pubkey=agent_pubkey)
                logging.info(f"Skill test result: {result}")

                try:
                    serialized_tx = result['serialized_tx']
                    tx = Transaction.from_bytes(base64.b64decode(serialized_tx))
                except Exception as e:
                    logging.error(f"Error deserializing transaction: {e}")
                    last_error = f"Skill executed but failed. Reason: Error deserializing transaction: {e}"
                    continue

                skill_id = self.skills.register(skill_code)
                self._update_action_space()
                info = {"new_skill_id": skill_id, "status": "success"}
                return 0.0, info

            except Exception as e:
                pdb.set_trace()
                logging.error(f"Runtime error in generated skill: {e}")
                last_error = f"Runtime error: {traceback.format_exc()}"
        
        # If all tries fail
        info = {"status": "failed", "last_error": last_error}
        return 0.0, info

    def _summarise_library(self):
        """Returns a summary of the skill library."""
        # The "summary" could be a feature vector for the agent.
        # For now, we'll just return the number of skills.
        info = {"num_skills": len(self.skills)}
        # No reward for just looking.
        return 0.0, info

    async def _fetch_transaction_examples(self, program_id: str = None):
        """Fetches example transactions for a specific program."""
        if not program_id:
            return 0.0, {"error": "No program_id specified. Please provide a program_id."}
        
        logging.info(f"=== FETCH_TX_EXAMPLES called for program: {program_id} ===")
        program_name = KNOWN_PROGRAM_IDS.get(program_id, "Unknown")
        logging.info(f"Program name: {program_name}")
        
        try:
            # Fetch recent transactions from the tx fetch RPC (e.g., mainnet)
            # This allows us to get real transaction examples even in local surfpool
            logging.info(f"Fetching signatures from: {self.tx_fetch_rpc_url}")
            signatures = await self.tx_fetch_client.get_signatures_for_address(
                Pubkey.from_string(program_id),
                limit=10  # Limit to avoid too many requests
            )
            
            logging.info(f"Found {len(signatures.value)} signatures")
            
            examples = []
            # Only process first 3 transactions to avoid timeouts
            for i, sig_info in enumerate(signatures.value[:3]):
                try:
                    logging.info(f"Fetching transaction {i+1}/3: {sig_info.signature}")
                    tx = await self.tx_fetch_client.get_transaction(
                        sig_info.signature,
                        encoding="json",
                        max_supported_transaction_version=0
                    )
                    
                    if tx and tx.value:
                        logging.info(f"Successfully fetched transaction {i+1}")
                        # Extract ALL logs - no truncation
                        logs = tx.value.transaction.meta.log_messages or []
                        
                        # Parse ALL instructions (outer + inner) with proper indexing
                        instructions = []
                        
                        # Parse outer instructions
                        outer_ixs = tx.value.transaction.transaction.message.instructions or []
                        for outer_idx, ix in enumerate(outer_ixs):
                            instructions.append({
                                "id": str(outer_idx),
                                "program_id_index": ix.program_id_index,
                                "accounts": ix.accounts,
                                "data": ix.data,
                                "depth": 0
                            })
                    
                        # Parse inner instructions
                        inner_ixs = tx.value.transaction.meta.inner_instructions or []
                        for outer_idx, inner_group in enumerate(inner_ixs):
                            if inner_group and inner_group.instructions:
                                for inner_idx, inner_ix in enumerate(inner_group.instructions):
                                    instructions.append({
                                        "id": f"{outer_idx}.{inner_idx}",
                                        "program_id_index": inner_ix.program_id_index,
                                        "accounts": inner_ix.accounts,
                                        "data": inner_ix.data,
                                        "depth": 1
                                    })
                    
                        # Sort instructions by execution order
                        # This ensures "0", "0.0", "0.1", "1", "1.0", "2" ordering
                        instructions.sort(key=lambda x: [int(part) for part in x["id"].split(".")])
                        
                        examples.append({
                            "signature": str(sig_info.signature),
                            "success": tx.value.transaction.meta.err is None,
                            "error": tx.value.transaction.meta.err,
                            "logs": logs,  # ALL logs, no limit
                            "instructions": instructions,  # Sorted by execution order
                            "accounts": tx.value.transaction.transaction.message.account_keys,
                            "slot": tx.value.slot,
                        })
                except Exception as e:
                    logging.warning(f"Failed to fetch transaction {i+1}: {e}")
                    # Continue with next transaction
                    continue
            
            info = {
                "program_id": program_id,
                "program_name": KNOWN_PROGRAM_IDS.get(program_id, "Unknown"),
                "examples": examples,
                "count": len(examples),
                "status": "success"
            }
            
            # Store in environment for next skill generation
            self.last_fetched_examples = examples
            self.last_fetched_program = program_id
            
            logging.info(f"Successfully fetched {len(examples)} examples")
            if examples:
                # Log summary of what was found
                successful_txs = sum(1 for ex in examples if ex['success'])
                failed_txs = len(examples) - successful_txs
                logging.info(f"Transaction breakdown: {successful_txs} successful, {failed_txs} failed")
                
                # Log unique instruction patterns found
                unique_instructions = set()
                for ex in examples:
                    for ix in ex['instructions']:
                        unique_instructions.add(f"depth={ix['depth']}")
                logging.info(f"Instruction patterns found: {unique_instructions}")
                
                # Log first example's error (if any) for learning
                for ex in examples:
                    if ex.get('error'):
                        logging.info(f"Example error to learn from: {ex['error']}")
                        break
            
            logging.info("Examples stored for next skill generation")
            
            return 0.0, info  # No reward for fetching
            
        except Exception as e:
            logging.error(f"Error fetching transactions: {e}")
            logging.error(f"Exception type: {type(e)}")
            logging.error(f"Exception details: {repr(e)}")
            import traceback
            logging.error(f"Traceback: {traceback.format_exc()}")
            return 0.0, {"error": f"Failed to fetch transactions: {str(e)}"}

    async def _run_skill(self, skill_id: int):
        """
        Executes a skill, computes the reward, and handles exceptions.
        The protocol labeling happens regardless of skill success or failure.
        """
        if skill_id not in self.skills.skills:
            return 0.0, {"error": f"Skill {skill_id} not found."}

        file_path = self.skills.skills[skill_id]
        info = {}

        try:
            # Pass agent pubkey and latest blockhash to skill execution
            agent_pubkey = str(self.solana_env.agent_keypair.pubkey())
            
            # Fetch latest blockhash before skill execution
            blockhash_resp = await self.solana_env.client.get_latest_blockhash()
            latest_blockhash_str = str(blockhash_resp.value.blockhash)
            
            result = self.skills.execute_skill(file_path, agent_pubkey=agent_pubkey, latest_blockhash=latest_blockhash_str)
            
            # Get transaction data from skill result
            # Note: tx_receipt_json_string is now a base64-encoded unsigned transaction
            tx_data = result.get("serialized_tx")
        except Exception as e:
            logging.error(f"Error running skill {skill_id}: {e}")
            info["error"] = f"Exception in skill {skill_id}: {e}"
            tx_data = None
        
        # Process the base64 transaction if present
        receipt_str = None
        if tx_data:
            try:
                # Handle base64 transaction
                from solders.transaction import Transaction
                
                # Decode the base64 transaction
                tx_bytes = base64.b64decode(tx_data)
                tx = Transaction.from_bytes(tx_bytes)
                
                # Sign with agent keypair
                # Fetch the latest blockhash from surfpool
                blockhash_resp = await self.solana_env.client.get_latest_blockhash()
                latest_blockhash = blockhash_resp.value.blockhash
                pdb.set_trace()
                
                tx.sign([self.solana_env.agent_keypair], latest_blockhash)
                
                # Send transaction through surfpool
                # Note: surfpool_env.step returns (obs, tx_receipt, done, info)
                _, tx_receipt_json, _, send_info = await self.solana_env.step(tx)
                
                if tx_receipt_json:
                    receipt_str = tx_receipt_json
                    info["tx_sent"] = True
                elif send_info.get("possible_success"):
                    # Handle the parsing error case - transaction might have succeeded
                    info["tx_possibly_sent"] = True
                    info["tx_parse_error"] = send_info.get("error")
                    # For testing, treat as success with dummy receipt
                    receipt_str = '{"meta": {"err": null}, "transaction": {}}'
                else:
                    info["tx_error"] = send_info.get("error", "Unknown error")
                    
            except Exception as e:
                logging.error(f"Error processing base64 transaction: {e}")
                info["tx_processing_error"] = str(e)
                receipt_str = None
        
        # The final reward includes a voyager-style exploration bonus.
        # This requires the transaction receipt from the skill execution.
        return 0.0, info

    async def reset(self, *, seed=None, options=None):
        self.t = 0
        self.protocols_seen.clear()
        self.program_instructions_seen.clear()
        return await self.solana_env.reset(seed=seed, options=options)

    async def step(self, action):
        self.t += 1
        info = {}
        extrinsic_reward = 0.0
        
        # Extract action components
        action_type = action["action_type"]
        program_id = action.get("program_id", None)
        
        logging.info(f"--- Step {self.t}: Action type {action_type}, program_id: {program_id} ---")

        if action_type == self.SPECIALS["NEW_SKILL"]:
            extrinsic_reward, info = await self._grow_skill()
        elif action_type == self.SPECIALS["INSPECT_LIB"]:
            extrinsic_reward, info = self._summarise_library()
        elif action_type == self.SPECIALS["FETCH_TX_EXAMPLES"]:
            extrinsic_reward, info = await self._fetch_transaction_examples(program_id)
        else:
            # The action space is the number of specials + the number of skills.
            # So, the skill_id is the action minus the number of specials.
            skill_id = action_type - len(self.SPECIALS)
            logging.info(f"Executing skill ID: {skill_id}")
            extrinsic_reward, info = await self._run_skill(skill_id)

        terminated = self.t >= self.max_steps
        
        # The final observation is the last one from the low-level env
        obs = self.solana_env.last_observation
        
        return obs, extrinsic_reward, terminated, False, info

    def render(self, mode="human"):
        return self.solana_env.render(mode=mode)

    async def close(self):
        await self.solana_env.close()
        if hasattr(self, 'tx_fetch_client'):
            await self.tx_fetch_client.close()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Clean up skills from previous runs
    if os.path.exists("./skills"):
        shutil.rmtree("./skills")

    async def main():
        env = SolanaVoyagerEnv()
        obs, info = await env.reset()
        logging.info("--- Voyager Env Reset ---")
        logging.info(f"Initial observation keys: {obs.keys()}")

        # 1. First action: Create a new skill
        logging.info("\n--- Step 1: Creating a new skill ---")
        action = {"action_type": env.SPECIALS["NEW_SKILL"], "program_id": None}
        obs, reward, term, trunc, info = await env.step(action)
        logging.info(f"Action: NEW_SKILL, Reward: {reward}, Info: {info}")
        
        # 2. Second action: Execute the newly created skill
        logging.info("\n--- Step 2: Executing the new skill ---")
        if 'new_skill_id' in info:
            skill_to_run = info['new_skill_id']
            action = {"action_type": len(env.SPECIALS) + skill_to_run, "program_id": None}
            logging.info(f"\n--- Step 2: Executing skill {skill_to_run} with action {action} ---")
            obs, reward, term, trunc, info = await env.step(action)
            logging.info(f"Result of executing skill {skill_to_run} -> Reward: {reward}, Info: {info}")
        else:
            logging.warning("Could not execute new skill, as it was not created.")

        await env.close()

    asyncio.run(main())
