#!/usr/bin/env python3
"""
Demo script showing transaction complexity tracking and visualization.

This demonstrates:
1. Parsing transaction receipts for detailed information
2. Tracking transaction complexity metrics
3. Creating interactive transaction browsers
4. Visualizing transaction patterns
"""

import json
import random
from trajectory_tracker import TrajectoryTracker, TransactionDetails
from trajectory_visualizer import TrajectoryVisualizer
from transaction_parser import parse_transaction_receipt


def generate_mock_transaction_receipt(skill_type: str, complexity: str = "medium") -> str:
    """Generate a mock transaction receipt with varying complexity."""
    
    # Define different transaction patterns
    patterns = {
        "simple": {
            "num_accounts": 3,
            "num_instructions": 1,
            "compute_units": 50000,
            "fee": 5000,
            "programs": ["11111111111111111111111111111111"]
        },
        "medium": {
            "num_accounts": 8,
            "num_instructions": 3,
            "compute_units": 150000,
            "fee": 15000,
            "programs": ["TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", 
                        "11111111111111111111111111111111"]
        },
        "complex": {
            "num_accounts": 15,
            "num_instructions": 7,
            "compute_units": 400000,
            "fee": 35000,
            "programs": ["JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
                        "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
                        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                        "11111111111111111111111111111111"]
        }
    }
    
    pattern = patterns.get(complexity, patterns["medium"])
    
    # Build account keys
    account_keys = pattern["programs"] + [
        f"Account{i:02d}{'1' * 32}" for i in range(pattern["num_accounts"] - len(pattern["programs"]))
    ]
    
    # Build instructions
    instructions = []
    for i in range(pattern["num_instructions"]):
        program_idx = i % len(pattern["programs"])
        instructions.append({
            "programIdIndex": program_idx,
            "accounts": list(range(len(pattern["programs"]), 
                                  min(len(account_keys), len(pattern["programs"]) + 3))),
            "data": f"instruction_data_{i}",
            "stackHeight": 1 if i == 0 else random.randint(1, 3)
        })
    
    # Build log messages
    log_messages = [
        f"Program {pattern['programs'][0]} invoke [1]",
        f"Program log: Processing {skill_type} transaction",
        f"Program consumed {pattern['compute_units']} compute units",
        f"Program {pattern['programs'][0]} success"
    ]
    
    # Build receipt
    receipt = {
        "signature": f"sig{''.join(random.choices('0123456789abcdef', k=64))}",
        "slot": random.randint(250000000, 260000000),
        "blockTime": 1751414176,
        "transaction": {
            "message": {
                "accountKeys": account_keys,
                "instructions": instructions
            }
        },
        "meta": {
            "err": None if random.random() > 0.1 else {"InstructionError": [0, {"Custom": 1}]},
            "fee": pattern["fee"],
            "logMessages": log_messages
        }
    }
    
    return json.dumps(receipt)


def create_demo_with_transactions():
    """Create a demo trajectory with detailed transaction information."""
    
    # Initialize tracker
    tracker = TrajectoryTracker()
    
    # Simulate multiple episodes
    for episode_num in range(1, 4):
        print(f"\nSimulating Episode {episode_num}...")
        episode = tracker.start_episode()
        
        # Vary complexity based on episode progress
        complexities = ["simple", "simple", "medium", "medium", "complex"] if episode_num == 1 else \
                      ["medium", "medium", "complex", "complex", "complex"]
        
        # Simulate skill attempts with transactions
        skills = ["basic_swap", "token_transfer", "jupiter_swap", "liquidity_add", "stake_sol"]
        
        for i, (skill, complexity) in enumerate(zip(skills, complexities)):
            # Record LLM call
            tracker.record_llm_call(
                objective=f"Generate {skill} skill",
                success=True,
                skill_generated=True
            )
            
            # Generate transaction receipt
            tx_receipt_json = generate_mock_transaction_receipt(skill, complexity)
            
            # Parse transaction details
            tx_details = parse_transaction_receipt(tx_receipt_json)
            
            # Determine success and reward
            success = tx_details.success if tx_details else False
            reward = 2.0 if "jupiter" in skill else 1.0 if success else 0.0
            
            # Record skill attempt with transaction details
            tracker.record_skill_attempt(
                skill_id=i,
                skill_name=skill,
                success=success,
                reward=reward,
                done_reason="success" if success else "failed",
                protocols_discovered=["Jupiter"] if "jupiter" in skill and episode_num == 1 else [],
                transaction_details=tx_details
            )
            
            print(f"  - {skill}: {'✓' if success else '✗'} "
                  f"(Complexity: {tx_details.compute_units_consumed:,} CUs, "
                  f"{tx_details.num_instructions} instructions)")
        
        tracker.end_episode()
    
    # Save trajectory data
    tracker.save("demo_trajectory_with_transactions.json")
    print("\nTrajectory data saved to demo_trajectory_with_transactions.json")
    
    return tracker


