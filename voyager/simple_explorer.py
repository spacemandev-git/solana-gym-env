
from datetime import datetime
import json
import logging
import os
import pdb
import uuid

from openai import AsyncOpenAI
from skill_manager.ts_skill_manager import TypeScriptSkillManager
from voyager.surfpool_env import SurfpoolEnv
from voyager.known_programs import KNOWN_PROGRAM_IDS
from solders.transaction import Transaction
import base64

SYSTEM_PROMPT = """
You are an expert Solana developer, attempting to show off how many different programs you can interact with.
Your goal is to succesfully interact with as many programs as possible using with as many different instructions as possible.
You will be given a list of programs that we recommend you interact with, but you are free to interact with any program you want.
We recommend that you start by interacting with the programs in the list, and then move on to other programs.

=== HOW TO INTERACT WITH PROGRAMS ===
To get credit for discovering a program, you need to create a base64 serialized transaction that executes
an instruction on that program at some point during execution. The transaction must include the program in its account keys.

Important clarification:
- SystemProgram.transfer() is an instruction that interacts with the System Program (11111111111111111111111111111111)
- A transfer TO a program address using SystemProgram.transfer() does NOT count as interacting with that program
- To interact with a specific program, you must create an instruction where that program is the programId

Use the tools to learn how transactions work against different programs, and then write Typescript functions to create transactions 
for new programs and new instructions.

You get more points for interacting with new programs and new instructions.

=== TYPESCRIPT SKILL TEMPLATE ===
```typescript
// This is a template for a skill. You can use modify it as necessary to create a new skill.
// The default export needs to be a function that returns a base64 encoded transaction.
import {{ Transaction, SystemProgram, PublicKey, LAMPORTS_PER_SOL }} from '@solana/web3.js';
import {{ AnchorProvider, AnchorWallet, Wallet }} from '@coral-xyz/anchor';

export async function executeSkill(): Promise<string> {{
    const tx = new Transaction();
    
    // ================================
    // CREATE YOUR TRANSACTION HERE
    // ================================
    
    // Set transaction properties
    // Use a placeholder blockhash for now, it will be overridden by the environment automatically
    tx.recentBlockhash = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi";
    tx.feePayer = new PublicKey("{agent_pubkey}");
    
    // Serialize to base64
    const serializedTx = tx.serialize({{
        requireAllSignatures: false,
        verifySignatures: false
    }}).toString('base64');
    
    return serializedTx;
}}
```

The package json for the skill runner is:
```json
{{
  "name": "skill_runner",
  "module": "runSkill.ts",
  "type": "module",
  "devDependencies": {{
    "bun-types": "latest"
  }},
  "peerDependencies": {{
    "typescript": "^5.0.0"
  }},
  "dependencies": {{
    "@solana/web3.js": "^1.98.2",
    "@coral-xyz/anchor": "^0.30.1"
  }}
}}
```

=== IMPORTANT NOTES ===
1. Each skill must create exactly ONE unsigned transaction
2. The transaction will be signed and sent by the environment
3. Start simple - a transfer to a protocol address counts as interaction
4. Return the base64 encoded serialized transaction

=== PROTOCOL LIST ===
{protocol_list}
"""

FUNCTIONS = [
    {
        'type': 'function',
        # OpenRouter specific format for functions
        'function': {
            'name': 'executeSkill',
            'description': 'Executes a skill to return an unsigned base64 serialized transaction',
            'strict': True,
            'parameters': {
                'type': 'object',
                'properties': {
                    'skill_name': {
                        'type': 'string',
                        'description': 'The name of the skill to execute',
                    },
                },
                'additionalProperties': False,
                'required': ['skill_name'],
            },
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'fetchTransactions',
            'description': 'Fetches the transactions for a given program',
            'strict': True,
            'parameters': {
                'type': 'object',
                'properties': {
                    'program_id': {
                        'type': 'string',
                        'description': 'The program ID to fetch transactions for',
                    },
                },
                'required': ['program_id'],
                'additionalProperties': False,
            }
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'writeSkill',
            'description': 'Writes a skill to the file system',
            'strict': True,
            'parameters': {
                'type': 'object',
                'properties': {
                    'skill_name': {
                        'type': 'string',
                        'description': 'The name of the skill to write',
                    },
                    'skill_code': {
                        'type': 'string',
                        'description': 'The code of the skill to write',
                    },
                },
                'additionalProperties': False,
                'required': ['skill_name', 'skill_code'],
            },
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'readSkills',
            'description': 'Reads the skills from the file system',
            'strict': True,
            'parameters': {
                'type': 'object',
                'properties': {
                },
                'required': [],
                'additionalProperties': False,
            },
        }
    }
]

