#!/usr/bin/env python3
"""
Demo: Solana Voyager Agent Writing Its Own Skills

This script demonstrates the agent's ability to:
1. Observe the environment
2. Generate new skills using LLM (OpenRouter)
3. Execute the generated skills
4. Learn from successes and failures
"""

import asyncio
import logging
import os
import shutil
from voyager_env import SolanaVoyagerEnv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def demonstrate_skill_generation():
    """Demonstrates the agent writing and executing its own skills."""
    
    # Clean up any existing skills from previous runs
    skills_dir = "./demo_skills"
    if os.path.exists(skills_dir):
        shutil.rmtree(skills_dir)
    
    # Create environment with custom skills directory
    env = SolanaVoyagerEnv(max_steps=10, skill_root=skills_dir)
    
    try:
        # Reset the environment
        obs, info = await env.reset()
        logging.info("=== Solana Voyager Environment Initialized ===")
        logging.info(f"Initial observation keys: {list(obs.keys())}")
        logging.info(f"Wallet balances: {obs.get('wallet_balances', [])[:5]}...")  # Show first 5
        
        # Step 1: Generate a new skill
        logging.info("\n=== Step 1: Agent Generates a New Skill ===")
        logging.info("The agent will now use LLM to create a skill based on the current observation.")
        
        obs, reward, term, trunc, info = await env.step(env.SPECIALS["NEW_SKILL"])
        
        if info.get("status") == "success":
            logging.info(f"✅ Skill generated successfully! Reward: {reward}")
            logging.info(f"New skill ID: {info.get('new_skill_id')}")
            
            # Step 2: Execute the newly created skill
            skill_id = info['new_skill_id']
            action = len(env.SPECIALS) + skill_id
            
            logging.info(f"\n=== Step 2: Agent Executes Generated Skill (ID: {skill_id}) ===")
            obs, reward, term, trunc, info = await env.step(action)
            
            logging.info(f"Execution result:")
            logging.info(f"  - Reward: {reward}")
            logging.info(f"  - Done reason: {info.get('done_reason', 'N/A')}")
            logging.info(f"  - Protocols interacted: {info.get('protocols_interacted', [])}")
            
            # Step 3: Generate another skill based on updated observation
            logging.info("\n=== Step 3: Agent Generates Another Skill ===")
            logging.info("Based on the results, the agent creates another skill.")
            
            obs, reward, term, trunc, info = await env.step(env.SPECIALS["NEW_SKILL"])
            
            if info.get("status") == "success":
                logging.info(f"✅ Second skill generated! Reward: {reward}")
                
                # Execute the second skill
                skill_id = info['new_skill_id']
                action = len(env.SPECIALS) + skill_id
                
                logging.info(f"\n=== Step 4: Agent Executes Second Skill (ID: {skill_id}) ===")
                obs, reward, term, trunc, info = await env.step(action)
                
                logging.info(f"Execution result:")
                logging.info(f"  - Reward: {reward}")
                logging.info(f"  - Done reason: {info.get('done_reason', 'N/A')}")
                logging.info(f"  - Protocols interacted: {info.get('protocols_interacted', [])}")
            else:
                logging.error(f"❌ Failed to generate second skill: {info.get('last_error')}")
                
        else:
            logging.error(f"❌ Failed to generate initial skill: {info.get('last_error')}")
            logging.info("Note: This might happen if OPENROUTER_API_KEY is not set in .env")
            logging.info("Without API key, dummy skills will be used.")
        
        # Show summary
        logging.info("\n=== Summary ===")
        logging.info(f"Total skills created: {len(env.skills)}")
        logging.info(f"Protocols discovered: {env.protocols_seen}")
        
        # List generated skills
        if os.path.exists(skills_dir):
            skills = [f for f in os.listdir(skills_dir) if f.endswith('.ts')]
            logging.info(f"Generated skill files: {skills}")
            
            # Show content of first generated skill
            if skills:
                logging.info(f"\n=== Content of {skills[0]} ===")
                with open(os.path.join(skills_dir, skills[0]), 'r') as f:
                    logging.info(f.read())
                    
    finally:
        await env.close()
        logging.info("\n=== Environment Closed ===")

async def main():
    """Main entry point."""
    logging.info("=== Solana Gym Skill Generation Demo ===")
    logging.info("This demo shows the agent writing its own TypeScript skills using LLM.\n")
    
    # Check if API key is set
    if not os.environ.get("OPENROUTER_API_KEY"):
        logging.warning("⚠️  OPENROUTER_API_KEY not found in environment!")
        logging.warning("Please create a .env file with your OpenRouter API key.")
        logging.warning("Copy .env.example to .env and add your key.")
        logging.warning("The demo will continue with dummy skills.\n")
    else:
        logging.info("✅ OpenRouter API key found. Skills will be generated using LLM.\n")
    
    await demonstrate_skill_generation()

if __name__ == "__main__":
    asyncio.run(main())