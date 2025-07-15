
import json
import logging
import os
import pdb

from openai import AsyncOpenAI
from skill_manager.ts_skill_manager import TypeScriptSkillManager
from surfpool_env import SurfpoolEnv
from known_programs import KNOWN_PROGRAM_IDS

SYSTEM_PROMPT = """
You are a Solana expert, attempting to maximize your understanding of Solana program ecosystem.
Your goal is to succesfully interact with as many programs as possible using as many different instructions as possible.
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
import {{ Transaction, SystemProgram, PublicKey, LAMPORTS_PER_SOL }} from '@solana/web3.js';

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

=== IMPORTANT NOTES ===
1. Each skill must create exactly ONE unsigned transaction
2. The transaction will be signed and sent by the environment
3. Start simple - a transfer to a protocol address counts as interaction
4. Return the base64 encoded serialized transaction
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
        self.skills = TypeScriptSkillManager(skill_root="./skills")
        # self.model = 'tencent/hunyuan-a13b-instruct:free'
        # self.model = "x-ai/grok-3-mini"
        # self.model = "mistralai/mistral-small-3.2-24b-instruct:free"
        # self.model = "google/gemini-2.5-pro-exp-03-25"
        # self.model = "deepseek/deepseek-chat-v3-0324:free"
        self.model = "openai/gpt-4o-mini"
        # self.model = "mistralai/devstral-small"
        # self.model = "moonshotai/kimi-k2:free"
        # "google/gemma-3n-e2b-it:free"
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key
        )

    async def step(self, last_observation):
        self.messages.append({
            'role': 'user',
            'content': f"Last observation: {last_observation}"
        })

        logging.info(f"Messages: {self.messages}")
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            stream=False,
            tools=FUNCTIONS,
            tool_choice="auto",
        )
        if response.choices[0].finish_reason == "tool_calls":
            function_call = response.choices[0].message.tool_calls[0].function
            function_name = function_call.name
            function_args = json.loads(function_call.arguments)
            logging.info(f"Function call: {function_name} with args: {function_args}")
            pdb.set_trace()
            if function_name == "executeSkill":
                skill_name = function_args["skill_name"]
                skill_code = self.skills.get_skill(skill_name)
            elif function_name == "fetchTransactions":
                program_id = function_args["program_id"]
                transactions = await self.env.fetch_transactions(program_id)
                logging.info(f"Transactions: {transactions}")
            elif function_name == "writeSkill":
                skill_name = function_args["skill_name"]
                skill_code = function_args["skill_code"]
            elif function_name == "readSkills":
                skills = self.skills.get_skills()
                logging.info(f"Skills: {skills}")
            else:
                raise ValueError(f"Unexpected function name: {function_name}")
                # self.messages.append({
                #     'role': 'function',
                #     'name': function_name,
                #     'content': skill_code

            # if function_name == "executeSkill":
            #     skill_name = function_args["skill_name"]
            #     skill_code = self.skills.get_skill(skill_name)
        else:
            raise ValueError(f"Unexpected finish reason: {response.choices[0].finish_reason}")

        obs, reward, terminated, truncated, info = await self.env.step()

        return self.messages, reward, terminated, truncated, info

    async def rollout(self):
        logging.info("Starting rollout")
        observation, info = await self.reset()
        logging.info(f"Observation: {observation}")
        # while True:
        messages, reward, terminated, truncated, info = await self.step(observation)
        #     logging.info(f"Observation: {observation}")
        #     if terminated or truncated:
        #         break
        # return messages, reward, terminated, truncated, info
        return False

    async def reset(self):
        observation, info = await self.env.reset()
        self.messages = [{
            'role': 'system',
            'content': SYSTEM_PROMPT.format(agent_pubkey=self.env.agent_keypair.pubkey()),
        }]
        return observation, info

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    async def main():
        explorer = SimpleExplorer()
        logging.info("Starting rollout")
        await explorer.rollout()
    
    asyncio.run(main())
    # import json
    # print(json.dumps(FUNCTIONS, ensure_ascii=False, indent=2).replace("\'", "\""))