def visualize_transaction_complexity(tracker: TrajectoryTracker):
    """Create visualizations of transaction complexity."""
    
    print("\nGenerating transaction visualizations...")
    
    # Initialize visualizer
    viz = TrajectoryVisualizer(tracker)
    
    # 1. Transaction complexity analysis
    print("1. Creating transaction complexity analysis...")
    viz.plot_transaction_complexity("transaction_complexity_analysis.html")
    
    # 2. Interactive transaction browser
    print("2. Creating interactive transaction browser...")
    viz.create_transaction_browser("transaction_browser.html")
    
    # 3. Voyager-style plot with transactions
    print("3. Creating Voyager-style exploration plot...")
    viz.plot_voyager_style_exploration("voyager_with_transactions.png")
    
    # 4. Comprehensive dashboard
    print("4. Creating comprehensive dashboard...")
    viz.plot_comprehensive_dashboard("comprehensive_dashboard.html")
    
    print("\nVisualizations created:")
    print("  - transaction_complexity_analysis.html: Detailed transaction metrics")
    print("  - transaction_browser.html: Interactive browser for all transactions")
    print("  - voyager_with_transactions.png: Voyager-style exploration plot")
    print("  - comprehensive_dashboard.html: Full performance dashboard")


def analyze_transaction_patterns(tracker: TrajectoryTracker):
    """Analyze and print transaction patterns."""
    
    print("\n" + "="*60)
    print("TRANSACTION PATTERN ANALYSIS")
    print("="*60)
    
    # Collect all transactions
    all_transactions = []
    for ep in tracker.episodes:
        for attempt in ep.skill_attempts:
            if attempt.transaction_details:
                all_transactions.append({
                    'episode': ep.episode_id,
                    'skill': attempt.skill_name,
                    'tx': attempt.transaction_details,
                    'success': attempt.success
                })
    
    if not all_transactions:
        print("No transactions found.")
        return
    
    # Compute statistics
    total_cus = sum(t['tx'].compute_units_consumed for t in all_transactions)
    total_fees = sum(t['tx'].fee for t in all_transactions)
    avg_accounts = sum(t['tx'].num_accounts for t in all_transactions) / len(all_transactions)
    avg_instructions = sum(t['tx'].num_instructions for t in all_transactions) / len(all_transactions)
    
    print(f"\nTotal Transactions: {len(all_transactions)}")
    print(f"Success Rate: {sum(1 for t in all_transactions if t['success']) / len(all_transactions):.1%}")
    print(f"\nCompute Units:")
    print(f"  Total: {total_cus:,}")
    print(f"  Average: {total_cus / len(all_transactions):,.0f}")
    print(f"  Max: {max(t['tx'].compute_units_consumed for t in all_transactions):,}")
    print(f"\nFees:")
    print(f"  Total: {total_fees / 1e9:.6f} SOL")
    print(f"  Average: {(total_fees / len(all_transactions)) / 1e9:.6f} SOL")
    print(f"\nComplexity:")
    print(f"  Avg Accounts per TX: {avg_accounts:.1f}")
    print(f"  Avg Instructions per TX: {avg_instructions:.1f}")
    
    # Most complex transactions
    print("\nMost Complex Transactions:")
    from transaction_parser import get_transaction_complexity_score
    
    complex_txs = sorted(all_transactions, 
                        key=lambda x: get_transaction_complexity_score(x['tx']), 
                        reverse=True)[:3]
    
    for i, tx_data in enumerate(complex_txs, 1):
        score = get_transaction_complexity_score(tx_data['tx'])
        print(f"\n  {i}. {tx_data['skill']} (Episode {tx_data['episode']})")
        print(f"     Complexity Score: {score:.1f}")
        print(f"     CUs: {tx_data['tx'].compute_units_consumed:,}")
        print(f"     Instructions: {tx_data['tx'].num_instructions}")
        print(f"     Accounts: {tx_data['tx'].num_accounts}")


if __name__ == "__main__":
    print("Solana Voyager - Transaction Complexity Demo")
    print("=" * 50)
    
    # Create demo trajectory with transactions
    tracker = create_demo_with_transactions()
    
    # Analyze transaction patterns
    analyze_transaction_patterns(tracker)
    
    # Create visualizations
    visualize_transaction_complexity(tracker)
    
    print("\n✅ Demo completed successfully!")
    print("\nTo view the visualizations:")
    print("  - Open transaction_browser.html in a web browser")
    print("  - Open transaction_complexity_analysis.html for detailed metrics")
    print("  - View voyager_with_transactions.png for the exploration plot")