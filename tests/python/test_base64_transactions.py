#!/usr/bin/env python3
"""Test base64 transaction serialization with TypeScript skills."""

import unittest
import json
import base64
import os
from skill_manager.ts_skill_manager import TypeScriptSkillManager


class TestBase64Transactions(unittest.TestCase):
    """Test that skills properly create base64-encoded transactions."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures path."""
        cls.fixtures_path = os.path.join(
            os.path.dirname(__file__), 
            "..", "..", "skill_runner", "tests", "fixtures"
        )
    
    def test_basic_transfer_skill(self):
        """Test that a basic transfer skill returns valid base64 transaction."""
        skill_path = os.path.join(self.fixtures_path, "skill_base64_transfer.ts")
        
        # Use the skill manager to execute
        skill_manager = TypeScriptSkillManager()
        result = skill_manager.execute_skill(skill_path)
        
        # Verify execution succeeded
        self.assertTrue(result['success'])
        self.assertEqual(result['reward'], 1.0)
        self.assertEqual(result['done_reason'], 'created_transfer_tx')
        
        # Verify we got a base64 transaction
        tx_base64 = result['tx_receipt_json_string']
        self.assertIsNotNone(tx_base64)
        self.assertIsInstance(tx_base64, str)
        
        # Decode and verify it's valid base64
        tx_bytes = base64.b64decode(tx_base64)
        self.assertGreater(len(tx_bytes), 0)
        
    def test_multi_instruction_skill(self):
        """Test that skills can create transactions with multiple instructions."""
        skill_path = os.path.join(self.fixtures_path, "skill_multi_instruction.ts")
        
        skill_manager = TypeScriptSkillManager()
        result = skill_manager.execute_skill(skill_path)
        
        # Verify execution succeeded
        self.assertTrue(result['success'])
        self.assertEqual(result['reward'], 1.0)
        self.assertEqual(result['done_reason'], 'multi_instruction_success')
        
        # Verify transaction is larger (has multiple instructions)
        tx_base64 = result['tx_receipt_json_string']
        tx_bytes = base64.b64decode(tx_base64)
        self.assertGreater(len(tx_bytes), 100)  # Multi-instruction tx should be larger
        
    def test_observation_only_skill(self):
        """Test that observation-only skills can return null transaction."""
        skill_path = os.path.join(self.fixtures_path, "skill_observation_only.ts")
        
        skill_manager = TypeScriptSkillManager()
        result = skill_manager.execute_skill(skill_path)
        
        # Verify execution succeeded
        self.assertTrue(result['success'])
        self.assertEqual(result['reward'], 0.5)  # Has enough SOL
        self.assertEqual(result['done_reason'], 'sufficient_balance')
        
        # Verify no transaction was created
        self.assertIsNone(result['tx_receipt_json_string'])
        
    def test_invalid_base64_handling(self):
        """Test handling of skills that return invalid data."""
        # Create a skill that returns invalid base64
        invalid_skill = """
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    return [1.0, "invalid", "not-valid-base64!@#"];
}
"""
        skill_manager = TypeScriptSkillManager(skill_root="test_invalid_skills")
        skill_id = skill_manager.register(invalid_skill)
        skill_path = skill_manager.skills[skill_id]
        
        result = skill_manager.execute_skill(skill_path)
        
        # Execution should succeed (skill ran)
        self.assertTrue(result['success'])
        
        # But decoding the "base64" should fail
        with self.assertRaises(Exception):
            base64.b64decode(result['tx_receipt_json_string'], validate=True)
        
        # Clean up
        import shutil
        shutil.rmtree("test_invalid_skills", ignore_errors=True)


if __name__ == '__main__':
    unittest.main()