#!/usr/bin/env python3
"""
System Program Demo - Shows agent successfully discovering the System Program

This demo uses the System Program which doesn't require Anchor discriminators,
so transactions will actually succeed and we can see protocol discovery working.
"""

import asyncio
import logging
import os
import json
from datetime import datetime
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from tracking.voyager_env_with_tracking import VoyagerEnvWithTracking

# Set up detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

async def run_system_program_demo():
    """Run a demo that successfully discovers the System Program."""
    
    # Use tracking environment
    env = VoyagerEnvWithTracking(max_steps=10, skill_root="./demo_skills", enable_tracking=True, protocols=["11111111111111111111111111111111"])
    
    try:
        # Reset environment
        obs, info = await env.reset()
        
        print("\n" + "="*80)
        print("🚀 SOLANA GYM - SYSTEM PROGRAM DEMO")
        print("="*80)
        print("This demo shows successful protocol discovery with the System Program")
        
        # Show initial observation
        print("\n📊 Initial Observation:")
        print(f"  - Wallet balance: {obs.get('wallet_balances', [0])[0]:.2f} SOL")
        print(f"  - Protocols discovered so far: {len(env.protocols_seen)}")
        
        # STEP 1: Create a skill that transfers SOL (uses System Program)
        print("\n" + "-"*60)
        print("🔧 STEP 1: Generate System Program Transfer Skill")
        print("-"*60)
        
        # Override planner to create a System Program skill
        if hasattr(env, 'planner'):
            original_get_dummy = env.planner._get_dummy_skill
            def system_program_skill():
                return """
import { Transaction, SystemProgram, PublicKey, LAMPORTS_PER_SOL } from '@solana/web3.js';

export async function executeSkill(): Promise<string> {
    const tx = new Transaction();
    
    // Transfer 0.01 SOL to ourselves (uses System Program)
    tx.add(SystemProgram.transfer({
        fromPubkey: new PublicKey(wallet.publicKey),
        toPubkey: new PublicKey(wallet.publicKey),  // Send to self
        lamports: Math.floor(0.01 * LAMPORTS_PER_SOL)
    }));
    
    // Set transaction properties
    tx.recentBlockhash = env.getRecentBlockhash();
    tx.feePayer = new PublicKey(wallet.publicKey);
    
    // Serialize to base64
    const serializedTx = tx.serialize({
        requireAllSignatures: false,
        verifySignatures: false
    }).toString('base64');
    
    return serializedTx;
}
"""
            env.planner._get_dummy_skill = system_program_skill
        
        action = {"action_type": env.SPECIALS["NEW_SKILL"], "program_id": None}
        obs, reward, term, trunc, info = await env.step(action)
        
        print(f"\n✅ Skill Generation Result:")
        print(f"   - Success: {info.get('status') == 'success'}")
        print(f"   - Reward: {reward}")
        print(f"   - New skill ID: {info.get('new_skill_id', 'N/A')}")
        
        if info.get('status') == 'success':
            skill_id = info['new_skill_id']
            
            # STEP 2: Execute the skill
            print("\n" + "-"*60)
            print("🚀 STEP 2: Execute System Program Transfer")
            print("-"*60)
            
            action = {"action_type": len(env.SPECIALS) + skill_id, "program_id": None}
            obs, reward, term, trunc, info = await env.step(action)
            
            print(f"\n📊 Execution Result:")
            print(f"   - Base reward from skill: 0.5")
            print(f"   - Exploration bonus: {reward - 0.5}")
            print(f"   - Total reward: {reward}")
            print(f"   - Done reason: {info.get('done_reason', 'N/A')}")
            print(f"   - Protocols discovered: {info.get('protocols_interacted', [])}")
            print(f"   - Transaction succeeded: {info.get('tx_sent', False)}")
            
            # STEP 3: Execute again to show no bonus for repeated protocol
            print("\n" + "-"*60)
            print("🔄 STEP 3: Execute Again (No Bonus Expected)")
            print("-"*60)
            
            obs, reward2, term, trunc, info2 = await env.step(action)
            
            print(f"\n📊 Second Execution Result:")
            print(f"   - Base reward from skill: 0.5")
            print(f"   - Exploration bonus: {reward2 - 0.5}")
            print(f"   - Total reward: {reward2}")
            print(f"   - Protocols in this tx: {info2.get('protocols_interacted', [])}")
            
        # Show what the agent learned
        print("\n" + "="*60)
        print("🎓 WHAT THE AGENT LEARNED")
        print("="*60)
        print(f"Total protocols discovered: {len(env.protocols_seen)}")
        print(f"Protocols: {list(env.protocols_seen)}")
        
        if hasattr(env, 'tracker') and env.tracker:
            metrics = env.tracker.get_metrics()
            print(f"\nTrajectory metrics:")
            print(f"  - Skill attempts: {metrics.get('total_skill_attempts', 0)}")
            print(f"  - Success rate: {metrics.get('success_rate', 0):.1%}")
            print(f"  - Total reward: {metrics.get('avg_reward_per_episode', 0) * metrics.get('total_episodes', 1):.1f}")
            
            # Save trajectory
            trajectory_file = f"system_program_trajectory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            env.tracker.save(trajectory_file)
            print(f"\n💾 Trajectory saved to: {trajectory_file}")
            
    except Exception as e:
        logging.error(f"Error during demo: {e}", exc_info=True)
        
    finally:
        await env.close()
        print("\n✅ Demo complete!")

async def main():
    """Main entry point."""
    await run_system_program_demo()

if __name__ == "__main__":
    asyncio.run(main())