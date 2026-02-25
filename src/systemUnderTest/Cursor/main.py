import os
import shutil
import subprocess

OUTPUT_DIR = os.getenv("OUTPUT_DIR")
DISPLAY_ID = os.getenv("DISPLAY_ID")
# Display id should be set before loading utils
if DISPLAY_ID:
    os.environ["DISPLAY"] = DISPLAY_ID
    
from .utils import *

def main(json_input: dict):
    if json_input["status"] == "init":
        return setup(json_input)
    elif json_input["status"] == "suggestion":
        return subsequent_edit_recommendation(json_input)
    elif json_input["status"] == "end":
        return None

def setup(json_input: dict):
    """
    Open the project and checkout to given commit in Cursor.
    """
    global OUTPUT_DIR

    # Open workspace in cursor. Make sure you can open cursor via command `cursor`
    if is_inside_docker():
        log_path = os.path.join(OUTPUT_DIR, "cursor.log")
        app_path = "/opt/Cursor/squashfs-root/AppRun"
        with open(log_path, "w") as log_file:
            subprocess.Popen(
                [app_path, "--no-sandbox", json_input["repo_dir"]],
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
    else:
        subprocess.Popen(['cursor', json_input["repo_dir"]])
    time.sleep(2)
    print("[MESSAGE:SUT] Open project in Cursor.")
    
    full_screen()
    print("[MESSAGE:SUT] Make cursor in full screen.")
    screenshot("App_in_full_screen", json_input["project_name"], json_input["id"])
    
    ensure_ai_chat_open()
    print("[MESSAGE:SUT] AI Chat is ready.")
    screenshot("AI_chat_ready", json_input["project_name"], json_input["id"])

    # make_edit(json_input["prior_edits"][-1], json_input["project_name"], json_input["id"])

def subsequent_edit_recommendation(json_input):
    """
    Make subsequent edit recommendation in Cursor.
    """
    # Clone current project status
    clone_dir(json_input["repo_dir"], f"{json_input['repo_dir']}_clone")

    # Prepare the chat message
    last_edit = json_input["prior_edits"][-1]
    chat_message = construct_edit_recommendation_chat_request(last_edit, json_input["edit_description"])
    # print(f"[MESSAGE:SUT] Chat message: {chat_message}")

    # Put cursor into the chat box
    focus_on_chat_input()
    time.sleep(0.5)
    
    # Clear the existing content if there's any
    get_current_input_box_content(clean_existing_content=True)
    time.sleep(0.5)
    # Enter the chat message
    pyperclip.copy(chat_message)
    # Paste the chat message
    if CURRENT_OS == "Darwin":
        press_hotkeys('command', 'v')
    else:
        press_hotkeys('ctrl', 'v')
        
    screenshot("Enter_ai_chat_message", json_input["project_name"], json_input["id"])
    
    # Ensure the input is correct
    current_input_content = get_current_input_box_content()
    assert current_input_content.strip() == chat_message.strip(), f"[ERROR:SUT] Input content is not correct. Expected: {chat_message}, but got: {current_input_content}"

    # Send the message
    pyautogui.press('enter')
    time.sleep(0.5)

    # Wait for AI response
    wait_ai_response()
    time.sleep(0.5)

    # Get AI suggestions
    dirty_files = get_dirty_files(f"{json_input['repo_dir']}_clone", json_input["repo_dir"])
    pred_snapshots = get_pred_snapshots(dirty_files, f"{json_input['repo_dir']}_clone", json_input["repo_dir"])
    
    # Sometimes, Cursor will remember your rejection and stop recommend that location, when the rejection reason is only accept 1 edit at a time.
    # reject_suggestions()

    return pred_snapshots
