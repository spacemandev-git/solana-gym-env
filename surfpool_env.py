import gymnasium as gym
import numpy as np
import subprocess
import asyncio
from contextlib import asynccontextmanager
import logging
import json
from typing import Optional, Callable, Set
from pathlib import Path
import shutil
import os
import signal


from gymnasium import spaces
from solana.rpc.api import Client as RpcClient
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.system_program import transfer, TransferParams
from solders.message import MessageV0
from solders.hash import Hash
from solders.pubkey import Pubkey

# TODO: These should be configured based on the specific protocols and tokens
MAX_TOKENS = 10  # Maximum number of different tokens in the wallet
NUM_PROTOCOLS = 20 # Number of known protocols the agent can interact with
MAX_INSTRUCTIONS_PER_PROTOCOL = 5 # Max instructions per protocol

READY_TOKEN = b"Connection established."          # surfpool prints this when ready
# ──────────────────────────────────────────────────────────────────────────
#  Async context-manager that owns the Surfpool process life-cycle
# ──────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def _surfpool_validator(rpc_url: str, *, backtrace: bool = True):
    """
    Async context manager that:
      • launches `surfpool start -u <rpc_url>`
      • waits until it prints the READY_TOKEN
      • yields the process object while the validator is live
      • always terminates the whole process-group on exit
    """
    if shutil.which("surfpool") is None:
        raise FileNotFoundError(
            "'surfpool' not found in PATH; install it or adjust PATH."
        )

    env = os.environ.copy()
    if backtrace:
        env["RUST_BACKTRACE"] = "1"
    # Disable raw-mode attempts in many TTY crates (crossterm/termion)
    env["CROSSTERM_DISABLE_RAW_MODE"] = "1"

    cmd = ["surfpool", "start", "--no-tui", "-u", rpc_url]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,        # own pgid → easy to kill
        env=env,
    )
    logging.info("surfpool [%s] launched", proc.pid)

    try:
        # Block until Surfpool is actually serving RPC or abort early
        while True:
            line = await proc.stdout.readline()
            if not line:                       # died before ready
                raise RuntimeError("surfpool exited before becoming ready")
            logging.debug("[surfpool] %s", line.decode().rstrip())
            if READY_TOKEN in line:
                break
        yield proc                             # ── control goes back to caller
    finally:
        if proc.returncode is None:
            logging.info("Stopping surfpool [%s] …", proc.pid)
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=8)
            except asyncio.TimeoutError:
                logging.warning("surfpool unresponsive; killing")
                os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
        logging.info("surfpool shut down")

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
        # self.observation_space = spaces.Dict({
        #     "wallet_balances": spaces.Box(low=0, high=np.inf, shape=(MAX_TOKENS,), dtype=np.float64),
        #     "agent_pubkey": spaces.Box(low=0, high=255, shape=(32,), dtype=np.uint8),
        #     "block_height": spaces.Box(low=0, high=np.inf, shape=(1,), dtype=np.int64),
        #     "block_timestamp": spaces.Box(low=0, high=np.inf, shape=(1,), dtype=np.int64),
        #     "last_tx_success": spaces.Discrete(2),
        #     "last_tx_error": spaces.Text(max_length=128),
        #     "available_protocols": spaces.Sequence(
        #         spaces.Dict({
        #             "protocol_id": spaces.Discrete(NUM_PROTOCOLS),
        #             "address": spaces.Box(low=0, high=255, shape=(32,), dtype=np.uint8),
        #         })
        #     )
        # })
        
        # This action space is a placeholder. The Voyager layer will use its own.
        # self.action_space = spaces.Discrete(1)
        self.last_observation = None
        self.last_tx_receipt = None
        self._validator_cm = None       # will hold the context-manager
        self._validator_proc = None     # the running subprocess.Process


    async def _get_observation(self, last_tx_result=None):
        # In a real implementation, you would fetch this data from the chain
        obs = {
            "wallet_balances": np.zeros(MAX_TOKENS, dtype=np.float64),
            "agent_pubkey": str(self.agent_keypair.pubkey()),
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
            logging.error(f"Error getting observation: {e}", exc_info=True)

        if last_tx_result:
            # The receipt is a JSON string, so we need to parse it
            receipt_dict = json.loads(last_tx_result)
            if receipt_dict.get("meta", {}).get("err") is None:
                obs["last_tx_success"] = 1
            else:
                obs["last_tx_success"] = 0
                obs["last_tx_error"] = str(receipt_dict.get("meta", {}).get("err"))

        self.last_observation = obs
        return obs

    async def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        
        if self._validator_cm:
            await self._validator_cm.__aexit__(None, None, None)

        # 2. Launch a fresh validator and wait until it’s live
        self._validator_cm = _surfpool_validator(self.rpc_url)
        self._validator_proc = await self._validator_cm.__aenter__()

        # Create a new agent for the episode
        self.agent_keypair = Keypair()
        
        # Fund the agent
        try:
            logging.info(f"Airdropping SOL to {self.agent_keypair.pubkey()}...")
            airdrop_sig = await self.client.request_airdrop(self.agent_keypair.pubkey(), 2 * 10**9) # 2 SOL
            await self.client.confirm_transaction(airdrop_sig.value, "confirmed", 30.0)
            logging.info("Airdrop successful.")
        except Exception as e:
            logging.error(f"Airdrop failed: {e}", exc_info=True)
            return None, {"error": f"Airdrop failed: {e}"}

        self.last_tx_receipt = None
        observation = await self._get_observation()
        info = {} # No extra info on reset
        return observation, info

    async def step(self, tx: VersionedTransaction):
        """
        Executes a pre-signed transaction on the Solana network.
        This is the core function of the low-level environment.
        The transaction must be signed before being passed to this method.
        """
        self.last_tx_receipt = None
        try:
            # The modern send_transaction expects a signed transaction
            sig = await self.client.send_transaction(tx)
            
            # The commitment level for confirmation should be high enough
            await self.client.confirm_transaction(sig.value, "confirmed", 30.0)
            
            # Fetch the confirmed transaction
            result = await self.client.get_transaction(sig.value, commitment="confirmed")
            
            if not result or not result.value:
                 raise Exception(f"Transaction result not found for signature {sig.value}")

            tx_receipt = result.value.transaction.to_json()
            self.last_tx_receipt = tx_receipt

        except Exception as e:
            logging.error(f"Error sending transaction: {e}", exc_info=True)
            obs = await self._get_observation()
            # Pass the error in the info dict
            return obs, None, True, {"error": str(e)}
        except BaseException as e:
            logging.error(f"Panic in send_transaction: {e}", exc_info=True)
            obs = await self._get_observation()
            # Pass the error in the info dict
            # For now, treat this specific error as a success for testing
            if "missing field `data`" in str(e):
                # This is likely a parsing issue with the response
                # The transaction might have actually succeeded
                return obs, None, False, {"error": str(e), "possible_success": True}
            return obs, None, True, {"error": str(e)}

        self.last_tx_receipt = tx_receipt
        obs = await self._get_observation(last_tx_result=tx_receipt)
        
        return obs, tx_receipt, False, {}

    def render(self, mode="human"):
        logging.info("Rendering not implemented for this environment.")
        pass

    async def close(self):
        if self._validator_cm:
            await self._validator_cm.__aexit__(None, None, None)
            self._validator_cm = self._validator_proc = None

            if self.client:
                await self.client.close()
            logging.info("SurfpoolEnv closed.")
        logging.info("SurfpoolEnv closed.")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    async def main():
        env = SurfpoolEnv()
        obs, info = await env.reset()
        logging.info("Environment reset.")
        logging.info(f"Initial Observation: {obs}")

        if obs is not None:
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

            logging.info("\nExecuting a test transaction...")
            obs, receipt, terminated, info = await env.step(tx)
            
            logging.info("\n--- Step Result ---")
            logging.info(f"Observation: {obs}")
            logging.info(f"Transaction Receipt: {receipt}")
            logging.info(f"Terminated: {terminated}")
            logging.info(f"Info: {info}")

        await env.close()

    asyncio.run(main())