class SimpleExplorer():
    def __init__(self):
        self.env = SurfpoolEnv(rpc_url="https://api.mainnet-beta.solana.com")
        self.messages = []
        self.run_id = datetime.now().strftime("%y-%m-%d") + "_" + str(int(datetime.now().timestamp()))
        self.skills = TypeScriptSkillManager(skill_root=f"./skills/{self.run_id}")
        # self.model = 'tencent/hunyuan-a13b-instruct:free'
        self.model = "x-ai/grok-3-mini"
        # self.model = "mistralai/mistral-small-3.2-24b-instruct:free"
        # self.model = "google/gemini-2.5-pro-exp-03-25"
        # self.model = "deepseek/deepseek-chat-v3-0324:free"
        # self.model = "openai/gpt-4o-mini"
        # self.model = "mistralai/devstral-small"
        # self.model = "moonshotai/kimi-k2:free"
        # "google/gemma-3n-e2b-it:free"
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key
        )

    def write_trace(self, messages, reward):
        with open(f"traces/{self.run_id}.json", "w") as f:
            json.dump(messages, f, indent=2)
        with open(f"traces/{self.run_id}_reward.csv", "a") as f:
            f.write(f"{len(self.messages)},{reward}\n")

    async def step(self):
        finish_reason = "tool_calls"
        reward = 0.0
        while finish_reason == "tool_calls":
            # logging.info(f"Messages: {self.messages}")
            self.write_trace(self.messages, self.reward + reward)
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                stream=False,
                tools=FUNCTIONS,
                tool_choice="auto",
            )
            self.messages.append(response.choices[0].message.model_dump())
            self.write_trace(self.messages, self.reward + reward)
            
            done = False
            finish_reason = response.choices[0].finish_reason
            if finish_reason == "tool_calls":
                for tool_meta in response.choices[0].message.tool_calls:
                    tool_call = tool_meta.function
                    function_name = tool_call.name
                    function_args = json.loads(tool_call.arguments)
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_meta.id,
                        "name": function_name,
                        "content": ""
                    }
                    logging.info(f"Function call: {function_name} with args: {function_args}")
                    if function_name == "executeSkill":
                        skill_name = function_args["skill_name"]
                        skill_file_path = self.skills.get_skills().get(skill_name, None)
                        if skill_file_path is None:
                            tool_message["content"] = f"Skill {skill_name} not found"
                        else:
                            try:
                                # Pass agent pubkey and latest blockhash to skill execution
                                agent_pubkey = str(self.env.agent_keypair.pubkey())
                                
                                # Fetch latest blockhash before skill execution
                                blockhash_resp = await self.env.client.get_latest_blockhash()
                                latest_blockhash_str = str(blockhash_resp.value.blockhash)
                                
                                result = self.skills.execute_skill(skill_file_path, agent_pubkey=agent_pubkey, latest_blockhash=latest_blockhash_str)
                                tx_data = result.get("serialized_tx")
                                if not tx_data:
                                    tool_message["content"] = f"Error executing skill {skill_name}: {json.dumps(result)}"
                                else:
                                    # Get transaction data from skill result
                                    tx_bytes = base64.b64decode(tx_data)
                                    tx = Transaction.from_bytes(tx_bytes)
                                    
                                    # Sign with agent keypair
                                    # Fetch the latest blockhash from surfpool
                                    blockhash_resp = await self.env.client.get_latest_blockhash()
                                    latest_blockhash = blockhash_resp.value.blockhash
                                    
                                    tx.sign([self.env.agent_keypair], latest_blockhash)
                                    
                                    # Send transaction through surfpool
                                    obs, step_reward, _, _, info = await self.env.step(tx)
                                    reward += step_reward
                                    
                                    logging.info(f"Reward: {step_reward}, total reward: {reward}")
                                    tool_message["content"] = f"{json.dumps({ 'observation': obs, 'info': info, 'reward': step_reward })}"
                                            
                            except Exception as e:
                                logging.error(f"Error running skill {skill_id}: {e}")
                                tool_message["content"] = f"Exception in skill {skill_id}: {e}"

                    elif function_name == "fetchTransactions":
                        program_id = function_args["program_id"]
                        txs = await self.env.fetch_transactions(program_id)
                        tool_message["content"] = json.dumps(txs)
                    elif function_name == "writeSkill":
                        skill_name = function_args["skill_name"]
                        skill_code = function_args["skill_code"]
                        skill_id = self.skills.register(skill_name, skill_code)
                        tool_message["content"] = f"Skill {skill_name} written to file system with id {skill_id}"
                    elif function_name == "readSkills":
                        skills = list(self.skills.get_skills().keys())
                        tool_message["content"] = json.dumps(skills)
                        logging.info(f"Skills: {skills}")
                    else:
                        raise ValueError(f"Unexpected function name: {function_name}")
                    self.messages.append(tool_message)

        self.write_trace(self.messages, self.reward + reward)
        return reward, done

    async def rollout(self):
        logging.info("Starting rollout")
        observation, info = await self.reset()
        logging.info(f"Observation: {observation}")
        self.messages.append({
            'role': 'user',
            'content': f"Last observation: {observation}"
        })
        while True:
            reward, done = await self.step()
            self.reward += reward
            logging.info(f"Total reward: {self.reward}")
            if done:
                break
        return self.reward, False

    async def reset(self):
        observation, info = await self.env.reset()
        self.reward = 0.0
        self.messages = [{
            'role': 'system',
            'content': SYSTEM_PROMPT.format(
                agent_pubkey=self.env.agent_keypair.pubkey(), 
                # protocol_list=json.dumps(list(KNOWN_PROGRAM_IDS.keys()), indent=2)
                protocol_list="11111111111111111111111111111111, ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL, TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
            ),
        }]
        return observation, info

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    async def main():
        explorer = SimpleExplorer()
        logging.info("Starting rollout")
        total_reward, done = await explorer.rollout()
        logging.info(f"Total reward: {total_reward}")
    
    asyncio.run(main())
    # import json
    # print(json.dumps(FUNCTIONS, ensure_ascii=False, indent=2).replace("\'", "\""))