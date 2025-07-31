import os
import pdb
import re
import logging
from langchain.schema import SystemMessage, HumanMessage

from voyager.prompts import load_prompt
import voyager.utils as U
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from voyager.known_programs import KNOWN_PROGRAM_IDS

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
            base_url="https://openrouter.ai/api/v1",
            model=model_name,
            temperature=temperature,
            request_timeout=request_timeout,
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )
        self.qa_llm = ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            model=qa_model_name,
            temperature=qa_temperature,
            request_timeout=request_timeout,
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )
        assert mode in ["auto", "manual"], "Mode must be either auto or manual"
        self.mode = mode
        self.ckpt_dir = ckpt_dir
        U.f_mkdir(f"{self.ckpt_dir}/curriculum/vectordb")
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
        # pdb.set_trace()
        assert events[-1][0] == "observe", "Last event must be observe"
        obs_data = events[-1][1]
        
        # Handle double-wrapped observation from _get_observation
        if isinstance(obs_data, list) and len(obs_data) > 0 and obs_data[0][0] == "observe":
            obs_data = obs_data[0][1]
        
        # Build a comprehensive observation for the curriculum agent
        observation = f"Wallet balances: SOL={obs_data.get('sol_balance', 0):.3f}\n"
        observation += f"Block height: {obs_data.get('block_height', 0)}\n"
        observation += f"Total reward earned: {obs_data.get('total_reward', 0)}\n"
        observation += f"Unique instructions discovered: {obs_data.get('unique_instructions_found', 0)}\n"
        observation += f"Discovered protocols: {obs_data.get('discovered_programs', 0)} unique programs\n"
        observation += f"Known protocols: {', '.join(obs_data.get('discovered_program_list', []))}\n"
        
        # CRITICAL: Add discovered instructions by program so AI knows what NOT to repeat
        discovered_by_program = obs_data.get('discovered_instructions_by_program', {})
        if discovered_by_program:
            observation += "\nDiscovered instructions by program:\n"
            for prog_id, instruction_ids in discovered_by_program.items():
                prog_short = prog_id[:4] + "..." + prog_id[-4:] if len(prog_id) > 10 else prog_id
                observation += f"  - {prog_short}: instruction IDs {sorted(instruction_ids)}\n"
        
        # Add available programs to explore
        if KNOWN_PROGRAM_IDS:
            # Show a sample of unexplored programs (only those with names)
            unexplored_programs = []
            for prog_id, prog_name in KNOWN_PROGRAM_IDS.items():
                if prog_name and prog_name.strip() and prog_id not in discovered_by_program:
                    unexplored_programs.append(f"{prog_name} ({prog_id[:8]}...)")
                if len(unexplored_programs) >= 10:  # Show first 10 unexplored
                    break
            
            if unexplored_programs:
                total_unexplored = sum(1 for pid, pname in KNOWN_PROGRAM_IDS.items() 
                                     if pname and pname.strip() and pid not in discovered_by_program)
                observation += f"\nAvailable programs to explore (showing {len(unexplored_programs)} of {total_unexplored} unexplored):\n"
                for prog in unexplored_programs:
                    observation += f"  - {prog}\n"
        
        observation += f"\nCompleted tasks so far: {', '.join(self.completed_tasks[-5:])}\n"  # Last 5 tasks
        observation += f"Failed tasks that are too hard: {', '.join(self.failed_tasks[-3:])}\n"  # Last 3 failures
        
        # Add reward information from recent events
        recent_rewards = []
        for event_type, event_data in events[-10:]:  # Look at last 10 events
            if event_type == "info" and isinstance(event_data, dict):
                if "programs_interacted" in event_data:
                    observation += f"Recent transaction used: {', '.join(event_data['programs_interacted'])}\n"
                if "reward" in event_data:
                    recent_rewards.append(event_data["reward"])
        
        if recent_rewards:
            observation += f"Recent transaction rewards: {recent_rewards}\n"
        
        return observation

    def render_human_message(self, *, events):
        """todo(ngundotra): flesh out observation"""
        observation = self.render_observation(events=events)
        # pdb.set_trace()
        return HumanMessage(content=observation)

    def propose_next_task(self, *, events, max_retries=5):
        if self.progress == 0 and self.mode == "auto":
            task = "Transfer 0.1 SOL to a new address"
            context = "Create a simple SOL transfer transaction. Generate a random recipient address using Keypair.generate().publicKey for testing."
            return task, context

        # hard code task when invenv
        messages = [
            self.render_system_message(),
            self.render_human_message(
                events=events
            )
        ]
        if self.mode == "auto":
            return self.propose_next_ai_task(messages=messages, max_retries=max_retries)
        elif self.mode == "manual":
            return self.propose_next_ai_task(messages=messages, max_retries=max_retries)
        else:
            raise ValueError(f"Invalid curriculum agent mode: {self.mode}")

    def propose_next_ai_task(self, *, messages, max_retries=5):
        if max_retries == 0:
            raise RuntimeError("Max retries reached, failed to propose ai task.")
        curriculum = self.llm.invoke(messages).content
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
        # For simple/common operations, provide minimal context to speed up exploration
        simple_tasks = ["transfer", "create account", "create token account", "swap", "close account", "mint", "burn", "approve"]
        if any(simple in task.lower() for simple in simple_tasks):
            # Provide quick programmatic context without lengthy Q&A
            context_map = {
                "transfer": "Use web3.SystemProgram.transfer({fromPubkey, toPubkey, lamports}) for SOL. Generate random recipient: web3.Keypair.generate().publicKey. For SPL tokens use Token.transfer().",
                "create account": "For a new SOL account, just transfer SOL to a new address (web3.Keypair.generate().publicKey). Use SystemProgram.createAccount() only for data accounts with specific space requirements.",
                "create token account": "Use getOrCreateAssociatedTokenAccount() from @solana/spl-token, or create manually with TOKEN_PROGRAM_ID instructions.",
                "swap": "Use DEX SDK (Orca/Raydium). Basic pattern: 1) Get pool info 2) Calculate amounts 3) Create swap instruction 4) Add to transaction.",
                "close account": "Use TOKEN_PROGRAM_ID closeAccount instruction to close SPL token accounts and recover rent to owner.",
                "mint": "Use TOKEN_PROGRAM_ID mintTo instruction. Requires mint authority signature.",
                "burn": "Use TOKEN_PROGRAM_ID burn instruction to destroy tokens from an account.",
                "approve": "Use TOKEN_PROGRAM_ID approve instruction to delegate spending authority."
            }
            for key, value in context_map.items():
                if key in task.lower():
                    return f"Task: {task}\nProgrammatic approach: {value}"
        
        # For complex tasks, use the Q&A system
        question = (
            f"How to {task.replace('_', ' ').strip().lower()} on Solana?"
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
        # Base questions about Solana fundamentals
        questions = [
            "What are the basic programs available on Solana?",
            "How to interact with the Token Program on Solana?",
            "What are the common DeFi protocols on Solana?",
        ]
        concepts = ["Solana programs", "Token Program", "DeFi protocols"]
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
        qa_answer = self.qa_llm.invoke(messages).content
        logging.info(
            f"\033[35mCurriculum Agent : {qa_answer}\033[0m"
        )
        return qa_answer
