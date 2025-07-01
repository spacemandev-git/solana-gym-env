import unittest
import os
from skill_manager.ts_skill_manager import TypeScriptSkillManager

class TestTypeScriptSkillManager(unittest.TestCase):
    def setUp(self):
        self.manager = TypeScriptSkillManager(skills_dir="test_skills")

    def tearDown(self):
        if os.path.exists(self.manager.skills_dir):
            for f in os.listdir(self.manager.skills_dir):
                os.remove(os.path.join(self.manager.skills_dir, f))
            os.rmdir(self.manager.skills_dir)

    def test_save_and_execute_skill(self):
        skill_code = """
export async function executeSkill(env: any): Promise<{ reason: string; }> {
    return { reason: "Test skill executed successfully." };
}
"""
        file_path = self.manager.save_skill("test_skill", skill_code)
        self.assertTrue(os.path.exists(file_path))

        result = self.manager.execute_skill(file_path)
        self.assertTrue(result["success"])
        self.assertEqual(result["reason"], "Test skill executed successfully.")

if __name__ == "__main__":
    unittest.main()
