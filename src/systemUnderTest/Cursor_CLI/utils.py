import os
import re
import time
import shutil

import hashlib
import tempfile
import subprocess
from io import StringIO

def clone_dir(src_dir: str, dst_dir: str) -> None:
    if not os.path.isdir(src_dir):
        raise ValueError(f"Source directory '{src_dir}' does not exist or is not a directory.")

    # If dst_dir exists, remove it
    if os.path.exists(dst_dir):
        shutil.rmtree(dst_dir)

    # Clone src_dir to dst_dir
    shutil.copytree(src_dir, dst_dir, symlinks=True)

def construct_edit_recommendation_chat_request(last_edit, commit_message):
    chat_message= ""
    if last_edit["before"] == [] and last_edit["after"] != []:
        edit_action_description = f"inserted code:\n {''.join(last_edit['after'])}"
    elif last_edit["before"] != [] and last_edit["after"] == []:
        edit_action_description = f"deleted code:\n {''.join(last_edit['before'])}"
    else:
        edit_action_description = f"replaced code:\n {''.join(last_edit['before'])} with \n{''.join(last_edit['after'])}"
    
    chat_message += f"I want to: {commit_message}, Therefore I  {edit_action_description} in file: ./{last_edit['file_path']}. Please recommend the next edit (Only 1 edit!) I should make, which may exist in the current file or other files in the project. Avoide excessive file reading and return your suggestion within 2 minuts. Apply your suggested edit directly to the project files."

    return chat_message

def get_cursor_suggestion(prompt, cwd):
    escaped_prompt = prompt.encode('unicode_escape').decode('utf-8')
    cursor_agent_cmd = [
        "cursor-agent", 
        "-p", 
        "--force",
        f"\"{escaped_prompt}\"", 
        "--output-format", 
        "text"
    ]
    try:
        # 创建字符串缓冲区用于记录输出
        output_buffer = StringIO()
        
        # 使用Popen替代run，实现实时输出处理
        process = subprocess.Popen(
            cursor_agent_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 合并错误输出到标准输出
            text=True,
            bufsize=1,  # 行缓冲模式
            universal_newlines=True
        )
        
        # 实时读取并打印输出
        output = []
        print(f"="*15, "Cursor CLI Output", "="*15)
        for line in process.stdout:
            # 同时打印到终端和缓冲区
            sys.stdout.write(line)
            sys.stdout.flush()
            output.append(line)
            output_buffer.write(line)
        print("\n"+"="*15, "Cursor CLI Output End", "="*15)
        
        # 等待进程完成并获取返回码
        process.wait(timeout=120)
        
        # 获取完整输出内容
        full_output = output_buffer.getvalue()
        output_buffer.close()
        
        if process.returncode == 0:
            return full_output
        else:
            return f"Command failed with code {process.returncode}: {full_output}"
            
    except subprocess.TimeoutExpired as e:
        print(e)
        return None
    except FileNotFoundError as e:
        print(e)
        return None

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
