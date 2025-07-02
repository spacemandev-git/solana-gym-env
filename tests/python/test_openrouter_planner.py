import unittest
import os
from unittest.mock import patch, MagicMock
from planner import LLMPlanner
from skill_manager.ts_skill_manager import TypeScriptSkillManager

class TestOpenRouterPlanner(unittest.TestCase):
    def setUp(self):
        self.skill_manager = TypeScriptSkillManager(skill_root="test_skills")
        self.planner = LLMPlanner(self.skill_manager)
        
    def tearDown(self):
        if os.path.exists(self.skill_manager.skills_dir):
            import shutil
            shutil.rmtree(self.skill_manager.skills_dir)
    
    def test_planner_initialization_without_api_key(self):
        """Test that planner initializes correctly without API key."""
        with patch.dict(os.environ, {}, clear=True):
            planner = LLMPlanner(self.skill_manager)
            self.assertIsNone(planner.api_key)
    
    def test_planner_initialization_with_api_key(self):
        """Test that planner initializes correctly with API key."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test_key"}):
            planner = LLMPlanner(self.skill_manager)
            self.assertEqual(planner.api_key, "test_key")
    
    def test_dummy_skill_generation(self):
        """Test that dummy skill is returned when no API key is set."""
        with patch.dict(os.environ, {}, clear=True):
            planner = LLMPlanner(self.skill_manager)
            skill_code = planner.propose({"wallet_balances": [1.0]})
            
            self.assertIn("export async function executeSkill", skill_code)
            self.assertIn("Promise<[number, string, string | null]>", skill_code)
            self.assertIn("created_transfer_tx", skill_code)
    
    @patch('requests.post')
    def test_openrouter_api_call_success(self, mock_post):
        """Test successful API call to OpenRouter."""
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'choices': [{
                'message': {
                    'content': '''```typescript
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    const txReceipt = env.simulateTransaction(true, "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4");
    return [1.0, "Jupiter swap executed", txReceipt];
}
```'''
                }
            }]
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response
        
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test_key"}):
            planner = LLMPlanner(self.skill_manager)
            skill_code = planner.propose({"wallet_balances": [1.0]})
            
            # Verify API was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            
            # Check headers
            headers = call_args[1]['headers']
            self.assertEqual(headers['Authorization'], 'Bearer test_key')
            self.assertEqual(headers['Content-Type'], 'application/json')
            
            # Check the generated skill
            self.assertIn("Jupiter swap executed", skill_code)
            self.assertIn("JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4", skill_code)
    
    def test_openrouter_api_call_failure(self):
        """Test handling of API call failure."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test_key"}):
            planner = LLMPlanner(self.skill_manager)
            
            # Mock the _call_openrouter to return None (simulating failure)
            with patch.object(planner, '_call_openrouter', return_value=None):
                with patch('logging.warning'):  # Suppress warning logging in test
                    skill_code = planner.propose({"wallet_balances": [1.0]})
            
            # Should return dummy skill on failure
            self.assertIn("simulated_success", skill_code)
    
    def test_prompt_generation(self):
        """Test that prompts are generated correctly."""
        observation = {"wallet_balances": [1.0, 0.5], "block_height": [100]}
        prompt = self.planner._generate_prompt(observation, "Test objective")
        
        # Check key elements are in prompt
        self.assertIn("TypeScript module", prompt)
        self.assertIn("executeSkill(env: any)", prompt)
        self.assertIn("[number, string, string | null]", prompt)
        self.assertIn(str(observation), prompt)
        self.assertIn("Test objective", prompt)
    
    def test_prompt_with_error(self):
        """Test prompt generation with previous error."""
        observation = {"wallet_balances": [1.0]}
        error = "TypeError: Cannot read property 'foo' of undefined"
        prompt = self.planner._generate_prompt(observation, "Test", error=error)
        
        self.assertIn("Previous Attempt Failed", prompt)
        self.assertIn(error, prompt)
    
    def test_code_extraction_from_markdown(self):
        """Test extraction of TypeScript code from markdown response."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test_key"}):
            planner = LLMPlanner(self.skill_manager)
            
            # Test with typescript code block
            with patch.object(planner, '_call_openrouter') as mock_call:
                mock_call.return_value = '''Here's the code:
```typescript
export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    return [1.0, "test", null];
}
```
That should work!'''
                
                skill_code = planner.propose({})
                self.assertEqual(skill_code.strip(), '''export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    return [1.0, "test", null];
}''')
    
    def test_model_configuration(self):
        """Test that model can be configured."""
        # Test default model
        self.assertEqual(self.planner.model, "google/gemini-2.0-flash-exp:free")
        
        # Test custom model
        custom_planner = LLMPlanner(self.skill_manager, model="openai/gpt-4")
        self.assertEqual(custom_planner.model, "openai/gpt-4")
        
        # Test model from environment
        with patch.dict(os.environ, {"OPENROUTER_MODEL": "anthropic/claude-3"}):
            env_planner = LLMPlanner(self.skill_manager)
            self.assertEqual(env_planner.model, "anthropic/claude-3")

if __name__ == "__main__":
    unittest.main()