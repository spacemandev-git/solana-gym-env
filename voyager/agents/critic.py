import logging
import os
import pdb
from voyager.prompts import load_prompt
# from langchain.chat_models.openai import ChatOpenAI
from langchain_openai import ChatOpenAI
# from langchain_anthropic import ChatAnthropic
from langchain.schema import SystemMessage, HumanMessage

from voyager.utils.json_utils import fix_and_parse_json

class CriticAgent:

    def __init__(
        self, 
        model_name: str,
        temperature=0,
        request_timeout=120,
        mode="auto",
    ):
        self.llm = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            model=model_name,
            temperature=temperature,
            api_key=os.getenv("OPENROUTER_API_KEY"),
            request_timeout=request_timeout,
        )
        assert mode in ["auto", "manual"]
        self.mode = mode

    def render_system_message(self):
        return SystemMessage(
            content=load_prompt("critic")
        )
    
    def render_human_message(
        self,
        *,
        events,
        task,
        context,
    ):
        # Extract transaction result and balance info from events
        tx_result = "failed"
        tx_sig = None
        error_msg = None
        error_trace = None
        balances_before = {}
        balances_after = {}
        programs_interacted = []
        
        # pdb.set_trace()
        for event_type, event in events:
            if event_type == "observe" and isinstance(event, dict):
                logging.info(f"Event: {event}")
                # This is the observation data
                if "sol_balance" in event:
                    if not balances_before:
                        balances_before = {"SOL": event.get("sol_balance", 0)}
                    else:
                        balances_after = {"SOL": event.get("sol_balance", 0)}
            elif isinstance(event, dict):
                if "tx_sig" in event:
                    tx_result = "success"
                    tx_sig = event.get("tx_sig")
                    # Use programs_interacted directly from the info dict
                    if "programs_interacted" in event:
                        programs_interacted = event["programs_interacted"]
                elif "error" in event:
                    error_msg = event["error"]
                    if "trace" in event:
                        error_trace = event["trace"]
                
        observation = ""
        observation += f"Transaction Result: {tx_result}\n"
        if tx_sig:
            observation += f"Transaction Signature: {tx_sig}\n"
        if error_msg:
            observation += f"Error Message: {error_msg}\n"
        if error_trace:
            observation += f"Error Trace: {error_trace}\n"
        if balances_before.get('SOL', -1) != -1:
            observation += f"Wallet Balances Before: [SOL: {balances_before.get('SOL'):.4f}]\n"
        if balances_after.get('SOL', -1) != -1:
            observation += f"Wallet Balances After: [SOL: {balances_after.get('SOL'):.4f}]\n"
        if programs_interacted:
            observation += f"Programs Interacted: {programs_interacted}\n"
        observation += f"\nTask: {task}\n"
        if context:
            observation += f"\nContext: {context}\n"

        logging.info(
            f"\033[31m****Critic Agent human message****\n{observation}\033[0m"
        )
        return HumanMessage(content=observation)

    def human_check_task_success(self):
        confirmed = False
        success = False
        critique = ""
        while not confirmed:
            success = input("Success? (y/n)")
            success = success.lower() == "y"
            critique = input("Enter your critique: ")
            logging.info(f"Success: {success}\nCritique: {critique}")
            confirmed = input("Confirm? (y/n)") in ["y", ""]
        return success, critique

    def ai_check_task_success(self, messages, max_retries=5):
        if max_retries == 0:
            logging.info(
                "\033[31mFailed to parse Critic Agent response. Consider updating your prompt.\033[0m"
            )
            return False, ""

        if messages[1] is None:
            return False, ""
        
        critic = self.llm.invoke(messages).content
        logging.info(f"\033[31m****Critic Agent ai message****\n{critic}\033[0m")
        try:
            # pdb.set_trace()
            response = fix_and_parse_json(critic)
            assert response["success"] in ["True", "False", 'true', 'false', True, False], "Critic Agent response must contain a boolean success field"
            if "critique" not in response:
                response["critique"] = ""
            return response["success"], response["critique"]
        except Exception as e:
            logging.info(
                f"\033[31mError parsing critic response: {e} Trying again!\033[0m"
            )
            return self.ai_check_task_success(messages=messages, max_retries=max_retries - 1)

    def check_task_success(
        self, 
        *,
        events,
        task,
        context,
        max_retries=5,
    ):
        human_message = self.render_human_message(
            events=events,
            task=task,
            context=context,
        )

        messages = [
            self.render_system_message(),
            human_message,
        ]

        if self.mode == "manual":
            return self.human_check_task_success()
        elif self.mode == "auto":
            return self.ai_check_task_success(messages=messages, max_retries=max_retries)
        else:
            raise ValueError(f"Invalid critic agent mode: {self.mode}")