import os
import re
import cv2
import time
import shutil
import hashlib
import tempfile
import platform
import pyautogui
import pyperclip
import subprocess
import pytesseract
import numpy as np
import pyscreenshot as ImageGrab

from datetime import datetime

CURRENT_OS = platform.system()
CURRENT_PATH = os.path.abspath(os.path.dirname(__file__))

MAX_RETRY = os.getenv("MAX_RETRY")
MAX_WAIT_RESPONSE = os.getenv("MAX_WAIT_RESPONSE")
OUTPUT_DIR = os.getenv("OUTPUT_DIR")
LOG_DIR = os.getenv("LOG_DIR")
DISPLAY_ID = os.getenv("DISPLAY_ID")
MEDIA_PATH_NAME = os.getenv("MEDIA_PATH_NAME")
MEDIA_PATH = os.path.join(CURRENT_PATH, MEDIA_PATH_NAME)
if DISPLAY_ID:
    os.environ["DISPLAY"] = DISPLAY_ID

def clone_dir(src_dir: str, dst_dir: str) -> None:
    if not os.path.isdir(src_dir):
        raise ValueError(f"Source directory '{src_dir}' does not exist or is not a directory.")

    # If dst_dir exists, remove it
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)

    # Clone src_dir to dst_dir
    shutil.copytree(src_dir, dst_dir, symlinks=True)

def full_screen():
    global DISPLAY_ID
    if CURRENT_OS == "Darwin":
        print("[MESSAGE:SUT] At src/systemUnderTest/Cursor/utils.py: full_screen(), this hotkey require specific software named `Magnet`.")
        press_hotkeys('ctrl', 'option', 'enter')
    elif CURRENT_OS == "Linux":
        subprocess.run(
            'xdotool search --onlyvisible --name "Cursor" | while read win; do xdotool windowsize "$win" 1920 1080; done',
            shell=True,
            check=True,
            env={"DISPLAY": DISPLAY_ID}
        )
    else:
        raise OSError(f"[ERROR:SUT] Unsupported OS: {CURRENT_OS}")
    time.sleep(0.5)

def press_hotkeys(*keys, delay=0.1):
    """
    Press a sequence of keys as a hotkey combination.
    The last key is treated as the action key (e.g., 'f'),
    while preceding keys are treated as modifiers (e.g., 'ctrl', 'command').

    Args:
        *keys: Keys to press, in order. Last key is the main key.
        delay: Time delay between actions (in seconds).
    """
    if len(keys) < 2:
        raise ValueError("[ERROR:SUT] At least two keys required: modifiers + target key")

    *modifiers, target = keys

    for key in modifiers:
        pyautogui.keyDown(key)
    time.sleep(delay)
    pyautogui.press(target)
    time.sleep(delay)
    for key in reversed(modifiers):
        pyautogui.keyUp(key)

    release_all_modifiers()

def locate_and_click(image_path, confidence, click_offset_percentage, desc):
    global MEDIA_PATH, MAX_RETRY
    # Find the location of input box
    retry_cnt = 0
    while True:
        print(f"[WARNING:SUT] At src/systemUnderTest/Cursor/utils.py: locate_and_click(), The locating image {image_path} depends on the system.")
        location = safe_locate(image_path, confidence=confidence)

        if location:
            assert 0 <= click_offset_percentage[0] <= 1, "[ERROR:SUT] The click offset percentage for x axis is in [0, 1]"
            assert 0 <= click_offset_percentage[1] <= 1, "[ERROR:SUT] The click offset percentage for y axis is in [0, 1]"
            x = location.left + int(location.width * click_offset_percentage[0])
            y = location.top + int(location.height * click_offset_percentage[1])
            
            print(f"[MESSAGE:SUT] Find {desc} at: {location}, click at ({x}, {y})")
            # 可选：移动到该点并点击
            pyautogui.moveTo(x, y)
            pyautogui.click()
            time.sleep(0.5)
            return 
        else:
            print(f"[MESSAGE:SUT] Failed to find {desc}, retry...")
            retry_cnt += 1
            if retry_cnt >= int(MAX_RETRY):
                raise RuntimeError(f"[ERROR:SUT] Failed to find {desc}.")

