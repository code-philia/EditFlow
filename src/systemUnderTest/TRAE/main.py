import os
import shutil
import subprocess
from .utils import *

def main(json_input: dict):
    if json_input["status"] == "init":
        return setup(json_input)
    elif json_input["status"] == "suggestion":
        return subsequent_edit_recommendation(json_input)
    elif json_input["status"] == "end":
        return end(json_input)

    
def setup(json_input: dict):
    """
    Open the project and checkout to given commit in TRAE.
    """

    # Open workspace in trae. Make sure you can open trae via command `trae`
    subprocess.Popen(['trae', json_input["repo_dir"]])
    time.sleep(2)
    
    print("[MESSAGE:SUT] Make trae in full screen.")
    full_screen()

    ensure_ai_chat_open()
    time.sleep(3) # Sometimes the ai chat is loading
    print("[MESSAGE:SUT] AI Chat is ready.")
    open_new_ai_chat()


def subsequent_edit_recommendation(json_input):
    """
    Make subsequent edit recommendation in TRAE.
    """
    # Clone current project status
    clone_dir(json_input["repo_dir"], f"{json_input['repo_dir']}_clone")

    # Prepare the chat message
    last_edit = json_input["prior_edits"][-1]
    chat_message = construct_edit_recommendation_chat_request(last_edit, json_input["edit_description"])
    # print(f"[MESSAGE:SUT] Chat message: {chat_message}")

    # Put mouse cursor into the chat box
    focus_on_chat_input()
    time.sleep(0.5)
    
    # Paste the chat message
    if CURRENT_OS == "Darwin":
        # Clear the existing content if there's any
        get_current_input_box_content(clean_existing_content=True)
        time.sleep(0.5)
        # Enter the chat message
        pyperclip.copy(chat_message)
        press_hotkeys('command', 'v')
    else:
        raise OSError(f"[ERROR:SUT] Unsupported OS: {CURRENT_OS}")

    # Ensure the input is correct
    current_input_content = get_current_input_box_content()
    # Below assertion is commented out, because TRAE will render the input, copying the rendered one may causing it different from our input
    # assert current_input_content.strip() == chat_message.strip(), f"[ERROR:SUT] Input content is not correct. Expected: \n\n{chat_message}, but got: \n\n{current_input_content}"

    # Send the message
    pyautogui.press('enter')
    time.sleep(0.5)

    # Wait for AI response
    wait_ai_response()
    time.sleep(0.5)

    # Get AI suggestions
    dirty_files = get_dirty_files(f"{json_input['repo_dir']}_clone", json_input["repo_dir"])
    pred_snapshots = get_pred_snapshots(dirty_files, f"{json_input['repo_dir']}_clone", json_input["repo_dir"])

    # If no suggestion is made, return empty dict
    if pred_snapshots == {}:
        return pred_snapshots
    
    # Reject all suggestions
    reject_suggestions()
    
    return pred_snapshots

def end(json_input: dict):
    """
    End the simulation in TRAE.
    """
    global MEDIA_PATH
    locate_and_click(
        image_path=os.path.join(MEDIA_PATH, 'close_ide.png'),
        confidence=0.8,
        click_offset_percentage=(0, 0.5),
        desc="Close IDE"
    )