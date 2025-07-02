#!/usr/bin/env bun
/**
 * Minimal reproduction of surfpool RPC issue - TypeScript version
 * 
 * This tests if the issue is specific to solana-py or general to surfpool.
 * 
 * To run:
 * 1. Start surfpool: surfpool start --no-tui
 * 2. Run this script: bun surfpool_repro.ts
 */

import { 
    Connection, 
    Keypair, 
    Transaction, 
    SystemProgram, 
    LAMPORTS_PER_SOL,
    sendAndConfirmTransaction 
} from '@solana/web3.js';

async function reproduceError() {
    console.log("=".repeat(60));
    console.log("SURFPOOL RPC ERROR TEST (TypeScript)");
    console.log("=".repeat(60));
    
    const connection = new Connection("http://localhost:8899", "confirmed");
    
    try {
        // Create test keypairs
        console.log("\n1. Creating test keypairs...");
        const sender = Keypair.generate();
        const receiver = Keypair.generate();
        console.log(`   Sender: ${sender.publicKey.toBase58()}`);
        console.log(`   Receiver: ${receiver.publicKey.toBase58()}`);
        
        // Fund sender
        console.log("\n2. Funding sender...");
        const airdropSig = await connection.requestAirdrop(
            sender.publicKey,
            2 * LAMPORTS_PER_SOL
        );
        await connection.confirmTransaction(airdropSig);
        
        const balance = await connection.getBalance(sender.publicKey);
        console.log(`   Balance: ${balance / LAMPORTS_PER_SOL} SOL`);
        
        // Test cases
        console.log("\n3. Testing transactions...");
        
        // Case 1: Self-transfer
        console.log("\n   Case 1: Self-transfer");
        try {
            const tx1 = new Transaction().add(
                SystemProgram.transfer({
                    fromPubkey: sender.publicKey,
                    toPubkey: sender.publicKey,
                    lamports: 0.001 * LAMPORTS_PER_SOL
                })
            );
            
            const sig1 = await sendAndConfirmTransaction(connection, tx1, [sender]);
            console.log(`   ✅ Success: ${sig1}`);
        } catch (e) {
            console.log(`   ❌ Failed: ${e}`);
        }
        
        // Case 2: Transfer to unfunded account
        console.log("\n   Case 2: Transfer to unfunded account");
        try {
            const tx2 = new Transaction().add(
                SystemProgram.transfer({
                    fromPubkey: sender.publicKey,
                    toPubkey: receiver.publicKey,
                    lamports: 0.001 * LAMPORTS_PER_SOL
                })
            );
            
            const sig2 = await sendAndConfirmTransaction(connection, tx2, [sender]);
            console.log(`   ✅ Success: ${sig2}`);
        } catch (e) {
            console.log(`   ❌ Failed: ${e}`);
        }
        
        // Case 3: Transfer to system program
        console.log("\n   Case 3: Transfer to system program");
        try {
            const tx3 = new Transaction().add(
                SystemProgram.transfer({
                    fromPubkey: sender.publicKey,
                    toPubkey: SystemProgram.programId,
                    lamports: 0.001 * LAMPORTS_PER_SOL
                })
            );
            
            const sig3 = await sendAndConfirmTransaction(connection, tx3, [sender]);
            console.log(`   ✅ Success: ${sig3}`);
        } catch (e) {
            console.log(`   ❌ Failed: ${e}`);
        }
        
        // Case 4: Raw RPC call to check response format
        console.log("\n4. Testing raw RPC response...");
        const recentBlockhash = await connection.getLatestBlockhash();
        const tx4 = new Transaction({
            recentBlockhash: recentBlockhash.blockhash,
            feePayer: sender.publicKey
        }).add(
            SystemProgram.transfer({
                fromPubkey: sender.publicKey,
                toPubkey: SystemProgram.programId,
                lamports: 1000
            })
        );
        tx4.sign(sender);
        
        // Send raw transaction and inspect response
        try {
            const serialized = tx4.serialize();
            const response = await fetch("http://localhost:8899", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    id: 1,
                    method: "sendTransaction",
                    params: [
                        serialized.toString("base64"),
                        { encoding: "base64" }
                    ]
                })
            });
            
            const result = await response.json();
            console.log("   Raw RPC response:", JSON.stringify(result, null, 2));
        } catch (e) {
            console.log(`   Raw RPC error: ${e}`);
        }
        
    } catch (e) {
        console.error("\nUnexpected error:", e);
    }
    
    console.log("\n" + "=".repeat(60));
}

// Run the test
reproduceError().catch(console.error);