import os
import importlib.util
import logging
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
        # Must be sorted to ensure consistent skill order
        for filename in sorted(os.listdir(self.skill_root)):
            if filename.endswith(".py"):
                try:
                    self.register_from_file(os.path.join(self.skill_root, filename))
                except Exception as e:
                    logging.error(f"Failed to load skill from {filename}: {e}", exc_info=True)

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
            logging.info(f"Successfully loaded skill {skill_id} from {filepath}")
        else:
            raise ImportError(f"Skill file {filepath} must contain a callable 'execute_skill' function")

    def __getitem__(self, skill_id: int) -> Callable:
        if skill_id not in self.skills:
            raise KeyError(f"Skill with ID {skill_id} not found.")
        return self.skills[skill_id]

    def __contains__(self, skill_id: int) -> bool:
        return skill_id in self.skills

    def __len__(self) -> int:
        return len(self.skills)

    def load_skill_from_code(self, skill_code: str) -> Callable:
        """
        Dynamically loads a skill from a string of Python code without
        saving it to a file or registering it permanently.
        This is used for testing a proposed skill before it is saved.
        """
        # Use a temporary, unique name for the module
        temp_module_name = f"temp_skill_{os.urandom(4).hex()}"
        
        spec = importlib.util.spec_from_loader(temp_module_name, loader=None)
        skill_module = importlib.util.module_from_spec(spec)
        
        # Compile and execute the code in the module's namespace
        exec(skill_code, skill_module.__dict__)
        
        if hasattr(skill_module, "execute_skill") and callable(skill_module.execute_skill):
            return skill_module.execute_skill
        else:
            raise ImportError("Skill code must contain a callable function 'execute_skill'")

    def get_skill_docs(self) -> Dict[str, str]:
        """Returns a dictionary of skill names and their docstrings."""
        docs = {}
        for skill_id, skill_func in self.skills.items():
            skill_name = f"skill_{skill_id}"
            docstring = skill_func.__doc__.strip() if skill_func.__doc__ else "No docstring."
            docs[skill_name] = docstring
        return docs

    def get_all_skills(self) -> Dict[int, Callable]:
        return self.skills

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    dummy_skill_code = """
import asyncio
async def execute_skill(env):
    logging.info("Executing dummy skill.")
    await asyncio.sleep(0.1)
    return 1.0, "success"
"""
    skill_manager = SkillManager(skill_root="./temp_skills")
    
    skill_id = skill_manager.register(dummy_skill_code)
    logging.info(f"Registered new skill with ID: {skill_id}")
    
    retrieved_skill = skill_manager[skill_id]
    logging.info(f"Retrieved skill: {retrieved_skill}")
    
    assert skill_id in skill_manager
    
    import shutil
    shutil.rmtree("./temp_skills")
