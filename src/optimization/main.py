import os
import json

from .utils import *
from .rerank import *
from dotenv import load_dotenv

current_path = os.path.abspath(os.path.dirname(__file__))
root_path = os.path.abspath(os.path.join(current_path, "../../"))
load_dotenv(dotenv_path=os.path.join(root_path, ".config"))
REPOS_DIR = os.getenv("REPOS_DIR") # this directory should be the absolute path to the repository directory inside backend host
os.makedirs(REPOS_DIR, exist_ok=True)

def main(json_input: dict):
    """
    Input: 
        json_input: dict
            - id: str, user identifier
            - system_under_test: str, the system under test
            - status: str, the status of the request, ["init", "suggestion"]
            - project_name: str, the name of the project
            - project: dict, the project to be edited. 
                * The key is the relative file path
                * The value is the content of file. Has type
                    * If the file is binary: bytes;
                    * If the status is `init` and the file is not binary: [list[str]], each str is a line of code;
                    * If the status is `suggestion` and the file is not binary: list[list[str] | dict], the edit snapshot for this file.
            - edit_description: str, the description of the edit, if status is `init`, of type None, else, of type str.
    """
    user_id = json_input["id"]
    system_under_test = json_input["system_under_test"]
    status = json_input["status"]
    if system_under_test == "CoEdPilot":
        import systemUnderTest.CoEdPilot.main as SUT
    elif system_under_test == "Claude":
        import systemUnderTest.Claude.main as SUT

    USER_REPOS_DIR = os.path.join(REPOS_DIR, f"user_{user_id}")
    if status == "init":
        # Write the entire project to local
        write_project(
            json_input["project"], 
            json_input["project_name"],
            USER_REPOS_DIR
        )

        # Let SUT initiate
        assert json_input["edit_description"] is None
        SUT_json_input = {
            "id": user_id,
            "project_name": json_input["project_name"],
            "status": "init",
            "repo_dir": os.path.join(USER_REPOS_DIR, json_input["project_name"]),
            "prior_edits": [], # User justed opened workspace, no prior edit exists
            "edit_description": ""
        }
        SUT.main(SUT_json_input)

    elif status == "suggestion":
        # Write the delta project to local
        write_project(
            json_input["project"], 
            json_input["project_name"],
            USER_REPOS_DIR
        )

        # Let SUT suggest
        prior_edits = extract_prior_edits(json_input["project"])
        SUT_json_input = {
            "id": user_id,
            "project_name": json_input["project_name"],
            "status": "suggestion",
            "repo_dir": os.path.join(USER_REPOS_DIR, json_input["project_name"]),
            "prior_edits": prior_edits,
            "edit_description": json_input["edit_description"]
        }
        sut_output = SUT.main(SUT_json_input)
        if isinstance(sut_output, tuple):
            pred_snapshots = sut_output[0]
        else:
            pred_snapshots = sut_output
        pred_snapshots = indexing_edits_within_snapshots(pred_snapshots)

        # re-rank edits
        reranked_pred_snapshots, rerank_cost = rerank(pred_snapshots, prior_edits)
        return reranked_pred_snapshots