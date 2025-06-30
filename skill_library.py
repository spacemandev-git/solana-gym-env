import os
import importlib.util
from typing import Callable, Dict, Any

class SkillManager:
    """
    Manages a collection of skills, which are dynamically loaded Python scripts.
    Each skill is a callable that takes the environment as input and executes
    a series of actions.
    """
    def __init__(self, skill_root: str = "./skills"):
        self.skill_root = skill_root
        self.skills: Dict[int, Callable] = {}
        self.next_skill_id = 0
        
        if not os.path.exists(skill_root):
            os.makedirs(skill_root)
        else:
            self._load_skills_from_disk()

    def _load_skills_from_disk(self):
        """Loads all .py files from the skill_root directory."""
        for filename in os.listdir(self.skill_root):
            if filename.endswith(".py"):
                try:
                    self.register_from_file(os.path.join(self.skill_root, filename))
                except Exception as e:
                    print(f"Failed to load skill from {filename}: {e}")

    def register(self, skill_code: str) -> int:
        """
        Registers a new skill from a string of Python code.
        Saves it to a file and loads it into the manager.
        """
        skill_id = self.next_skill_id
        filepath = os.path.join(self.skill_root, f"skill_{skill_id}.py")
        
        with open(filepath, "w") as f:
            f.write(skill_code)
            
        self.register_from_file(filepath)
        return skill_id

    def register_from_file(self, filepath: str):
        """
        Loads a skill from a Python file and adds it to the skill registry.
        The file is expected to contain a function named 'execute_skill'.
        """
        skill_id = self.next_skill_id
        
        # Dynamically import the module
        spec = importlib.util.spec_from_file_location(f"skill_{skill_id}", filepath)
        skill_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(skill_module)
        
        # The skill must be a function called 'execute_skill'
        if hasattr(skill_module, "execute_skill") and callable(skill_module.execute_skill):
            self.skills[skill_id] = skill_module.execute_skill
            self.next_skill_id += 1
            print(f"Successfully loaded skill {skill_id} from {filepath}")
        else:
            raise ImportError(f"Skill file {filepath} must contain a callable function 'execute_skill'")

    def __getitem__(self, skill_id: int) -> Callable:
        if skill_id not in self.skills:
            raise KeyError(f"Skill with ID {skill_id} not found.")
        return self.skills[skill_id]

    def __contains__(self, skill_id: int) -> bool:
        return skill_id in self.skills

    def __len__(self) -> int:
        return len(self.skills)

    def get_all_skills(self) -> Dict[int, Callable]:
        return self.skills

if __name__ == '__main__':
    # Example Usage
    # 1. Create a dummy skill
    dummy_skill_code = """
import asyncio
from surfpool_env import SurfpoolEnv
from solders.keypair import Keypair
from solders.system_program import transfer, TransferParams
from solders.message import MessageV0
from solders.transaction import VersionedTransaction

async def execute_skill(env: SurfpoolEnv):
    print("Executing dummy skill: sending a simple transfer.")
    
    # The skill logic uses the environment to interact with the chain
    recipient = Keypair().pubkey()
    instruction = transfer(
        TransferParams(
            from_pubkey=env.agent_keypair.pubkey(),
            to_pubkey=recipient,
            lamports=500
        )
    )
    
    latest_blockhash = await env.client.get_latest_blockhash()
    message = MessageV0.try_compile(
        payer=env.agent_keypair.pubkey(),
        instructions=[instruction],
        address_lookup_table_accounts=[],
        recent_blockhash=latest_blockhash.value.blockhash
    )
    tx = VersionedTransaction(message, [env.agent_keypair])
    
    # Use the env's step function to execute the transaction
    obs, receipt, terminated, info = await env.step(tx, [env.agent_keypair])
    
    print(f"Dummy skill execution result: {info}")
    
    # The skill should return the outcome
    if 'error' in info:
        return 0, "error" # Return reward and done reason
    else:
        return 1, "success"
"""
    # 2. Initialize the SkillManager
    skill_manager = SkillManager(skill_root="./temp_skills")
    
    # 3. Register the new skill
    skill_id = skill_manager.register(dummy_skill_code)
    print(f"Registered new skill with ID: {skill_id}")
    
    # 4. Retrieve and inspect the skill
    retrieved_skill = skill_manager[skill_id]
    print(f"Retrieved skill: {retrieved_skill}")
    
    # Clean up the dummy skill and directory
    import shutil
    shutil.rmtree("./temp_skills")
