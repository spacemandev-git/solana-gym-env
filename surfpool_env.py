import gymnasium as gym
import numpy as np
import subprocess
import time
import asyncio
from typing import Optional, Callable, Set

from gymnasium import spaces
from solana.rpc.api import Client as RpcClient
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.system_program import transfer, TransferParams
from solders.message import MessageV0
from solders.hash import Hash
from solders.pubkey import Pubkey

# Define constants for the observation and action spaces
# TODO: These should be configured based on the specific protocols and tokens
MAX_TOKENS = 10  # Maximum number of different tokens in the wallet
NUM_PROTOCOLS = 20 # Number of known protocols the agent can interact with
MAX_INSTRUCTIONS_PER_PROTOCOL = 5 # Max instructions per protocol

class SurfpoolEnv(gym.Env):
    """
    The low-level Solana environment that interfaces directly with the surfpool validator.
    This environment is responsible for:
    - Managing the surfpool validator subprocess.
    - Providing a rich observation of the on-chain state.
    - Executing pre-formed transactions.
    """
    metadata = {"render_modes": ["human"], "render_fps": 30}

    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com/6da7c9d2-7d3d-4f7f-8302-97f5fadb58a8", ws_url: str = "ws://localhost:8900"):
        super().__init__()

        self.rpc_url = rpc_url
        self.ws_url = ws_url
        # The client for the Voyager environment will connect to the surfpool instance
        self.client = AsyncClient("http://127.0.0.1:8899", "confirmed")
        self.test_validator_process = None
        self.agent_keypair = Keypair()

        # --- Observation Space ---
        self.observation_space = spaces.Dict({
            "wallet_balances": spaces.Box(low=0, high=np.inf, shape=(MAX_TOKENS,), dtype=np.float64),
            "agent_pubkey": spaces.Box(low=0, high=255, shape=(32,), dtype=np.uint8),
            "block_height": spaces.Box(low=0, high=np.inf, shape=(1,), dtype=np.int64),
            "block_timestamp": spaces.Box(low=0, high=np.inf, shape=(1,), dtype=np.int64),
            "last_tx_success": spaces.Discrete(2),
            "last_tx_error": spaces.Text(max_length=128),
            "available_protocols": spaces.Sequence(
                spaces.Dict({
                    "protocol_id": spaces.Discrete(NUM_PROTOCOLS),
                    "address": spaces.Box(low=0, high=255, shape=(32,), dtype=np.uint8),
                })
            )
        })
        
        # This action space is a placeholder. The Voyager layer will use its own.
        self.action_space = spaces.Discrete(1)
        self.last_observation = None


    def _start_test_validator(self):
        print("Starting Solana test validator via surfpool...")
        try:
            command = [
                'surfpool', 'start', '-u', self.rpc_url
            ]
            self.test_validator_process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("Surfpool process started.")
        except FileNotFoundError:
            print("Error: 'surfpool' command not found. Please ensure it's installed and in your PATH.")
            self.test_validator_process = None
        except Exception as e:
            print(f"Error starting test validator: {e}")
            self.test_validator_process = None

    async def _wait_for_validator(self):
        """Polls the RPC endpoint until it's responsive."""
        print("Waiting for validator to start...")
        for i in range(60):  # 60 seconds timeout
            try:
                # Check for block 0 as a health check
                await self.client.get_block(0)
                print("Validator is healthy.")
                return
            except Exception:
                await asyncio.sleep(1)
        raise RuntimeError("Validator did not start in time.")

    def _stop_test_validator(self):
        if self.test_validator_process and isinstance(self.test_validator_process, subprocess.Popen):
            print("Stopping Solana test validator...")
            self.test_validator_process.terminate()
            self.test_validator_process.wait()
            self.test_validator_process = None
            print("Solana test validator stopped.")

    async def _get_observation(self, last_tx_result=None):
        # In a real implementation, you would fetch this data from the chain
        obs = {
            "wallet_balances": np.zeros(MAX_TOKENS, dtype=np.float64),
            "agent_pubkey": np.frombuffer(self.agent_keypair.pubkey().__bytes__(), dtype=np.uint8),
            "block_height": np.array([0], dtype=np.int64),
            "block_timestamp": np.array([0], dtype=np.int64),
            "last_tx_success": 0,
            "last_tx_error": "",
            "available_protocols": [] # This would be populated with known protocol addresses
        }

        try:
            # Get basic block info
            block_height = await self.client.get_block_height()
            obs["block_height"] = np.array([block_height.value], dtype=np.int64)
            
            # Get agent SOL balance (as the first token)
            balance = await self.client.get_balance(self.agent_keypair.pubkey())
            obs["wallet_balances"][0] = balance.value / 1e9 # Convert lamports to SOL

            # TODO: Get other token balances

        except Exception as e:
            print(f"Error getting observation: {e}")

        if last_tx_result:
            if last_tx_result["meta"]["err"] is None:
                obs["last_tx_success"] = 1
            else:
                obs["last_tx_success"] = 0
                obs["last_tx_error"] = str(last_tx_result["meta"]["err"])

        self.last_observation = obs
        return obs

    async def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        self._stop_test_validator()
        self._start_test_validator()

        # Wait for the validator to be ready
        await self._wait_for_validator()

        # Create a new agent for the episode
        self.agent_keypair = Keypair()
        
        # Fund the agent
        try:
            print(f"Airdropping SOL to {self.agent_keypair.pubkey()}...")
            airdrop_sig = await self.client.request_airdrop(self.agent_keypair.pubkey(), 2 * 10**9) # 2 SOL
            await self.client.confirm_transaction(airdrop_sig.value, "confirmed", 30.0)
            print("Airdrop successful.")
        except Exception as e:
            print(f"Airdrop failed: {e}")
            # If airdrop fails, we can't continue the episode.
            # Consider a more robust retry mechanism.
            return None, {"error": "Airdrop failed"}

        observation = await self._get_observation()
        info = {} # No extra info on reset
        return observation, info

    async def step(self, tx: VersionedTransaction, signers: list[Keypair]):
        """
        Executes a pre-built transaction on the Solana network.
        This is the core function of the low-level environment.
        """
        try:
            sig = await self.client.send_transaction(tx, *signers)
            result = await self.client.get_transaction(sig.value, commitment="confirmed")
            
            if not result or not result.value:
                 raise Exception("Transaction result not found")

            # The result from get_transaction is a dict, not an object with attributes
            tx_receipt = {
                "meta": result.value.transaction.meta.to_json(),
                "transaction": result.value.transaction.transaction.to_json(),
            }
            
        except Exception as e:
            print(f"Error sending transaction: {e}")
            # Return a dummy error structure if the transaction fails to execute
            obs = await self._get_observation()
            return obs, None, True, {"error": str(e)} # Terminate on RPC error

        obs = await self._get_observation(last_tx_result=tx_receipt)
        
        # The low-level env doesn't compute rewards, it just returns the outcome.
        # The Voyager layer will be responsible for reward calculation.
        # We return the raw transaction receipt for the high-level env to process.
        return obs, tx_receipt, False, {}

    def render(self, mode="human"):
        print("Rendering not implemented for this environment.")
        pass

    def close(self):
        self._stop_test_validator()
        asyncio.run(self.client.close())
        print("SurfpoolEnv closed.")

if __name__ == '__main__':
    # Example of how to use the low-level environment directly
    async def main():
        env = SurfpoolEnv()
        obs, info = await env.reset()
        print("Environment reset.")
        print("Initial Observation:", obs)

        if obs is not None:
            # Create a simple transfer transaction to test the step function
            recipient = Keypair().pubkey()
            instruction = transfer(
                TransferParams(
                    from_pubkey=env.agent_keypair.pubkey(),
                    to_pubkey=recipient,
                    lamports=1000
                )
            )
            
            latest_blockhash = await env.client.get_latest_blockhash()
            message = MessageV0.try_compile(
                payer=env.agent_keypair.pubkey(),
                instructions=[instruction],
                address_lookup_table_accounts=[],
                recent_blockhash=latest_blockhash.value.blockhash
            )
            tx = VersionedTransaction(message, [env.agent_keypair])

            print("\nExecuting a test transaction...")
            obs, receipt, terminated, info = await env.step(tx, [env.agent_keypair])
            
            print("\n--- Step Result ---")
            print("Observation:", obs)
            print("Transaction Receipt:", receipt)
            print("Terminated:", terminated)
            print("Info:", info)

        await env.close()

    asyncio.run(main())
