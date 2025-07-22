# TODO(ngundotra): figure out what sort of events should go in the chatlog
import pdb
import re
import time

import voyager.utils as U
from voyager.prompts import load_prompt
from javascript import require
from langchain_openai import ChatOpenAI
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
            model=model_name,
            temperature=temperature,
            request_timeout=request_timeout,
        )

    def render_system_message(self, skills=[]):
        system_template = load_prompt("action_template")
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
        chat_messages = []
        error_messages = []
        assert events[-1][0] == "observe", "Last event must be observe"
        for i, (event_type, event) in enumerate(events):
            # todo: add other event types
            if event_type == "observe":
                # todo: add observation
                assert i == len(events) - 1, "observe must be the last event"
            
        observation = ""

        if code:
            observation += f"Code from the last round:\n{code}\n\n"
        else:
            observation += f"Code form the last round: No code in the first round\n\n"
        
        if self.execution_error:
            if error_messages:
                error = "\n".join(error_messages)
                observation += f"Execution error:\n{error}\n\n"
            else:
                observation += f"Execution error: No error\n\n"
            
        if self.chat_log:
            if chat_messages:
                chat_log = "\n".join(chat_messages)
                observation += f"Chat log: {chat_log}\n\n"
            else:
                observation += f"Chat log: None\n\n"
            
        # todo: flesh out observation here
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

                # todo(ngundotra): make this more flexible
                assert (
                    len(main_function["params"]) == 1 and
                    main_function["params"][0].name == "bot"
                ), f"Main function {main_function['name']} must have exactly one parameter named 'bot'."
                program_code = "\n\n".join(function["body"] for function in functions)
                exec_code = f"await {main_function['name']}();"
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