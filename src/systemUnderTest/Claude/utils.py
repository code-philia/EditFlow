import os
import re
import shutil
import asyncio
import hashlib
import datetime
import tempfile
import subprocess

from pathlib import Path
from typing import List, Dict, Any
from claude_code_sdk import query, ClaudeCodeOptions

ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

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

def get_claude_suggestion(prompt, cwd):
    async def query_claude(prompt, options):
        messages = []
        async for message in query(prompt=prompt, options=options):
            messages.append(message)
        json_log = messages_to_json(messages, prompt=prompt)
        if json_log["messages"][-1]["result"] == "Overloaded":
            raise ValueError("[ERROR:SUT] Claude code is currently overloaded")
        return json_log
    
    options = ClaudeCodeOptions(
        max_turns=15,
        system_prompt="You are a AI coding assistant, your job is to identify potential subsequent edit based on the given prompt, which includes: edit description, last edit. The subsequent edit may/ may not exist in the same file of the last edit",
        cwd=Path(cwd),
        allowed_tools=["Read", "Write", "Bash"],
        permission_mode="acceptEdits"
    )

    return asyncio.run(query_claude(prompt, options))

def messages_to_json(messages: List, prompt: str = None) -> Dict[str, Any]:
    """
    Convert Claude Code message objects list to JSON format
    
    Args:
        messages: List of message objects returned by Claude Code
        prompt: Original prompt string
        session_name: Name of the session
    
    Returns:
        Structured JSON data
    """
    
    json_messages = []
    session_info = {}
    
    for i, message in enumerate(messages):
        json_message = serialize_message(message, i)
        json_messages.append(json_message)
        
        # Extract session information
        if hasattr(message, 'session_id'):
            session_info['session_id'] = message.session_id
        if hasattr(message, 'total_cost_usd'):
            session_info['total_cost_usd'] = message.total_cost_usd
        if hasattr(message, 'usage'):
            session_info['usage'] = message.usage
        if hasattr(message, 'duration_ms'):
            session_info['duration_ms'] = message.duration_ms
    
    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "prompt": prompt,
        "session_info": session_info,
        "total_messages": len(messages),
        "messages": json_messages
    }

def serialize_message(message, index: int = 0) -> Dict[str, Any]:
    """
    Serialize a single message object to JSON format
    """
    
    base_data = {
        "index": index,
        "message_type": type(message).__name__,
        "timestamp": datetime.datetime.now().isoformat()
    }
    
    # Handle SystemMessage
    if hasattr(message, 'subtype') and hasattr(message, 'data'):
        base_data.update({
            "subtype": message.subtype,
            "data": message.data if isinstance(message.data, dict) else str(message.data)
        })
    
    # Handle AssistantMessage and UserMessage
    if hasattr(message, 'content'):
        base_data["content"] = serialize_content(message.content)
    
    # Handle ResultMessage
    if hasattr(message, 'result'):
        base_data["result"] = message.result
    if hasattr(message, 'is_error'):
        base_data["is_error"] = message.is_error
    if hasattr(message, 'duration_ms'):
        base_data["duration_ms"] = message.duration_ms
    if hasattr(message, 'duration_api_ms'):
        base_data["duration_api_ms"] = message.duration_api_ms
    if hasattr(message, 'num_turns'):
        base_data["num_turns"] = message.num_turns
    if hasattr(message, 'total_cost_usd'):
        base_data["total_cost_usd"] = message.total_cost_usd
    if hasattr(message, 'usage'):
        base_data["usage"] = message.usage
    if hasattr(message, 'session_id'):
        base_data["session_id"] = message.session_id
    
    # Add all other attributes
    for attr_name in dir(message):
        if not attr_name.startswith('_') and attr_name not in base_data:
            try:
                attr_value = getattr(message, attr_name)
                if not callable(attr_value):
                    base_data[attr_name] = serialize_value(attr_value)
            except:
                pass  # Ignore attributes that cannot be serialized
    
    return base_data

def serialize_content(content) -> List[Dict[str, Any]]:
    """
    Serialize message content
    """
    if not content:
        return []
    
    serialized_content = []
    
    for item in content:
        if hasattr(item, '__dict__'):
            # Object type content
            item_data = {
                "type": type(item).__name__,
                "attributes": {}
            }
            
            for attr_name in dir(item):
                if not attr_name.startswith('_'):
                    try:
                        attr_value = getattr(item, attr_name)
                        if not callable(attr_value):
                            item_data["attributes"][attr_name] = serialize_value(attr_value)
                    except:
                        pass
            
            serialized_content.append(item_data)
        else:
            # Simple type content
            serialized_content.append({
                "type": "raw",
                "value": serialize_value(item)
            })
    
    return serialized_content

def serialize_value(value) -> Any:
    """
    Serialize any value to JSON-compatible format
    """
    if value is None:
        return None
    elif isinstance(value, (str, int, float, bool)):
        return value
    elif isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]
    elif isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    else:
        return str(value)

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
