# TODO(ngundotra): figure out what sort of events should go in the chatlog
import os
import pdb
import re
import time
import logging

import voyager.utils as U
from voyager.prompts import load_prompt
from javascript import require
from langchain_openai import ChatOpenAI
# from langchain_anthropic import ChatAnthropic
from langchain.prompts import SystemMessagePromptTemplate
from langchain.schema import HumanMessage, AIMessage, SystemMessage

class ActionAgent:

    def __init__(
        self, 
        model_name: str,
        temperature=0,
        request_timeout=120,
        ckpt_dir="ckpt",
        resume=False,
        chat_log=True,
        execution_error=True
    ):
        self.ckpt_dir = ckpt_dir
        self.chat_log = chat_log
        self.execution_error = execution_error

        U.f_mkdir(f"{self.ckpt_dir}/action")
        # if resume:
        #     logging.info(f"\033[32mLoading Action Agent from {ckpt_dir}/action\033[0m")
        # else:
        self.llm = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            model=model_name,
            api_key=os.getenv("OPENROUTER_API_KEY"),
            temperature=temperature,
        )

    def render_system_message(self, skills=[]):
        system_template = load_prompt("action_template")
        # Debug logging
        logging.info(f"render_system_message received {len(skills)} skills")
        if skills:
            for i, skill in enumerate(skills):
                logging.info(f"Skill {i}: type={type(skill)}, len={len(skill) if isinstance(skill, str) else 'N/A'}, first 50 chars: {repr(skill[:50]) if isinstance(skill, str) else repr(skill)[:50]}")
        programs = "\n\n".join(skills)
        response_format = load_prompt("action_response_format")
        system_message_prompt = SystemMessagePromptTemplate.from_template(
            system_template
        )
        system_message = system_message_prompt.format(
            programs=programs, response_format=response_format
        )
        assert isinstance(system_message, SystemMessage)
        return system_message

    def render_human_message(
        self, *, events, code="", task="", context="", critique=''
    ):
        error_messages = []
        obs_data = {}
        
        # Process events to extract observations and errors
        for event_type, event in events:
            if event_type == "observe" and isinstance(event, dict):
                obs_data = event
            elif event_type == "error":
                if isinstance(event, dict):
                    # Extract detailed error information
                    error_msg = event.get("error", "Unknown error")
                    if event.get("trace"):
                        error_msg += f"\nTrace: {event['trace']}"
                    error_messages.append(error_msg)
                else:
                    error_messages.append(str(event))
            
        observation = ""

        if code:
            observation += f"Code from the last round:\n{code}\n\n"
        else:
            observation += f"Code from the last round: No code in the first round\n\n"
        
        if self.execution_error:
            if error_messages:
                error = "\n".join(error_messages)
                observation += f"Execution error:\n{error}\n\n"
            else:
                observation += f"Execution error: No error\n\n"
        
        # Add Solana-specific observations
        if obs_data:
            observation += f"Wallet balances: [SOL: {obs_data.get('sol_balance', 0):.4f}]\n"
            observation += f"Agent wallet address: {obs_data.get('agent_pubkey', 'Unknown')}\n"
            observation += f"Block height: {obs_data.get('block_height', 0)}\n"
            observation += f"Discovered protocols: {obs_data.get('discovered_programs', 0)}\n"
            
            # Add discovered instructions by program
            if obs_data.get('discovered_instructions_by_program'):
                observation += f"Discovered instructions by program: {obs_data['discovered_instructions_by_program']}\n"
            
            # Add transaction efficiency metrics
            observation += f"Last transaction instruction count: {obs_data.get('last_tx_instruction_count', 0)}\n"
            observation += f"Last transaction reward: {obs_data.get('last_tx_reward', 0)}\n"
            observation += f"Total reward: {obs_data.get('total_reward', 0)}\n"
            
            if obs_data.get('discovered_program_list'):
                observation += f"Discovered protocol list: {', '.join(obs_data['discovered_program_list'][:5])}"
                if len(obs_data['discovered_program_list']) > 5:
                    observation += f" (and {len(obs_data['discovered_program_list']) - 5} more)"
                observation += "\n"
            observation += "\n"
        
        observation += f"Task: {task}\n\n"
        if context:
            observation += f"Context: {context}\n\n"
        else:
            observation += f"Context: None\n\n"
        if critique:
            observation += f"Critique: {critique}\n\n"
        else:
            observation += f"Critique: None\n\n"
        
        return HumanMessage(content=observation)

    def process_ai_message(self, message):
        assert isinstance(message, AIMessage)

        retry = 3
        error = None
        while retry > 0:
            try:
                babel = require("@babel/core")
                babel_generator = require("@babel/generator")

                code_pattern = re.compile(r"```(?:javascript|js|typescript|ts)(.*?)```", re.DOTALL)
                code = "\n".join(code_pattern.findall(message.content))
                parsed = babel.parse(code)
                functions = []
                assert len(list(parsed.program.body)) > 0, "No functions found"
                for i, node in enumerate(parsed.program.body):
                    if node.type != 'FunctionDeclaration':
                        continue
                    node_type = (
                        "AsyncFunctionDeclaration"
                        if node["async"]
                        else "FunctionDeclaration"
                    )
                    # Try calling babel_generator.default if it exists
                    generator_func = babel_generator.default if hasattr(babel_generator, 'default') else babel_generator
                    generated = generator_func(node)
                    functions.append(
                        {
                            "name": node.id.name,
                            "type": node_type,
                            "body": generated.code,
                            "params": list(node["params"])
                        }
                    )
                # find the last async function
                main_function = None
                for function in reversed(functions):
                    if function["type"] == "AsyncFunctionDeclaration":
                        main_function = function
                        break
                assert (
                    main_function is not None
                ), "No async function found. Your main function must be async."

                # For Solana, we don't need any parameters
                # The function should just build and return a transaction
                assert (
                    len(main_function["params"]) == 0
                ), f"Main function {main_function['name']} must have no parameters for Solana transactions."
                program_code = "\n\n".join(function["body"] for function in functions)
                exec_code = f"return await {main_function['name']}();"
                return {
                    "program_code": program_code,
                    "program_name": main_function["name"],
                    "exec_code": exec_code,
                }
            except Exception as e:
                retry -= 1
                error = e
                time.sleep(1)
        return f"Error parsing action response (before program execution): {error}"

    def summarize_chatlog(self, events):
        chatlog = set()
        for event_type, event in events:
            if event_type == "something":
                if event:
                    chatlog.add(event)
        return "I also need " + ", ".join(chatlog) + "." if chatlog else ""

