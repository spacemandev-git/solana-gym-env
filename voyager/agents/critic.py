import logging
from voyager.prompts import load_prompt
from langchain.chat_models.openai import ChatOpenAI
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
            model=model_name,
            temperature=temperature,
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
        assert events[-1][0] == "observe", "Last event must be observe"
        for _, (event_type, event) in enumerate(events):
            if event_type == "error":
                logging.info(
                    f"\033[31mCritic Agent: Error occurs {event['onError']}\033[0m"
                )
                return None
                
        observation = ""
        observation += f"Task: {task}\n\n"
        if context:
            observation += f"Context: {context}\n\n"
        else:
            observation += f"Context: None\n\n"

        logging.info(
            f"\033[31m****Critic Agent human message****\n{observation}\033[0m"
        )
        return HumanMessage(content=observation)

    def human_check_task_success(self):
        confirmed = False
        success = False
        critique = ""
        while not confirmed:
            success = input("Succes? (y/n)")
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
        
        critic = self.llm(messages).contet
        logging.info(f"\033[31m****Critic Agent ai message****\n{critic}\033[0m")
        try:
            response = fix_and_parse_json(critic)
            assert response["success"] in ["True", "False"], "Critic Agent response must contain a boolean success field"
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
        human_message = self.render_system_message(
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