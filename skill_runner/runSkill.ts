import { exec } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execAsync = promisify(exec);

// Define the expected return type from executeSkill in TS skills
type SkillExecutionResult = [number, string, string | null]; // [reward, done_reason, tx_receipt_json_string]

// Track transaction count for single transaction enforcement
let transactionCount = 0;

// A mock environment for the skill to interact with.
// In a real scenario, this would be a more complex object
// that mirrors the Python SurfpoolEnv's capabilities.
// For now, it simulates a transaction receipt.
const surfpoolEnv = {
    // This is a simplified mock. In a real scenario, this would
    // interact with a Solana test validator or similar.
    // For the purpose of testing skills and returning a receipt,
    // we'll simulate a transaction.
    simulateTransaction: async (success: boolean = true, protocol: string | null = null) => {
        transactionCount++;
        if (transactionCount > 1) {
            throw new Error(
                "SINGLE_TRANSACTION_LIMIT: Skills can only execute ONE transaction. " +
                "To perform multiple operations, create separate skills and chain them. " +
                "This transaction attempt was blocked."
            );
        }
        
        // Generate a dummy transaction receipt.
        // In a real scenario, this would come from a Solana RPC call.
        const txReceipt = {
            transaction: {
                message: {
                    accountKeys: protocol ? [protocol] : [], // Use protocol as a dummy program ID
                    instructions: protocol ? [{ programIdIndex: 0 }] : [],
                },
            },
            meta: {
                err: success ? null : { "InstructionError": [0, { "Custom": 1 }] }, // Simulate success or failure
                logMessages: ["Simulated transaction log"],
            },
        };
        return JSON.stringify(txReceipt);
    },
    // Mock wallet balances: [SOL, USDC, ...]
    wallet_balances: [2.5, 100.0, 0.0, 0.0, 0.0],
    // Add getWallet method for compatibility
    getWallet: () => ({
        balances: [2.5, 100.0, 0.0, 0.0, 0.0],
        publicKey: "11111111111111111111111111111111" // Valid base58 pubkey
    }),
    // Add getRecentBlockhash for transaction building
    getRecentBlockhash: () => "11111111111111111111111111111111",
    // Add other methods as needed to mirror SurfpoolEnv
    read: () => "some data",
    write: (data: string) => console.log(`Skill wrote: ${data}`),
};

async function runSkill(): Promise<void> {
    const [, , filePath, timeoutMsStr] = process.argv;

    if (!filePath || !timeoutMsStr) {
        console.error('Usage: bun runSkill.ts <file> <timeoutMs>');
        process.exit(1);
    }

    const timeoutMs = parseInt(timeoutMsStr, 10);
    const absolutePath = path.resolve(filePath);

    // Reset transaction counter for each skill execution
    transactionCount = 0;

    try {
        const skillModule = await import(absolutePath);

        if (typeof skillModule.executeSkill !== 'function') {
            throw new Error('executeSkill function not found in the provided module.');
        }

        const [reward, done_reason, tx_receipt_json_string]: SkillExecutionResult = await Promise.race([
            skillModule.executeSkill(surfpoolEnv),
            new Promise<SkillExecutionResult>((_, reject) =>
                setTimeout(() => reject(new Error('Skill execution timed out.')), timeoutMs)
            ),
        ]);

        console.log(JSON.stringify({
            success: true,
            reward,
            done_reason,
            tx_receipt_json_string
        }));
    } catch (error) {
        const reason = error instanceof Error ? error.message : 'An unknown error occurred.';
        // For skill execution errors, return a proper error format
        console.log(JSON.stringify({ 
            success: false, 
            reason,
            reward: 0.0,
            done_reason: "error",
            tx_receipt_json_string: null,
            error: reason
        }));
        process.exit(1);
    }
}

runSkill();
