"""
Simplified End-to-End Test: Agent Learning to Perform Jupiter Swap

This test verifies the core functionality without dealing with async complexity.
"""

import unittest
import os
import shutil
import tempfile
from unittest.mock import patch, MagicMock
import json

# Import after path is set
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from skill_manager.ts_skill_manager import TypeScriptSkillManager
from planner import LLMPlanner


class TestE2EJupiterSwapSimple(unittest.TestCase):
    """Simplified end-to-end test for Jupiter swap skill generation."""
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.skills_dir = os.path.join(self.test_dir, "test_skills")
        os.makedirs(self.skills_dir)
        
        # Create skill manager
        self.skill_manager = TypeScriptSkillManager(skill_root=self.skills_dir)
        
        # Mock observation
        self.observation = {
            "wallet_balances": [2.5, 100.0, 0.0, 0.0, 0.0],  # SOL, USDC
            "block_height": [250000000],
            "recent_blockhash": "FwRYtTPRk5N4wUeP87rTw9kQVSwigB6kbikGzzeCMrW5"
        }
    
    def tearDown(self):
        """Clean up."""
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
    
    def _create_jupiter_swap_skill(self):
        """Create a Jupiter swap skill response."""
        return '''
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    // Check if we have enough SOL for swap
    const solBalance = env.wallet_balances?.[0] || 0;
    if (solBalance < 0.1) {
        return [0.0, "insufficient_sol_for_swap", null];
    }
    
    // Simulate Jupiter swap
    const txReceipt = env.simulateTransaction(true, "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
    return [1.0, "jupiter_swap_successful", txReceipt];
}
'''
    
    @patch('planner.LLMPlanner._call_openrouter')
    def test_skill_generation_and_execution(self, mock_openrouter):
        """Test complete flow: observation → skill generation → execution."""
        # Mock LLM to return Jupiter swap skill
        mock_openrouter.return_value = self._create_jupiter_swap_skill()
        
        # Create planner
        planner = LLMPlanner(self.skill_manager)
        
        # Step 1: Generate skill based on observation
        skill_code = planner.propose(
            self.observation,
            objective="Create a skill to swap SOL for USDC on Jupiter"
        )
        
        # Verify skill was generated
        self.assertIn("executeSkill", skill_code)
        self.assertIn("jupiter", skill_code.lower())
        
        # Step 2: Register the skill
        skill_id = self.skill_manager.register(skill_code)
        self.assertEqual(skill_id, 0)
        self.assertEqual(len(self.skill_manager.skills), 1)
        
        # Step 3: Execute the skill
        file_path = self.skill_manager.skills[skill_id]
        result = self.skill_manager.execute_skill(file_path)
        
        # Verify execution results
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("done_reason"), "jupiter_swap_successful")
        self.assertIsNotNone(result.get("tx_receipt_json_string"))
        
        # Parse transaction receipt
        tx_receipt = json.loads(result["tx_receipt_json_string"])
        self.assertIn("transaction", tx_receipt)
        self.assertIn("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4", 
                      tx_receipt["transaction"]["message"]["accountKeys"])
    
    @patch('planner.LLMPlanner._call_openrouter')
    def test_insufficient_balance_handling(self, mock_openrouter):
        """Test skill handling insufficient balance."""
        # Create skill that checks for low balance
        low_balance_skill = '''
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    // Always return insufficient balance for testing
    return [0.0, "insufficient_sol_for_swap", null];
}
'''
        mock_openrouter.return_value = low_balance_skill
        
        planner = LLMPlanner(self.skill_manager)
        
        # Generate and register skill
        skill_code = planner.propose(self.observation)
        skill_id = self.skill_manager.register(skill_code)
        
        # Execute skill
        result = self.skill_manager.execute_skill(self.skill_manager.skills[skill_id])
        
        # Should handle insufficient balance gracefully
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("done_reason"), "insufficient_sol_for_swap")
        self.assertEqual(result.get("reward"), 0.0)
    
    def test_skill_persistence(self):
        """Test that skills persist across manager instances."""
        # Create and save a skill manually
        skill_code = '''
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    const tx = env.simulateTransaction(true, "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
    return [1.0, "manual_jupiter_swap", tx];
}
'''
        
        # Register skill with first manager
        skill_id = self.skill_manager.register(skill_code)
        self.assertEqual(len(self.skill_manager.skills), 1)
        
        # Create new manager with same directory
        new_manager = TypeScriptSkillManager(skill_root=self.skills_dir)
        
        # Should load the existing skill
        self.assertEqual(len(new_manager.skills), 1)
        self.assertIn(skill_id, new_manager.skills)
        
        # Should be able to execute loaded skill
        result = new_manager.execute_skill(new_manager.skills[skill_id])
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("done_reason"), "manual_jupiter_swap")
    
    @patch('planner.LLMPlanner._call_openrouter')
    def test_skill_library_growth(self, mock_openrouter):
        """Test building a library of different protocol skills."""
        # Different skills for each call
        skills = [
            # Jupiter
            '''export async function executeSkill(env: any): Promise<[number, string, string | null]> {
                const tx = env.simulateTransaction(true, "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
                return [1.0, "jupiter_swap", tx];
            }''',
            # Orca
            '''export async function executeSkill(env: any): Promise<[number, string, string | null]> {
                const tx = env.simulateTransaction(true, "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc");
                return [1.0, "orca_swap", tx];
            }''',
            # Raydium
            '''export async function executeSkill(env: any): Promise<[number, string, string | null]> {
                const tx = env.simulateTransaction(true, "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8");
                return [1.0, "raydium_swap", tx];
            }'''
        ]
        
        mock_openrouter.side_effect = skills
        planner = LLMPlanner(self.skill_manager)
        
        # Generate multiple skills
        objectives = [
            "Swap on Jupiter",
            "Swap on Orca", 
            "Swap on Raydium"
        ]
        
        for i, objective in enumerate(objectives):
            skill_code = planner.propose(self.observation, objective)
            skill_id = self.skill_manager.register(skill_code)
            self.assertEqual(skill_id, i)
        
        # Verify all skills work
        self.assertEqual(len(self.skill_manager.skills), 3)
        
        results = []
        for skill_id in range(3):
            result = self.skill_manager.execute_skill(self.skill_manager.skills[skill_id])
            results.append(result)
            self.assertTrue(result.get("success"))
        
        # Verify different protocols
        self.assertEqual(results[0]["done_reason"], "jupiter_swap")
        self.assertEqual(results[1]["done_reason"], "orca_swap") 
        self.assertEqual(results[2]["done_reason"], "raydium_swap")
    
    @patch('planner.LLMPlanner._call_openrouter')
    def test_complex_multi_step_skill(self, mock_openrouter):
        """Test generation of more complex multi-step skills."""
        # Complex skill that checks multiple conditions
        complex_skill = '''
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    // Multi-step Jupiter swap with safety checks
    const solBalance = env.wallet_balances?.[0] || 0;
    
    // Step 1: Check minimum balance
    if (solBalance < 0.1) {
        return [0.0, "insufficient_balance", null];
    }
    
    // Step 2: Check if swap amount is reasonable
    const swapAmount = Math.min(solBalance * 0.5, 1.0); // Max 50% or 1 SOL
    
    // Step 3: Simulate the swap
    const txReceipt = env.simulateTransaction(true, "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
    
    // Step 4: Return with appropriate reward based on amount
    const reward = swapAmount >= 0.5 ? 2.0 : 1.0;
    return [reward, "complex_swap_complete", txReceipt];
}
'''
        
        mock_openrouter.return_value = complex_skill
        planner = LLMPlanner(self.skill_manager)
        
        # Generate complex skill
        skill_code = planner.propose(
            self.observation,
            objective="Create a safe Jupiter swap skill with multiple checks"
        )
        
        # Register and execute
        skill_id = self.skill_manager.register(skill_code)
        result = self.skill_manager.execute_skill(self.skill_manager.skills[skill_id])
        
        # Should execute successfully with higher reward
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("done_reason"), "complex_swap_complete")
        self.assertEqual(result.get("reward"), 2.0)  # High reward for large swap


if __name__ == "__main__":
    unittest.main()