def select_down_n_lines(n):
    for _ in range(n):
        pyautogui.keyDown('shift')
        pyautogui.press('down')
        pyautogui.keyUp('shift')
        time.sleep(0.05)
    release_all_modifiers()

def release_all_modifiers():
    for key in ['shift', 'ctrl', 'command', 'alt', 'option', 'win']:
        try:
            pyautogui.keyUp(key)
        except Exception:
            pass  # 安全忽略未按下的情况

def text_on_screen(text, region=None):
    """
    NOTE: To determine the region, use CLI cmd: `python -m pyautogui`, which will print your cursor location, get your region via:
        1. Get top-left corner coordinate: (x1, y1)
        2. Get bottom-right corner coordinate: (x2, y2)
        3. Region: (x1, y1, x2 - x1, y2 - y1)
    """
    screenshot = pyautogui.screenshot(region=region)  # 可选区域限制
    extracted = pytesseract.image_to_string(screenshot).replace(' ', '')
    print(extracted)
    return text in extracted

def safe_locate(path, confidence=0.9, find_most_similar=True):
    try:
        # Try the standard locateOnScreen (which automatically uses the opencv mode)
        result = pyautogui.locateOnScreen(path, confidence=confidence)
        if result is not None:
            return result
    except Exception:
        # Compatibility for non-opencv backends or other exceptions
        pass
    
    if find_most_similar:
        # If no match is found, print the region with the highest similarity
        try:
            # Take a screenshot
            screenshot = pyautogui.screenshot()
            screen_rgb = np.array(screenshot)
            screen_bgr = cv2.cvtColor(screen_rgb, cv2.COLOR_RGB2BGR)

            # Read the template image
            template = cv2.imread(path, cv2.IMREAD_COLOR)
            if template is None:
                print(f"[ERROR:SUT] At src/systemUnderTest/Cursor/utils.py:safe_locate(), Failed to load template image: {path}")
                return None

            # Perform template matching
            result = cv2.matchTemplate(screen_bgr, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            print(f"[WARNING:SUT] At src/systemUnderTest/Cursor/utils.py:safe_locate(), no match found above threshold {confidence} for image {path}.")
            print(f"[WARNING:SUT] At src/systemUnderTest/Cursor/utils.py:safe_locate(), best match at {max_loc} with confidence {max_val:.4f}")

        except Exception as e:
            print(f"[ERROR:SUT] Error during fallback similarity check: {e}")

    return None
     
def ensure_ai_chat_open() -> None:
    global MEDIA_PATH, MAX_RETRY

    retry_cnt = 0
    while True:
        # 检查 off 状态是否可见
        print("[WARNING:SUT] At src/systemUnderTest/Cursor/utils.py: ensure_ai_chat_open(), The locating image depends on the system.")
        on = safe_locate(os.path.join(MEDIA_PATH, 'layout-sidebar-right-on.png'), confidence=0.9)
        if on:
            return retry_cnt
        else:
            print("[MESSAGE:SUT] Sidebar is OFF. Pressing Cmd+I to toggle.")
            if CURRENT_OS == "Darwin":
                press_hotkeys('command', 'i')
            elif CURRENT_OS == "Linux":
                press_hotkeys('ctrl', 'i')
            time.sleep(1)  # 等待界面响应
            retry_cnt += 1
            if retry_cnt >= int(MAX_RETRY):
                raise RuntimeError("[ERROR:SUT] Failed to open AI Chat.")

def make_edit(edit, project_name: str, id: str):
    global CURRENT_OS, MEDIA_PATH
    
    # 1. Open the file at certain line    
    line_idx = edit["parent_version_range"]["start"] + 1

    retry_cnt = 0
    while True:
        # Try to open the file path input box
        if CURRENT_OS == "Darwin":
            press_hotkeys('command', 'p')
        else:
            press_hotkeys('ctrl', 'p')
        screenshot("Open_file_path_input_box", project_name, id)
        
        time.sleep(0.5)
        print("[WARNING:SUT] At src/systemUnderTest/Cursor/utils.py: make_edit(), The locating image depends on the system.")
        # Make sure that the file path input box is open
        if not safe_locate(os.path.join(MEDIA_PATH, 'file_path_input_box.png'), confidence=0.9):
            time.sleep(1)
            retry_cnt += 1
            if retry_cnt >= int(MAX_RETRY):
                raise RuntimeError("[ERROR:SUT] Failed to open file path input box.")

        pyautogui.write(f'{edit["file_path"]}:{line_idx}', interval=0.02)
        time.sleep(0.5)
        screenshot("File_path_input_box_filled", project_name, id)
        pyautogui.press('enter')

        # Make sure the opened file is desired
        if CURRENT_OS == "Darwin" or CURRENT_OS == "Windows":
            import pygetwindow
            active_window_title= pygetwindow.getActiveWindow().title().lower()
        else:
            output = subprocess.check_output(
                ["xdotool", "getactivewindow", "getwindowname"],
                stderr=subprocess.DEVNULL
            )
            active_window_title = output.decode("utf-8").strip()
        if os.path.basename(edit["file_path"]) in active_window_title:
            print("[MESSAGE:SUT] Successfully opened desired file.")
            break
        else:
            time.sleep(1)
            retry_cnt += 1
            if retry_cnt >= int(MAX_RETRY):
                raise RuntimeError(f"[ERROR:SUT] Failed to open desired file, current file is: {active_window_title}.")

    # 2. Select range to edit
    if edit["before"]:
        select_down_n_lines(len(edit["before"]))
        time.sleep(0.5)
    pyperclip.copy("".join(edit["after"]))
    time.sleep(0.5)
    if CURRENT_OS == "Darwin":
        press_hotkeys('command', 'v')
    else:
        press_hotkeys('ctrl', 'v')
    
    time.sleep(0.5)
    if CURRENT_OS == "Darwin":
        press_hotkeys('command', 's')
    else:
        press_hotkeys('ctrl', 's')
    
    screenshot("Make_init_edit", project_name, id)
    print("[MESSAGE:SUT] Cursor is ready, with initial edit conducted.")

def construct_edit_recommendation_chat_request(last_edit, commit_message):
    chat_message= ""
    if last_edit["before"] == [] and last_edit["after"] != []:
        edit_action_description = f"inserting code:\n {''.join(last_edit['after'])}"
    elif last_edit["before"] != [] and last_edit["after"] == []:
        edit_action_description = f"deleting code:\n {''.join(last_edit['before'])}"
    else:
        edit_action_description = f"replacing code:\n {''.join(last_edit['before'])} with \n{''.join(last_edit['after'])}"
    chat_message += f"I want to: {commit_message}, Therefore I  {edit_action_description} in file: ./{last_edit['file_path']}. Please recommend the next edit (Only 1 edit!) I should make, which may exist in the current file or other files in the project. Avoide excessive file reading and return your suggestion within 2 minuts. Apply your suggested edit directly to the project files. I prefer to accept only one edit at a time; therefore, reverting previously recommended edits does not indicate rejection of those suggestions."

    return chat_message

def focus_on_chat_input():
    locate_and_click(
        image_path=os.path.join(MEDIA_PATH, 'ai_chat_input_box.png'),
        confidence=0.8,
        click_offset_percentage=(0.5, 0),
        desc="Chat input box"
    )

def get_current_input_box_content(clean_existing_content=False):
    """
    Get the content of the current input box.
    """
    global CURRENT_OS
    
    if CURRENT_OS == "Darwin":
        press_hotkeys('command', 'a')
        if clean_existing_content:
            time.sleep(0.5)
            pyautogui.press('delete')
            return None
        press_hotkeys('command', 'c')
    else:
        press_hotkeys('ctrl', 'a')
        if clean_existing_content:
            time.sleep(0.5)
            pyautogui.press('delete')
            return None
        press_hotkeys('ctrl', 'c')
    
    return pyperclip.paste()
    
def wait_ai_response():
    global MAX_WAIT_RESPONSE, MEDIA_PATH

    start_time = time.time()
    generated = False
    while time.time() - start_time < float(MAX_WAIT_RESPONSE):
        if not generated:
            generating = safe_locate(os.path.join(MEDIA_PATH,'generating.png'), confidence=0.8)
            if generating is None:
                time.sleep(0.5) # Avoid frequent screenshot
                continue
            else:
                generated = True # To make sure that the icon changed to generating for a moment

        # 是否能看到 "enter" 图像
        enter = safe_locate(os.path.join(MEDIA_PATH,'enter.png'), confidence=0.8, find_most_similar=False)
        
        if enter:
            print("[MESSAGE:SUT] AI response is ready.")
            return True
        
        time.sleep(1)  # Avoid frequent screenshot

    raise RuntimeError("[ERROR:SUT] Failed to generate AI response")

def reject_suggestions():
    locate_and_click(
        image_path=os.path.join(MEDIA_PATH, 'reject_all.png'),
        confidence=0.8,
        click_offset_percentage=(0.25, 0.5),
        desc="Reject suggestions"
    )

def get_dirty_files(src_dir, dst_dir):
    """
    Compare two directories and return predicted snapshots.
    
    Each item in the returned list is a dict with:
        - "file_path": relative file path
        - "type": one of "A" (added), "M" (modified), "D" (deleted)
    """
    
    def file_hash(path: str) -> str:
        """Compute the MD5 hash of a file's content."""
        hasher = hashlib.md5()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    changes = []

    src_files = set()
    dst_files = set()

    # Collect all files from src_dir
    for root, _, files in os.walk(src_dir):
        for file in files:
            rel_path = os.path.relpath(os.path.join(root, file), src_dir)
            src_files.add(rel_path)

    # Collect all files from dst_dir
    for root, _, files in os.walk(dst_dir):
        for file in files:
            rel_path = os.path.relpath(os.path.join(root, file), dst_dir)
            dst_files.add(rel_path)

    # Check for deleted or modified files
    for path in src_files:
        src_path = os.path.join(src_dir, path)
        dst_path = os.path.join(dst_dir, path)
        # Skip the comparison between link files
        if os.path.islink(src_path):
            continue
        if path not in dst_files:
            changes.append({"file_path": path, "type": "D"})  # Deleted
        elif file_hash(src_path) != file_hash(dst_path):
            changes.append({"file_path": path, "type": "M"})  # Modified

    # Check for added files
    for path in dst_files - src_files:
        changes.append({"file_path": path, "type": "A"})  # Added

    return changes

def get_pred_snapshots(dirty_files, src_dir, dst_dir):
    pred_snapshots = {}
    for change in dirty_files:
        try:
            if change["type"] == "D":
                with open(os.path.join(src_dir, change["file_path"]), "r") as f:
                    pred_snapshots[change["file_path"]] = [{
                        "before": f.readlines(),
                        "after": [],
                        "confidence": None
                    }]
            elif change["type"] == "A":
                with open(os.path.join(dst_dir, change["file_path"]), "r") as f:
                    pred_snapshots[change["file_path"]] = [{
                        "before": [],
                        "after": f.readlines(),
                        "confidence": None
                    }]
            else:
                with open(os.path.join(src_dir, change["file_path"]), "r") as f:
                    before_AI_suggestion_version = f.read()
                with open(os.path.join(dst_dir, change["file_path"]), "r") as f:
                    after_AI_suggestion_version = f.read()
                pred_snapshot = two_strings_to_snapshot(before_AI_suggestion_version, after_AI_suggestion_version)
                pred_snapshots[change["file_path"]] = pred_snapshot
        except:
            # Sometimes the file is not source code file, exclude them
            continue

    return pred_snapshots

def _convert_diff_section_to_snapshot(diff_section):
    diff_content = diff_section.splitlines(keepends=True)
    snapshot = []
    consecutive_code = []
    under_edit = False
    edits = []
    for line in diff_content:
        if line.startswith(" ") and under_edit == False:
            consecutive_code.append(line[1:])
        elif line.startswith(" ") and under_edit == True:
            under_edit = False
            snapshot.append(edit.copy())
            consecutive_code.append(line[1:]) 
        elif line.startswith("-") and under_edit == False:
            under_edit = True
            if consecutive_code != []:
                snapshot.append(consecutive_code.copy())
            consecutive_code = []
            edit = {
                "before": [],
                "after": [],
                "confidence": None
            }
            edit["before"].append(line[1:])
        elif line.startswith("+") and under_edit == False:
            under_edit = True
            if consecutive_code != []:
                snapshot.append(consecutive_code.copy())
            consecutive_code = []
            edit = {
                "before": [],
                "after": [],
                "confidence": None
            }
            edit["after"].append(line[1:])
        elif line.startswith("+") and under_edit == True:
            edit["after"].append(line[1:])
        elif line.startswith("-") and under_edit == True:
            edit["before"].append(line[1:])
    if under_edit == True:
        snapshot.append(edit.copy())
    if under_edit == False:
        snapshot.append(consecutive_code.copy())
    
    for window in snapshot:
        if type(window) == dict:
            edits.append(window)
    return snapshot

def two_strings_to_snapshot(str1, str2):
    with tempfile.NamedTemporaryFile(mode='w+', delete=False) as f1, \
         tempfile.NamedTemporaryFile(mode='w+', delete=False) as f2:
        
        f1.write(str1)
        f2.write(str2)
        f1.flush()
        f2.flush()

        result = subprocess.run(
            ['git', 'diff', '-U99999', '--no-index', '--', f1.name, f2.name],
            capture_output=True,
            text=True
        )
        
    git_diff_str = result.stdout
    # Split into diff section, 1 section = 1 file
    diff_sections = re.findall(r'diff --git[^\n]*\n.*?(?=\ndiff --git|$)', git_diff_str, re.DOTALL)
    assert len(diff_sections) == 1, f"[ERROR:SUT] Expect 1 diff section, got {len(diff_sections)}"

    diff_section = diff_sections[0]
    # Get the diff of the whole file
    # (if -U{number} is set large enough, a file should contain only 1 @@ -xx,xx +xx,xx @@)
    # we can only make snapshot based on the diff of the whole file
    match = re.search(r'@@[^\n]*\n(.+)', diff_section, re.DOTALL)
    if not match:
        raise ValueError(f"[ERROR:SUT] Edit fail to match @@ -xx,xx +xx,xx @@")
    # Match content after line @@
    after_at_symbol_content = match.group(1)
    return _convert_diff_section_to_snapshot(after_at_symbol_content)
    
def screenshot(name: str, project_name: str, id: str):
    global LOG_DIR
    image = ImageGrab.grab()
    timestamp = datetime.now().strftime("%Y%m%d_%H-%M-%S")
    target_dir = os.path.join(LOG_DIR, "Cursor", f"{project_name}-{str(id)[:8]}")
    os.makedirs(target_dir, exist_ok=True)
    image.save(os.path.join(target_dir, f"Screenshot-{name}-{timestamp}.png"))
    
def is_inside_docker():
    # Check for the presence of the /.dockerenv file
    if os.path.exists("/.dockerenv"):
        return True
    
    # Check cgroups v1 path
    try:
        with open("/proc/1/cgroup", "rt", errors="ignore") as f:
            if any("docker" in line or "kubepods" in line for line in f):
                return True
    except FileNotFoundError:
        pass
    
    # Check cgroups v2 path
    try:
        with open("/proc/self/cgroup", "rt", errors="ignore") as f:
            if any("docker" in line or "kubepods" in line for line in f):
                return True
    except FileNotFoundError:
        pass
    
    return False
