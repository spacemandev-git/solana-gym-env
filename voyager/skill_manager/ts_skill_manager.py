import logging
import subprocess
import json
import os
import pdb
from typing import Any, Dict, List

import voyager.utils as U
from voyager.prompts import load_prompt
from langchain.chat_models.openai import ChatOpenAI
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.schema import SystemMessage, HumanMessage

class TypeScriptSkillManager:
    def __init__(
        self, 
        model_name,
        temperature=0,
        retrieval_top_k=5,
        request_timeout=120,
        ckpt_dir="ckpt",
        resume=False,
        # Old code
        skill_root="skills"
    ):
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0.0,
            request_timeout=request_timeout,
        )
        U.f_mkdir(f"{ckpt_dir}/skill/code")
        U.f_mkdir(f"{ckpt_dir}/skill/description")
        U.f_mkdir(f"{ckpt_dir}/skill/vectordb")
        # todo(ngundotra): add programs for env execution
        if resume:
            logging.info(
               f"\033[33mLoading Skill Manager from {ckpt_dir}/skill\033[0m" 
            )
            self.skills = U.load_json(f"{ckpt_dir}/skill/skills.json")
        else:
            self.skills = {}
        self.retrieval_top_k = retrieval_top_k
        self.ckpt_dir = ckpt_dir
        self.vectordb = Chroma(
            collection_name="skill_vectordb",
            embedding_function=OpenAIEmbeddings(),
            persist_directory=f"{ckpt_dir}/skill/vectordb",
        )
        assert self.vectordb._collection.count() == len(self.skills), (
                f"Skill Manager's vectordb is not synced with skills.json.\n"
            f"There are {self.vectordb._collection.count()} skills in vectordb but {len(self.skills)} skills in skills.json.\n"
            f"Did you set resume=False when initializing the manager?\n"
            f"You may need to manually delete the vectordb directory for running from scratch."
        )        

        # Old code
        self.skills_dir = skill_root
        self.skills = {}
        self.next_skill_id = 0
        if not os.path.exists(self.skills_dir):
            os.makedirs(self.skills_dir)
        self._load_existing_skills()

    @property
    def programs(self):
        programs = ""
        for skill_name, entry in self.skills.items():
            programs += f"{entry['code']}\n\n"
        # todo(ngundotra): add primitives
        return programs

    # todo(ngundotra): fix this
    def add_new_skill(self, info: Dict[str, Any]):
        # todo(ngundotra): if task is for primitive, skip
        program_name = info['program_name']
        program_code = info['program_code']
        skill_description = self.generate_skill_description(program_name, program_code)
        logging.info(
            f"\033[33mSkill Manager generated description for {program_name}:\n{skill_description}\033[0m"
        )
        if program_name in self.skills:
            self.vectordb._collection.delete(ids=[program_name])
            i = 2
            while f"{program_name}V{i}.ts" in os.listdir(f"{self.ckpt_dir}/skill/code"):
                i += 1
            dumped_program_name = f"{program_name}V{i}"
        else:
            dumped_program_name = program_name
        self.vectordb.add_texts(
            texts=[skill_description],
            ids=[program_name],
            metadatas=[{"name": program_name}],
        )
        self.skills[program_name] = {
            "code": program_code,
            "description": skill_description,
        }
        assert self.vectordb._collection.count() == len(
            self.skills
        ), "vectordb is not synced with skills.json"
        U.dump_text(
            program_code,
            f"{self.ckpt_dir}/skill/code/{dumped_program_name}.ts"
        )
        U.dump_text(
            skill_description,
            f"{self.ckpt_dir}/skill/description/{dumped_program_name}.txt"
        )
        U.dump_json(self.skills, f"{self.ckpt_dir}/skill/skills.json")
        self.vectordb.persist()

    def generate_skill_description(self, program_name, program_code):
        messages = [
            SystemMessage(content=load_prompt("skill")),
            HumanMessage(
                content=program_code
                + "\n\n"
                + f"The main function is `{program_name}`."
            ),
        ]
        skill_description = f"    // { self.llm(messages).content}"
        return f"async function {program_name}() {{\n{skill_description}\n}}"

    def retrieve_skills(self, query: str):
        k = min(self.vectordb._collection.count(), self.retrieval_top_k)
        if k == 0:
            return []
        logging.info(
           f"\033[33mSkill Manager retrieving for {k} skills\033[0m" 
        )
        docs_and_scores = self.vectordb.similarity_search_with_score(query, k=k)
        logging.info(
            f"\033[33mSkill Manager retrieved skills: "
            f"{', '.join([doc.metadata['name'] for doc, _ in docs_and_scores])}\033[0m"
        )
        skills = []
        for doc, _ in docs_and_scores:
            skills.append(self.skills[doc.metadata['name']['code']]) 
        return skills


    def evaluate_code(self, code: str, programs: List[str], agent_pubkey: str, timeout_ms: int):
        import base64
        encoded_code = base64.b64encode(code.encode("utf-8")).decode("utf-8")

        # Need to add a dummy program to the list to make it non-empty
        if not programs:
            programs = ['console.log();']

        encoded_programs = base64.b64encode("\n".join(programs).encode("utf-8")).decode("utf-8")
        command = [
            "bun", "voyager/skill_runner/runCode.ts", 
            encoded_code, 
            encoded_programs, 
            agent_pubkey,
            str(timeout_ms),
        ]
        logging.info(f"Running skill runner with command: {command}")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8'
            )
            return {
                'success': True,
                'serialized_tx': json.loads(result.stdout.strip("\n"))["serialized_tx"],
                'stdout': result.stdout.strip("\n"),
                'stderr': result.stderr.strip("\n"),
            }
        except subprocess.CalledProcessError as e:
                return {
                    "success": False, 
                    "reason": f"Skill runner error: {e.stderr}", 
                    'stdout': result.stdout.strip("\n"),
                    'stderr': result.stderr.strip("\n"),
                }
        except FileNotFoundError:
            return {"success": False, "reason": "Bun command not found. Make sure Bun is installed and in your PATH."}


    # ================================
    # OLD CODE

    def get_skills(self) -> Dict[str, str]:
        return self.skills

    def _load_existing_skills(self):
        for filename in sorted(os.listdir(self.skills_dir)):
            if filename.endswith(".ts"):
                skill_id = self.next_skill_id
                self.skills[skill_id] = os.path.join(self.skills_dir, filename)
                self.next_skill_id += 1
    
    def register(self, skill_name: str, code: str) -> int:
        skill_id = self.next_skill_id
        file_path = os.path.join(self.skills_dir, f"skill_{skill_id}.ts")
        with open(file_path, "w") as f:
            f.write(code)
        self.skills[skill_name] = file_path
        self.next_skill_id += 1
        return skill_name

    def __len__(self):
        return len(self.skills)

    def get_skill_docs(self) -> Dict[str, str]:
        # For TypeScript skills, we might not have docstrings in the same way as Python.
        # For now, return the file paths as "docs".
        return {str(k): v for k, v in self.skills.items()}

    def save_skill(self, name: str, code: str) -> str:
        file_path = os.path.join(self.skills_dir, f"{name}.ts")
        with open(file_path, "w") as f:
            f.write(code)
        return file_path

    def execute_skill(self, file_path: str, timeout_ms: int = 10000, agent_pubkey: str = None, latest_blockhash: str = None) -> Dict[str, Any]:
        command = ["bun", "skill_runner/runSkill.ts", file_path, str(timeout_ms)]
        if agent_pubkey:
            command.append(agent_pubkey)
        if latest_blockhash:
            command.append(latest_blockhash)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8'
            )
            # runSkill.ts now outputs a JSON object with tx_receipt_json_string
            return json.loads(result.stdout.strip("\n"))
        except subprocess.CalledProcessError as e:
            # pdb.set_trace()
            # If runSkill.ts exits with an error, it prints the JSON result to stderr
            try:
                # The error output might also be a JSON object if the skill itself failed gracefully
                return json.loads(e.stderr.strip("\n"))
            except json.JSONDecodeError:
                # Fallback for unexpected stderr output
                return {"success": False, "reason": f"Skill runner error: {e.stderr}"}
        except FileNotFoundError:
            return {"success": False, "reason": "Bun command not found. Make sure Bun is installed and in your PATH."}


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    skill_manager = TypeScriptSkillManager(
        model_name="gpt-4o-mini",
        temperature=0.0,
        retrieval_top_k=5,
        request_timeout=120,
        ckpt_dir="test_ckpt",
        resume=False,
    )
    result = skill_manager.evaluate_code(
        "console.log('hello');",
        programs=[],
        agent_pubkey="fake",
        timeout_ms=10000,
    )
    assert not result['success'], f"Skill runner succeeded: {result}"
    result = skill_manager.evaluate_code(
"""
const kp = web3.Keypair.generate(); 
const tx = new web3.Transaction(); 
tx.add(web3.SystemProgram.transfer({
    fromPubkey: kp.publicKey,
    toPubkey: kp.publicKey,
    lamports: 100000,
}));
tx.recentBlockhash = "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi";
tx.feePayer = kp.publicKey; tx.sign(kp); 
return tx.serialize().toString('base64');
""",
        programs=[],
        agent_pubkey="fake",
        timeout_ms=10000,
    )
    assert result['success'], f"Skill runner failed: {result}"

