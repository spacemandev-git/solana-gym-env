import subprocess
import json
import os
from typing import Any, Dict

class TypeScriptSkillManager:
    def __init__(self, skill_root="skills"):
        self.skills_dir = skill_root
        self.skills = {}
        self.next_skill_id = 0
        if not os.path.exists(self.skills_dir):
            os.makedirs(self.skills_dir)
        self._load_existing_skills()

    def _load_existing_skills(self):
        for filename in os.listdir(self.skills_dir):
            if filename.endswith(".ts"):
                skill_id = self.next_skill_id
                self.skills[skill_id] = os.path.join(self.skills_dir, filename)
                self.next_skill_id += 1
    
    def register(self, code: str) -> int:
        skill_id = self.next_skill_id
        file_path = os.path.join(self.skills_dir, f"skill_{skill_id}.ts")
        with open(file_path, "w") as f:
            f.write(code)
        self.skills[skill_id] = file_path
        self.next_skill_id += 1
        return skill_id

    def __len__(self):
        return len(self.skills)

    def get_skill_docs(self) -> Dict[str, str]:
        # For TypeScript skills, we might not have docstrings in the same way as Python.
        # For now, return the file paths as "docs".
        return {str(k): v for k, v in self.skills.items()}

    def save_skill(self, name: str, code: str) -> str:
        file_path = os.path.join(self.skills_dir, f"{name}.ts")
        with open(file_path, "w") as f:
            f.write(code)
        return file_path

    def execute_skill(self, file_path: str, timeout_ms: int = 10000) -> Dict[str, Any]:
        command = ["bun", "run", "skill_runner/runSkill.ts", file_path, str(timeout_ms)]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8'
            )
            # runSkill.ts now outputs a JSON object with reward, done_reason, tx_receipt_json_string
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            # If runSkill.ts exits with an error, it prints the JSON result to stderr
            try:
                # The error output might also be a JSON object if the skill itself failed gracefully
                return json.loads(e.stderr)
            except json.JSONDecodeError:
                # Fallback for unexpected stderr output
                return {"success": False, "reason": f"Skill runner error: {e.stderr}"}
        except FileNotFoundError:
            return {"success": False, "reason": "Bun command not found. Make sure Bun is installed and in your PATH."}
