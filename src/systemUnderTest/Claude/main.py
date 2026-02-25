import os
import json
import time
import shutil

from .utils import *
from claude_code_sdk._errors import ProcessError

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
    Set up the project in backend. Claude Code does not need extra setup.
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
    
    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            start = time.time()
            json_log = get_claude_suggestion(chat_message, json_input["repo_dir"])
            end = time.time()
            total_time = end - start
            break  # 成功执行，跳出循环
        except ProcessError as e:
            if "exit code 1" in str(e) or "exit code: 1" in str(e):
                retry_count += 1
                if retry_count < max_retries:
                    print(f"[ERROR:SUT] Command failed, wait 5s and retry ({retry_count}/{max_retries})")
                    time.sleep(5)
                else:
                    print(f"[ERROR:SUT] Command failed {max_retries} times, raise exception")
                    raise  # 重新抛出异常
            else:
                raise  # 其他ProcessError直接抛出

    os.makedirs(os.path.join(LOG_DIR, "Claude", f"{json_input['project_name']}-{str(json_input['id'])[:8]}"), exist_ok=True)
    with open(
        os.path.join(LOG_DIR, "Claude", f"{json_input['project_name']}-{str(json_input['id'])[:8]}", f"chat_{len(json_input['prior_edits'])}.json"),
        "w"
    ) as f:
        json.dump(json_log, f, indent=4)

    # Get AI suggestions
    dirty_files = get_dirty_files(f"{json_input['repo_dir']}_clone", json_input["repo_dir"])
    pred_snapshots = get_pred_snapshots(dirty_files, f"{json_input['repo_dir']}_clone", json_input["repo_dir"])
    
    total_token = json_log["session_info"]["usage"]["input_tokens"] + json_log["session_info"]["usage"]["output_tokens"] + json_log["session_info"]["usage"]["cache_creation_input_tokens"]
    total_price = json_log["session_info"]["total_cost_usd"]

    costs = {
        "time": total_time,
        "token": total_token,
        "price": total_price
    }
    
    return pred_snapshots, costs
