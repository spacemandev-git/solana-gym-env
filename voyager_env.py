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

from surfpool_env import SurfpoolEnv
from skill_manager.ts_skill_manager import TypeScriptSkillManager
from enhanced_planner import EnhancedLLMPlanner
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solders.transaction import Transaction

# --- Constants ---
CONFIG_MAX_LLM_SKILL_TRIES = 3

import csv

KNOWN_PROGRAM_IDS: Dict[str, str] = {}

def load_program_ids_from_csv(file_path: str):
    global KNOWN_PROGRAM_IDS
    KNOWN_PROGRAM_IDS = {}
    if not os.path.exists(file_path) or os.stat(file_path).st_size == 0:
        raise FileNotFoundError(f"Program IDs CSV file not found or is empty: {file_path}")
    with open(file_path, mode='r', newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if 'program_address' in row and 'project_name' in row:
                KNOWN_PROGRAM_IDS[row['program_address']] = row['project_name']

# Load program IDs at startup
try:
    load_program_ids_from_csv('data/program_ids.csv')
except FileNotFoundError as e:
    logging.error(f"Failed to load program IDs: {e}")
    # Depending on criticality, you might want to exit or use a fallback
    # For now, we'll let it proceed with an empty dict if the file is missing/empty
except Exception as e:
    logging.error(f"An unexpected error occurred while loading program IDs: {e}")


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

        # RL view of the world - Dict action space
        self.action_space = gym.spaces.Dict({
            "action_type": gym.spaces.Discrete(len(self.skills) + len(self.SPECIALS)),
            "program_id": gym.spaces.Text(max_length=44)  # Base58 program address
        })
        
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

    def _protocol_labeler(self, tx_receipt: Dict[str, Any]) -> list[str]:
        """
        Identifies ALL protocols from a transaction receipt by checking for known
        program IDs in the transaction's instructions. This check is performed
        regardless of whether the transaction succeeded or failed.
        Returns a list of protocol names found in the transaction.
        """
        if not tx_receipt:
            return []

        protocols_found = []
        seen_protocols = set()  # To avoid duplicates

        try:
            # The transaction object contains account keys as strings
            account_keys = tx_receipt.get("transaction", {}).get("message", {}).get("accountKeys", [])
            if not account_keys:
                return []

            # The instructions contain indices into the account_keys list
            instructions = tx_receipt.get("transaction", {}).get("message", {}).get("instructions", [])

            for instruction in instructions:
                program_id_index = instruction.get("programIdIndex")
                if program_id_index is not None and program_id_index < len(account_keys):
                    program_id_str = account_keys[program_id_index]
                    if program_id_str in KNOWN_PROGRAM_IDS:
                        protocol = KNOWN_PROGRAM_IDS[program_id_str]
                        if protocol not in seen_protocols:
                            seen_protocols.add(protocol)
                            protocols_found.append(protocol)
            
            # Also check all account keys in case some are program IDs not in instructions
            for key in account_keys:
                if key in KNOWN_PROGRAM_IDS:
                    protocol = KNOWN_PROGRAM_IDS[key]
                    if protocol not in seen_protocols:
                        seen_protocols.add(protocol)
                        protocols_found.append(protocol)
        except Exception as e:
            logging.error(f"Error during protocol labeling: {e}")

        return protocols_found

    def _extract_instruction_discriminators(self, tx_receipt: Dict[str, Any]) -> Dict[str, Set[str]]:
        """
        Extracts unique instruction discriminators (first 8 bytes) for each program
        from a transaction receipt. Returns a dict mapping program_id to set of discriminators.
        """
        if not tx_receipt:
            return {}
        
        program_discriminators = {}
        
        try:
            # Get account keys
            account_keys = tx_receipt.get("transaction", {}).get("message", {}).get("accountKeys", [])
            if not account_keys:
                return {}
            
            # Process all instructions
            instructions = tx_receipt.get("transaction", {}).get("message", {}).get("instructions", [])
            
            for instruction in instructions:
                program_id_index = instruction.get("programIdIndex")
                if program_id_index is not None and program_id_index < len(account_keys):
                    program_id = account_keys[program_id_index]
                    
                    # Get instruction data (base64 encoded when encoding="json")
                    data_str = instruction.get("data", "")
                    if data_str and len(data_str) > 0:
                        try:
                            # Try base64 first (for JSON encoding)
                            try:
                                import base64
                                data_bytes = base64.b64decode(data_str)
                            except:
                                # Fall back to base58 (for base58 encoding)
                                data_bytes = base58.b58decode(data_str)
                            
                            if len(data_bytes) > 0:
                                # Use first byte as discriminator (could extend to 8 bytes for Anchor)
                                discriminator = data_bytes[0:1].hex()
                                
                                if program_id not in program_discriminators:
                                    program_discriminators[program_id] = set()
                                program_discriminators[program_id].add(discriminator)
                        except Exception as e:
                            logging.debug(f"Failed to decode instruction data: {e}")
            
            # Also process inner instructions if available
            inner_instructions = tx_receipt.get("meta", {}).get("innerInstructions", [])
            for inner_group in inner_instructions:
                if isinstance(inner_group, dict) and "instructions" in inner_group:
                    for inner_ix in inner_group["instructions"]:
                        program_id_index = inner_ix.get("programIdIndex")
                        if program_id_index is not None and program_id_index < len(account_keys):
                            program_id = account_keys[program_id_index]
                            
                            data_str = inner_ix.get("data", "")
                            if data_str and len(data_str) > 0:
                                try:
                                    # Try base64 first (for JSON encoding)
                                    try:
                                        import base64
                                        data_bytes = base64.b64decode(data_str)
                                    except:
                                        # Fall back to base58 (for base58 encoding)
                                        data_bytes = base58.b58decode(data_str)
                                    
                                    if len(data_bytes) > 0:
                                        discriminator = data_bytes[0:1].hex()
                                        
                                        if program_id not in program_discriminators:
                                            program_discriminators[program_id] = set()
                                        program_discriminators[program_id].add(discriminator)
                                except Exception as e:
                                    logging.debug(f"Failed to decode inner instruction data: {e}")
                    
        except Exception as e:
            logging.error(f"Error extracting instruction discriminators: {e}")
        
        return program_discriminators

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
        base_reward = 0.0
        info = {}

        try:
            # Pass agent pubkey and latest blockhash to skill execution
            agent_pubkey = str(self.solana_env.agent_keypair.pubkey())
            
            # Fetch latest blockhash before skill execution
            blockhash_resp = await self.solana_env.client.get_latest_blockhash()
            latest_blockhash_str = str(blockhash_resp.value.blockhash)
            
            result = self.skills.execute_skill(file_path, agent_pubkey=agent_pubkey, latest_blockhash=latest_blockhash_str)
            base_reward = 0.0 # No base reward for failed skill execution
            
            # Get transaction data from skill result
            # Note: tx_receipt_json_string is now a base64-encoded unsigned transaction
            tx_data = result.get("serialized_tx")
        except Exception as e:
            logging.error(f"Error running skill {skill_id}: {e}")
            info["error"] = f"Exception in skill {skill_id}: {e}"
            base_reward = 0.0 # Ensure reward is 0 on failure
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
        final_reward = base_reward
        if receipt_str:
            receipt = json.loads(receipt_str)
            protocols = self._protocol_labeler(receipt)
            if protocols:
                info["protocols_interacted"] = protocols
                # Add bonus for each new protocol
                for proto in protocols:
                    if proto not in self.protocols_seen:
                        logging.info(f"New protocol interaction: {proto}! Adding exploration bonus.")
                        self.protocols_seen.add(proto)
                        final_reward += 1.0
                    else:
                        logging.info(f"Already interacted with {proto}. No bonus.")
            
            # Extract and reward new instruction discriminators
            program_instructions = self._extract_instruction_discriminators(receipt)
            if program_instructions:
                info["program_instructions"] = {}
                for program_id, discriminators in program_instructions.items():
                    # Initialize tracking for this program if needed
                    if program_id not in self.program_instructions_seen:
                        self.program_instructions_seen[program_id] = set()
                    
                    # Check for new instructions
                    new_instructions = discriminators - self.program_instructions_seen[program_id]
                    if new_instructions:
                        program_name = KNOWN_PROGRAM_IDS.get(program_id, program_id[:8] + "...")
                        logging.info(f"New instructions discovered for {program_name}: {new_instructions}")
                        
                        # Add instruction-level rewards
                        for new_instr in new_instructions:
                            self.program_instructions_seen[program_id].add(new_instr)
                            final_reward += 0.5  # 0.5 reward per new instruction
                            logging.info(f"  +0.5 reward for new instruction: {new_instr}")
                        
                        info["program_instructions"][program_id] = {
                            "new": list(new_instructions),
                            "total_seen": len(self.program_instructions_seen[program_id])
                        }
        
        return final_reward, info

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
