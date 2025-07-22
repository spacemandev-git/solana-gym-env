import re
import time
import logging
from javascript import require
from langchain.schema import SystemMessage, HumanMessage
import pdb

from voyager.prompts import load_prompt
import voyager.utils as U
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
from langchain.vectorstores import Chroma

class CurriculumAgent:
    def __init__(
        self, 
        model_name: str,
        temperature=0,
        qa_model_name="gpt-3.5-turbo",
        qa_temperature=0,
        request_timeout=120,
        ckpt_dir="ckpt",
        resume=False,
        mode="auto",
        warm_up=None,
    ):
        self.llm = ChatOpenAI(
            model_name=model_name,
            temperature=temperature,
            request_timeout=request_timeout,
        )
        self.qa_llm = ChatOpenAI(
            model_name=qa_model_name,
            temperature=qa_temperature,
            request_timeout=request_timeout,
        )
        assert mode in ["auto", "manual"], "Mode must be either auto or manual"
        self.mode = mode
        self.ckpt_dir = ckpt_dir
        U.f_mkdir("self.ckpt_dir/curriculum/vectordb")
        if resume:
            logging.info(
                f"\033[35mLoading Curriculum Agent from {ckpt_dir}/curriculum\033[0m"
            )
            self.completed_tasks = U.load_json(f"{ckpt_dir}/curriculum/completed_tasks.json")
            self.failed_tasks = U.load_json(f"{ckpt_dir}/curriculum/failed_tasks.json")
            self.qa_cache = U.load_json(f"{ckpt_dir}/curriculum/qa_cache.json")
        else:
            self.completed_tasks = []
            self.failed_tasks = []
            self.qa_cache = {}

        # vectordb for qa cache
        self.qa_cache_questions_vectordb = Chroma(
            collection_name="qa_cache_questions_vectordb",
            embedding_function=OpenAIEmbeddings(),
            persist_directory=f"{ckpt_dir}/curriculum/vectordb",
        )
        assert self.qa_cache_questions_vectordb._collection.count() == len(
            self.qa_cache
        ), (
            f"Curriculum Agent's qa cache question vectordb is not synced with qa_cache.json.\n"
            f"There are {self.qa_cache_questions_vectordb._collection.count()} questions in vectordb "
            f"but {len(self.qa_cache)} questions in qa_cache.json.\n"
            f"Did you set resume=False when initializing the agent?\n"
            f"You may need to manually delete the qa cache question vectordb directory for running from scratch.\n"
        )

        if not warm_up:
            warm_up = self.default_warmup
        # todo(ngundotra): add warmup
        self.warm_up = warm_up

    @property
    def default_warmup(self):
        return {}

    @property
    def curriculum_observations(self):
        return [
        ]

    @property
    def progress(self):
        return len(self.completed_tasks)

    def render_system_message(self):
        system_message = SystemMessage(
            content=load_prompt("curriculum")
        )
        assert isinstance(system_message, SystemMessage), "System message must be a SystemMessage object"
        return system_message

    def render_observation(self, *, events):
        assert events[-1][0] == "observe", "Last event must be observe"
        observation = ""
        return observation

    def render_human_message(self, *, events):
        """todo(ngundotra): flesh out observation"""
        content = ""
        observation = self.render_observation(events=events)
        pdb.set_trace()
        return HumanMessage(content=content)

    def propose_next_task(self, *, events, max_retries=5):
        if self.progress == 0 and self.mode == "auto":
            task = "Mine 1 wood log"
            context = "You can mine one of oak, birch, spruce, jungle, acacia, dark oak or mangrove logs."
            return task, context

        # hard code task when invenv
        messages = [
            self.render_system_message(),
            self.render_human_message(
                events=events
            )
        ]
        if self.mode == "auto":
            return self.propose_next_ai_task()
        elif self.mode == "manual":
            return self.propose_next_ai_task(messages=messages, max_retries=max_retries)
        else:
            raise ValueError(f"Invalid curriculum agent mode: {self.mode}")

    def propose_next_ai_task(self, *, messages, max_retries=5):
        if max_retries == 0:
            raise RuntimeError("Max retries reached, failed to propose ai task.")
        curriculum = self.llm(messages).contet
        logging.info(
           f"\033[31m****Curriculum Agent ai message****\n{curriculum}\033[0m" 
        )

        try:
            response = self.parse_ai_message(curriculum)
            assert "next_task" in response
            context = self.get_task_context(response["next_task"])
            return response["next_task"], context
        except Exception as e:
            logging.info(
                f"\033[31m****Curriculum Agent error****\n{e}\033[0m"
            )
            return self.propose_next_ai_task(messages=messages, max_retries=max_retries - 1)

    def parse_ai_message(self, message):
        task = ""
        for line in message.split("\n"):
            if line.startswith("Task:"):
                task = line[5:].replace(".", "").strip()
        assert task, "Task not found in Curriculum Agent response"
        return {"next_task": task}

    def propose_next_manual_Task(self):
        confirmed = False
        task, context = "",""
        while not confirmed:
            task = input("Enter task: ")
            context = input("Enter context: ")
            logging.info(
                f"Task: {task}\nContext: {context}"
            )
            confirmed = input("Confirm (y/n): ").lower() in ["y", ""]
        return task, context

    def update_exploration_progress(self, info):
        # pdb.set_trace()
        task = info["task"]
        if info["success"]:
            logging.info(
               f"\033[35mCompleted task {task}.\033[0m" 
            )
            self.completed_tasks.append(task)
        else:
            logging.info(
                f"\033[35mFailed to complete task {task}. Skipping to next task.\033[0m"
            )
            self.failed_tasks.append(task)
        self.clean_up_tasks()

    def clean_up_tasks(self):
        updated_completed_tasks = []
        updated_failed_tasks = self.failed_tasks
        # dedup but keep order
        for task in self.completed_tasks:
            if task not in updated_completed_tasks:
                updated_completed_tasks.append(task)
        
        # remove completed tasks from failed tasks
        for task in updated_completed_tasks:
            while task in updated_failed_tasks:
                updated_failed_tasks.remove(task)

        self.completed_tasks = updated_completed_tasks
        self.failed_tasks = updated_failed_tasks

        U.dump_json(
            self.completed_tasks,
            f"{self.ckpt_dir}/curriculum/completed_tasks.json",
        )
        U.dump_json(
            self.failed_tasks,
            f"{self.ckpt_dir}/curriculum/failed_tasks.json",
        )

    def decompose_task(self, task, events):
        messages = [
            SystemMessage(
                content=load_prompt("curriculum_task_decomposition")
            ),
            self.render_human_message(events=events),
            HumanMessage(content=f"Final task: {task}")
        ]
        logging.info(
            f"\033[31m****Curriculum Agent task decomposition****\nFinal task: {task}\033[0m"
        )
        response = self.llm(messages).content
        logging.info(
           f"\033[31m****Curriculum Agent task decomposition****\n{response}\033[0m" 
        )
        return U.fix_and_parse_json(response)

    def run_qa(self, *, events):
        questions_new, _ = self.run_qa_step1_ask_questions(
            events=events
        )
        questions = []
        answers = []
        for question in questions_new:
            if self.qa_cache_questions_vectordb._collection.count() > 0:
                docs_and_scores = (
                    self.qa_cache_questions_vectordb.similarity_search_with_score(
                        question, k=1
                    )
                )
                if docs_and_scores and docs_and_scores[0][1] < 0.05:
                    question_cached = docs_and_scores[0][0].page_content
                    assert question_cached in self.qa_cache
                    answer_cached = self.qa_cache[question_cached]
                    questions.append(question_cached)
                    answers.append(answer_cached)
                    continue
            answer = self.run_qa_step2_answer_questions(question)
            assert question not in self.qa_cache
            self.qa_cache[question] = answer
            self.qa_cache_questions_vectordb.add_texts(
                texts=[question],
            )
            U.dump_json(self.qa_cache, f"{self.ckpt_dir}/curriculum/qa_cache.json")
            self.qa_cache_questions_vectordb.persist()
            questions.append(question)
            answers.append(answer)
        assert len(questions_new) == len(questions) == len(answers)
        return questions, answers

    def get_task_context(self, task):
        question = (
            f"How to {task.replace('_', ' ').strip().lower()} in Minecraft?"
        )
        if question in self.qa_cache:
            answer = self.qa_cache[question]
        else:
            answer = self.run_qa_step2_answer_questions(question=question)
            self.qa_cache[question] = answer
            self.qa_cache_questions_vectordb.add_texts(
                texts=[question],
            )
            U.dump_json(self.qa_cache, f"{self.ckpt_dir}/curriculum/qa_cache.json")
            self.qa_cache_questions_vectordb.persist()
        context = f"Question: {question}\nAnswer: {answer}"
        return context


    def render_system_message_qa_step1_ask_questions(self):
        return SystemMessage(content=load_prompt("curriculum_qa_step1_ask_questions"))

    def render_human_message_qa_step1_ask_questions(self, *, events):
        observation = self.render_observation(
            events=events
        )
        content = ""
        for key in self.curriculum_observations:
            content += observation[key]
        return HumanMessage(content=content)

    def run_qa_step1_ask_questions(self, *, events):
        biome = "beep"
        questions = [
            f"What are the blocks that I can find in the {biome} in Minecraft?",
            f"What are the items that I can find in the {biome} in Minecraft?",
            f"What are the mobs that I can find in the {biome} in Minecraft?",
        ]
        concepts = [biome, biome, biome]
        messages = [
            self.render_system_message_qa_step1_ask_questions(),
            self.render_human_message_qa_step1_ask_questions(
                events=events
            )
        ]
        qa_response = self.qa_llm(messages).content
        try:
            pattern = r"Question \d+: (.+)\nConcept \d+: (.+)"
            pairs = re.findall(pattern, qa_response)
            questions_new = [pair[0] for pair in pairs]
            concepts_new = [pair[1] for pair in pairs]
            assert len(questions_new) == len(concepts_new)
            questions.extend(questions_new)
            concepts.extend(concepts_new)
        except Exception as e:
            logging.info(
                f"\033[35mError parsing curriculum response for "
                f"QA step 1 ask questions: {e}.\033[0m"
            )
        return questions, concepts

    def render_system_message_qa_step2_answer_questions(self):
        return SystemMessage(content=load_prompt("curriculum_qa_step2_answer_questions"))

    def render_human_message_qa_step2_answer_questions(self, question):
        content = f"Question: {question}"
        return HumanMessage(content=content)

    def run_qa_step2_answer_questions(self, question):
        messages = [
            self.render_system_message_qa_step2_answer_questions(),
            self.render_human_message_qa_step2_answer_questions(question=question),
        ]
        logging.info(
           f"\033[35mCurriculum Agent Question: {question}\033[0m" 
        )
        qa_answer = self.qa_llm(messages).content
        logging.info(
            f"\033[35mCurriculum Agent : {qa_answer}\033[0m"
        )
        return qa_answer
