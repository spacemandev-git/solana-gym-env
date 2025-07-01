import os
import logging
from openai import OpenAI
from skill_manager.ts_skill_manager import TypeScriptSkillManager
from typing import Dict, Any, Optional

# It's good practice to use environment variables for API keys
# Ensure you have OPENAI_API_KEY set in your environment
# client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
client = None # Disabled for now

class LLMPlanner:
    """
    This class interfaces with a large language model (LLM) to generate
    TypeScript code for new skills based on the current environment observation,
    existing skills, and a high-level objective.
    """
    def __init__(self, skill_manager: TypeScriptSkillManager, model: str = "gpt-4-1106-preview"):
        self.skill_manager = skill_manager
        self.model = model

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

The function must return a Promise that resolves to an object with a `reason` property: `{{ reason: string; }}`.
- `reason`: A short string explaining the outcome (e.g., "success", "insufficient_funds").

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
"""
        return prompt

    def propose(
        self,
        observation: Dict[str, Any],
        objective: str = "Interact with a new protocol or perform a useful action.",
        error: Optional[str] = None
    ) -> str:
        """
        Proposes a new skill by querying the LLM.
        """
        if not client:
            logging.warning("LLMPlanner: OpenAI client not configured. Returning a dummy skill.")
            return self._get_dummy_skill()

        prompt = self._generate_prompt(observation, objective, error)
        
        try:
            logging.info("LLMPlanner: Querying LLM for a new skill...")
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            
            skill_code = response.choices[0].message.content
            if skill_code.startswith("```typescript"):
                skill_code = skill_code[len("```typescript"):].strip()
            if skill_code.endswith("```"):
                skill_code = skill_code[:-len("```")].strip()
                
            logging.info("LLMPlanner: Received skill proposal from LLM.")
            return skill_code
            
        except Exception as e:
            logging.error(f"LLMPlanner: Error querying LLM: {e}", exc_info=True)
            return self._get_dummy_skill()

    def _get_dummy_skill(self) -> str:
        """Returns a hardcoded dummy skill for testing without an LLM."""
        return """
export async function executeSkill(env: any): Promise<{ reason: string; }> {
    // This is a dummy skill that simulates a simple transfer.
    return { reason: "simulated_success" };
}
"""

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    skill_manager = TypeScriptSkillManager(skills_dir="./temp_skills_planner")
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
