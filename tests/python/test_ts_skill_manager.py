import unittest
import os
from skill_manager.ts_skill_manager import TypeScriptSkillManager

class TestTypeScriptSkillManager(unittest.TestCase):
    def setUp(self):
        self.manager = TypeScriptSkillManager(skill_root="test_skills")

    def tearDown(self):
        if os.path.exists(self.manager.skills_dir):
            for f in os.listdir(self.manager.skills_dir):
                os.remove(os.path.join(self.manager.skills_dir, f))
            os.rmdir(self.manager.skills_dir)

    def test_save_and_execute_skill(self):
        skill_code = """
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    return [1.0, "Test skill executed successfully.", null];
}
"""
        file_path = self.manager.save_skill("test_skill", skill_code)
        self.assertTrue(os.path.exists(file_path))

        result = self.manager.execute_skill(
            file_path,
            timeout_ms=5000,
            agent_pubkey="11111111111111111111111111111111",
            latest_blockhash="4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["done_reason"], "Test skill executed successfully.")

if __name__ == "__main__":
    unittest.main()
