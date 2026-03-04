import os
import json
import time
import shutil
from datetime import datetime

from .utils import *

LOG_DIR = os.getenv("LOG_DIR")

def main(json_input: dict):
    if json_input["status"] == "init":
        return setup(json_input)
    elif json_input["status"] == "suggestion":
        return subsequent_edit_recommendation(json_input)
    elif json_input["status"] == "end":
        return None
    
def setup(json_input: dict):
    """
    Set up the project in backend. Cursor CLI does not need extra setup.
    """
    pass

def subsequent_edit_recommendation(json_input: dict):
    """
    Get subsequent edit recommendation from Claude Code.
    """
    global LOG_DIR
    # Clone current project status
    clone_dir(json_input["repo_dir"], f"{json_input['repo_dir']}_clone")

    # Prepare the chat message
    last_edit = json_input["prior_edits"][-1]
    chat_message = construct_edit_recommendation_chat_request(last_edit, json_input["edit_description"])

    start = time.time()
    log = get_cursor_suggestion(chat_message, json_input["repo_dir"])
    end = time.time()
    total_time = end - start
    os.makedirs(os.path.join(LOG_DIR, "Cursor_CLI", f"{json_input['project_name']}-{str(json_input['id'])[:8]}"), exist_ok=True)
    with open(
        os.path.join(LOG_DIR, "Cursor_CLI", f"{json_input['project_name']}-{str(json_input['id'])[:8]}", f"chat_{len(json_input['prior_edits'])}.log"),
        "w"
    ) as f:
        start_time_str = datetime.utcfromtimestamp(start).strftime('%Y-%m-%dT%H:%M:%S') + f'.{int((start % 1) * 1000):03d}Z'
        f.write(f"Start time: {start_time_str}\n")
        f.write(log)

    # Get AI suggestions
    dirty_files = get_dirty_files(f"{json_input['repo_dir']}_clone", json_input["repo_dir"])
    pred_snapshots = get_pred_snapshots(dirty_files, f"{json_input['repo_dir']}_clone", json_input["repo_dir"])
    
    costs = {
        "time": total_time,
        "token": None,
        "price": None
    }

    return pred_snapshots, costs
