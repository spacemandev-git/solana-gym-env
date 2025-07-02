import os
import logging
import json
import requests
from dotenv import load_dotenv
from skill_manager.ts_skill_manager import TypeScriptSkillManager
from typing import Dict, Any, Optional

# Load environment variables
load_dotenv()

class LLMPlanner:
    """
    This class interfaces with OpenRouter LLM API to generate
    TypeScript code for new skills based on the current environment observation,
    existing skills, and a high-level objective.
    """
    def __init__(self, skill_manager: TypeScriptSkillManager, model: str = None):
        self.skill_manager = skill_manager
        self.model = model or os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        
        if not self.api_key:
            logging.warning("LLMPlanner: OPENROUTER_API_KEY not found in environment. Skill generation will use dummy skills.")

    def _generate_prompt(
        self,
        observation: Dict[str, Any],
        objective: str,
        error: Optional[str] = None
    ) -> str:
        """Constructs the prompt for the LLM."""
        
        existing_skills = "\n".join(
            [f"- {self.skill_manager.skills[k]}" for k in self.skill_manager.skills.keys()]
        )
        
        prompt = f"""
You are an expert Solana developer and an AI agent inside a reinforcement learning environment.
Your goal is to write a TypeScript module that exports a new "skill" for the agent to perform.

The module must contain a single asynchronous function `executeSkill(env: any)`.
This function takes the low-level Solana environment `env` as input.

The function must return a Promise that resolves to a tuple: `[number, string, string | null]`.
- First element: A number indicating the reward (e.g., 1.0 for success, 0.0 for failure).
- Second element: A short string explaining the outcome (e.g., "success", "insufficient_funds").
- Third element: A base64-encoded string of the unsigned transaction, or null if no transaction was made.

The env object provides:
- `env.getWallet()`: Returns wallet information including balances and public key
- `env.getRecentBlockhash()`: Returns a recent blockhash for the transaction
- Access to Solana web3.js library for building transactions

You should:
1. Import necessary Solana libraries (Transaction, SystemProgram, etc.)
2. Build a complete unsigned transaction with all instructions
3. Set recentBlockhash and feePayer on the transaction
4. Serialize it to base64 string
5. Return the base64 string

**CRITICAL CONSTRAINTS:**
1. Each skill MUST create exactly ONE unsigned transaction
2. The transaction should be serialized to base64 format before returning
3. Do NOT sign or send the transaction - the environment will handle that
4. If you need multiple operations, add multiple instructions to the same transaction
5. If operations cannot be combined in one transaction, create SEPARATE skills

Example structure:
```typescript
import {{ Transaction, SystemProgram, PublicKey }} from '@solana/web3.js';

export async function executeSkill(env: any): Promise<[number, string, string | null]> {{
    const wallet = env.getWallet();
    const tx = new Transaction();
    
    // Add your instructions
    tx.add(SystemProgram.transfer({{
        fromPubkey: new PublicKey(wallet.publicKey),
        toPubkey: new PublicKey("..."),
        lamports: 1000000
    }}));
    
    // Set required transaction fields
    tx.recentBlockhash = env.getRecentBlockhash();
    tx.feePayer = new PublicKey(wallet.publicKey);
    
    // Serialize the complete unsigned transaction to base64
    const serializedTx = tx.serialize({{
        requireAllSignatures: false,
        verifySignatures: false
    }}).toString('base64');
    
    return [1.0, "success", serializedTx];
}}
```

**Environment Observation:**
```json
{observation}
```

**High-Level Objective:**
{objective}

**Existing Skills:**
{existing_skills if existing_skills else "No skills yet."}
"""
        if error:
            prompt += f"""
**Previous Attempt Failed:**
The last generated skill failed with the following error. Please analyze the error and write a corrected version of the skill.
```
{error}
```
"""
        prompt += """
**Your Task:**
Write the complete TypeScript code for the `executeSkill` function.
Do not include any other code or explanations outside of the TypeScript code block.
The code should be self-contained and ready to be executed.
Focus on interacting with Solana protocols like Jupiter, Meteora, Raydium, etc.
"""
        return prompt

    def _call_openrouter(self, prompt: str) -> Optional[str]:
        """Makes a request to the OpenRouter API."""
        if not self.api_key:
            return None
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        site_url = os.environ.get("OPENROUTER_SITE_URL", "")
        app_name = os.environ.get("OPENROUTER_APP_NAME", "solana-gym")
        
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name
        
        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }
        
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data
            )
            response.raise_for_status()
            
            result = response.json()
            return result['choices'][0]['message']['content']
            
        except requests.exceptions.RequestException as e:
            logging.error(f"LLMPlanner: Error calling OpenRouter API: {e}")
            if hasattr(e.response, 'text'):
                logging.error(f"Response: {e.response.text}")
            return None
        except (KeyError, json.JSONDecodeError) as e:
            logging.error(f"LLMPlanner: Error parsing OpenRouter response: {e}")
            return None

    def propose(
        self,
        observation: Dict[str, Any],
        objective: str = "Interact with a new protocol or perform a useful action.",
        error: Optional[str] = None
    ) -> str:
        """
        Proposes a new skill by querying the LLM.
        """
        prompt = self._generate_prompt(observation, objective, error)
        
        logging.info(f"LLMPlanner: Querying {self.model} for a new skill...")
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
                    
            logging.info("LLMPlanner: Received skill proposal from LLM.")
            return skill_code
        else:
            logging.warning("LLMPlanner: Failed to get response from OpenRouter. Returning a dummy skill.")
            return self._get_dummy_skill()

    def _get_dummy_skill(self) -> str:
        """Returns a hardcoded dummy skill for testing without an LLM."""
        return """
import { Transaction, SystemProgram, PublicKey } from '@solana/web3.js';

export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    // This is a dummy skill that creates an unsigned transaction
    const wallet = env.getWallet();
    const tx = new Transaction();
    
    // Add a simple transfer instruction (1 lamport to system program)
    tx.add(SystemProgram.transfer({
        fromPubkey: new PublicKey(wallet.publicKey),
        toPubkey: SystemProgram.programId,
        lamports: 1
    }));
    
    // Set required transaction fields
    tx.recentBlockhash = env.getRecentBlockhash();
    tx.feePayer = new PublicKey(wallet.publicKey);
    
    // Serialize the complete unsigned transaction to base64
    const serializedTx = tx.serialize({
        requireAllSignatures: false,
        verifySignatures: false
    }).toString('base64');
    
    return [1.0, "created_transfer_tx", serializedTx];
}
"""

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    skill_manager = TypeScriptSkillManager(skill_root="./temp_skills_planner")
    planner = LLMPlanner(skill_manager)
    
    mock_observation = {"wallet_balances": [1.0], "block_height": [100]}
    
    new_skill_code = planner.propose(mock_observation)
    logging.info("\n--- Proposed Skill Code ---")
    logging.info(new_skill_code)
    
    skill_id = skill_manager.register(new_skill_code)
    logging.info(f"\nRegistered proposed skill with ID: {skill_id}")
    
    assert skill_id in skill_manager.skills
    logging.info("Skill successfully registered in SkillManager.")
    
    import shutil
    shutil.rmtree("./temp_skills_planner")