if __name__ == "__main__":
    agent = ActionAgent(model_name="gpt-4o-mini")
    message = AIMessage(
        '''Explain: Since this is the first task, there is no previous code or errors to explain.

Plan:
1) Find a wood log block.
2) Mine the wood log block.
Code:```javascript
async function mineWoodLog(bot) {
    // Find a wood log block
    const woodLogTypes = ['oak_log', 'birch_log', 'spruce_log', 'jungle_log', 'acacia_log', 'dark_oak_log', 'mangrove_log'];
    let woodLogBlock = null;
    for (let i = 0; i < woodLogTypes.length; i++) {
        woodLogBlock = bot.findBlock({
            matching: bot.mcData.blocksByName[woodLogTypes[i]].id,
            maxDistance: 32
        });
        if (woodLogBlock) break;
    }
    // If no wood log block is found, explore until one is found
    if (!woodLogBlock) {
        await exploreUntil(bot, [Math.random(), 0, Math.random()], 32, (block) => {
            return woodLogTypes.includes(block.name);
        });
        for (let i = 0; i < woodLogTypes.length; i++) {
            woodLogBlock = bot.findBlock({
                matching: bot.mcData.blocksByName[woodLogTypes[i]].id,
                maxDistance: 32
            });
            if (woodLogBlock) break;
        }
    }
    // Mine the wood log block
    if (woodLogBlock) {
        await mineBlock(bot, woodLogBlock.name, 1);
        bot.chat('Wood log mined.');
    } else {
        bot.chat('No wood log found.');
    }
}
```
'''
    )
    parsed = agent.process_ai_message(message)
    print(parsed)