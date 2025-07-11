"""
Enhanced LLM Planner with better context and protocol awareness
"""

import os
import logging
import csv
from typing import Dict, Any, List, Optional
from planner import LLMPlanner
import pdb

# Load program IDs from CSV
KNOWN_PROGRAM_IDS = {}
csv_path = os.path.join(os.path.dirname(__file__), 'data', 'program_ids.csv')
if os.path.exists(csv_path):
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('program_address') and row.get('project_name'):
                # Format: "ProjectName - ProgramName"
                name = row['project_name']
                if row.get('program_name'):
                    name += f" - {row['program_name']}"
                KNOWN_PROGRAM_IDS[row['program_address']] = name

class EnhancedLLMPlanner(LLMPlanner):
    """
    Enhanced planner that provides much better context to the LLM including:
    - Available protocols with descriptions
    - Example transactions
    - Current agent state
    - Previous attempts and learnings
    """
    
    def __init__(self, skill_manager, model: str = None, agent_pubkey: str = None, protocols: List[str] = None):
        super().__init__(skill_manager, model)
        self.attempt_history = []
        self.discovered_protocols = set()
        self.agent_pubkey = agent_pubkey
        self.protocols = protocols
        
    def _generate_enhanced_prompt(
        self,
        observation: Dict[str, Any],
        objective: str,
        error: Optional[str] = None
    ) -> str:
        """Constructs an enhanced prompt with better context."""
        
        existing_skills = "\n".join(
            [f"- {self.skill_manager.skills[k]}" for k in self.skill_manager.skills.keys()]
        )
        
        # Format observation nicely
        wallet_balances = observation.get('wallet_balances', [])
        sol_balance = wallet_balances[0] if len(wallet_balances) > 0 else 0
        
        # List available protocols from CSV
        
        prompt = f"""
You are an expert Solana developer helping an AI agent explore the Solana blockchain.
The agent is learning to interact with DeFi protocols by creating TypeScript skills.

=== CURRENT STATE ===
Wallet Balance: {sol_balance:.4f} SOL
Block Height: {observation.get('block_height', [0])[0]}
Skills Created: {len(self.skill_manager.skills)}
Protocols Discovered: {len(self.discovered_protocols)}
Your Public Key: {self.agent_pubkey}

=== YOUR MISSION ===
{objective}

=== HOW TO INTERACT WITH PROGRAMS ===
To get credit for discovering a program, you need to create a transaction that executes
an instruction on that program. The transaction must include the program in its account keys.

Important clarification:
- SystemProgram.transfer() is an instruction that interacts with the System Program (11111111111111111111111111111111)
- A transfer TO a program address using SystemProgram.transfer() does NOT count as interacting with that program
- To interact with a specific program, you must create an instruction where that program is the programId

Examples:
- SystemProgram.transfer() → Interacts with System Program ✓
- Sending SOL to Jupiter's address via SystemProgram.transfer() → Still only interacts with System Program ✗
- Creating an instruction with programId: JUPITER_PROGRAM_ID → Interacts with Jupiter ✓

The environment detects programs by looking at the programId field of each instruction.

=== TYPESCRIPT SKILL TEMPLATE ===
```typescript
import {{ Transaction, SystemProgram, PublicKey, LAMPORTS_PER_SOL }} from '@solana/web3.js';

export async function executeSkill(): Promise<string> {{
    const tx = new Transaction();
    
    // EXAMPLE: Create an instruction that references a program
    const PROGRAM_ID = new PublicKey("PASTE_PROGRAM_ID_HERE"); // Pick from the list above
    

    // ================================
    // CREATE YOUR TRANSACTION HERE
    // ================================
    
    // Set transaction properties
    // Use a placeholder blockhash for now, it will be overridden by the environment automatically
    tx.recentBlockhash = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi";
    tx.feePayer = new PublicKey("{self.agent_pubkey}");
    
    // Serialize to base64
    const serializedTx = tx.serialize({{
        requireAllSignatures: false,
        verifySignatures: false
    }}).toString('base64');
    
    return serializedTx;
}}
```

=== IMPORTANT NOTES ===
1. Each skill must create exactly ONE unsigned transaction
2. The transaction will be signed and sent by the environment
3. Start simple - a transfer to a protocol address counts as interaction
4. Return the base64 encoded serialized transaction

=== EXISTING SKILLS ===
{existing_skills if existing_skills else "No skills yet - you're creating the first one!"}

"""
        
        # Add fetched examples if available
        if hasattr(self, 'last_fetched_examples') and self.last_fetched_examples:
            logging.info(f"=== Including {len(self.last_fetched_examples)} fetched examples in prompt ===")
            logging.info(f"Examples are for program: {self.last_fetched_program}")
            prompt += f"""
=== RECENTLY FETCHED TRANSACTION EXAMPLES ===
You fetched examples for program {self.last_fetched_program}. Study these logs carefully:

"""
            for idx, ex in enumerate(self.last_fetched_examples[:3]):
                prompt += f"""
Example {idx + 1}: Transaction {ex['signature'][:16]}... - {'SUCCESS' if ex['success'] else 'FAILED'}
Error: {ex.get('error', 'None')}

Instruction Structure (execution order):
"""
                for ix in ex['instructions'][:10]:  # Show first 10 instructions
                    prompt += f"  - Instruction {ix['id']} (depth={ix['depth']})\n"
                
                prompt += f"\nLogs:\n"
                # Show all logs but limit total characters
                logs_text = '\n'.join(ex['logs'])
                if len(logs_text) > 2000:
                    logs_text = logs_text[:2000] + "\n... (truncated)"
                prompt += logs_text + "\n\n"
            
            prompt += """
=== UNDERSTANDING TRANSACTION STRUCTURE ===
Instructions are shown in execution order:
- "0" = First outer instruction
- "0.0" = First inner instruction called by instruction 0
- "0.1" = Second inner instruction called by instruction 0
- "1" = Second outer instruction (executes AFTER all of 0's inner instructions)

Pay special attention to error messages in the logs!
"""
        
        if error:
            prompt += f"""
=== PREVIOUS ATTEMPT FAILED ===
Error: {error}

Common fixes:
- Make sure you import LAMPORTS_PER_SOL from '@solana/web3.js'
- Use valid protocol addresses from the list above
- Ensure amounts are in lamports (SOL * LAMPORTS_PER_SOL)
- Set both recentBlockhash and feePayer on the transaction

If you see "8 byte instruction identifier not provided", use Anchor:
```typescript
// Anchor programs need 8-byte discriminators at the start of instruction data
const discriminator = Buffer.from([/* 8 bytes specific to the instruction */]);
const data = Buffer.concat([discriminator, /* other instruction data */]);
```
"""
        
        prompt += """
=== YOUR TASK ===
Write a complete TypeScript skill that creates a transaction interacting with one of the undiscovered protocols.
Focus on the protocols above. Start simple - even a transfer counts!

Remember: Return ONLY the TypeScript code to complete the objective, no explanations.
"""
        
        return prompt
    
    def propose(
        self,
        observation: Dict[str, Any],
        objective: str = None,
        error: Optional[str] = None
    ) -> str:
        """Enhanced propose that uses better prompting."""
        
        # Use enhanced objective if none provided
        if not objective:
            undiscovered = []
            if not self.protocols:
                for prog_id, desc in KNOWN_PROGRAM_IDS.items():
                    protocol_name = desc.split(" - ")[0] if " - " in desc else desc
                    if protocol_name not in self.discovered_protocols:
                        undiscovered.append(prog_id)
            else:
                undiscovered = self.protocols
            
            if undiscovered:
                objective = f"Create a skill to interact with one of these undiscovered protocols: {', '.join(undiscovered)}"
                logging.info(f"Auto-generated objective: {objective}")
        
        # Use enhanced prompt
        prompt = self._generate_enhanced_prompt(observation, objective, error)
        pdb.set_trace()
        
        logging.info(f"EnhancedPlanner: Generating skill for objective: {objective}")
        skill_code = self._call_openrouter(prompt)
        
        if skill_code:
            # Extract code from markdown if present
            if "```typescript" in skill_code:
                start = skill_code.find("```typescript") + len("```typescript")
                end = skill_code.find("```", start)
                if end != -1:
                    skill_code = skill_code[start:end].strip()
            elif "```" in skill_code:
                start = skill_code.find("```") + len("```")
                end = skill_code.find("```", start)
                if end != -1:
                    skill_code = skill_code[start:end].strip()
            
            # Track attempt
            self.attempt_history.append({
                'objective': objective,
                'success': error is None,
                'error': error
            })
            
            return skill_code
        else:
            # Return a better dummy skill that actually interacts with a protocol
            return self._get_protocol_interaction_skill()
    
    def _get_protocol_interaction_skill(self) -> str:
        """Returns a dummy skill that actually interacts with a protocol."""
        # Pick a protocol to interact with
        protocols = [
            ("JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB", "jupiter"),
            ("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", "raydium"),
            ("whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc", "orca"),
        ]
        
        # Pick first undiscovered or default to Jupiter
        for address, name in protocols:
            if name not in self.discovered_protocols:
                return self._create_interaction_skill(address, name)
        
        return self._create_interaction_skill(protocols[0][0], protocols[0][1])
    
    def _create_interaction_skill(self, protocol_address: str, protocol_name: str) -> str:
        """Creates a skill that interacts with a specific protocol."""
        return f"""
import {{ Transaction, PublicKey }} from '@solana/web3.js';

export async function executeSkill(): Promise<string> {{
    // Interact with {protocol_name.title()} program
    const wallet = env.getWallet();
    const tx = new Transaction();
    
    // Create an instruction for the target program
    const PROGRAM_ID = new PublicKey("{protocol_address}");
    
    // Create a minimal instruction that references the program
    // This will trigger protocol discovery
    const instruction = {{
        programId: PROGRAM_ID,
        keys: [
            {{ pubkey: new PublicKey(wallet.publicKey), isSigner: true, isWritable: true }}
        ],
        data: Buffer.from([]) // Empty data - would normally contain instruction data
    }};
    
    tx.add(instruction);
    
    // Set required transaction fields
    tx.recentBlockhash = env.getRecentBlockhash();
    tx.feePayer = new PublicKey(wallet.publicKey);
    
    // Serialize the complete unsigned transaction to base64
    const serializedTx = tx.serialize({{
        requireAllSignatures: false,
        verifySignatures: false
    }}).toString('base64');
    
    return [1.0, "interacted_with_{protocol_name}", serializedTx];
}}
"""
    
    def update_discovered(self, protocols: list):
        """Update the set of discovered protocols."""
        self.discovered_protocols.update(protocols)