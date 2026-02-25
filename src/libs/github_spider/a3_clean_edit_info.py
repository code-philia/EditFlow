# This script is used to 1. filter commit based on edits made, filter rules may check comments start with Rule #num
import re
import os
import json
import threading
import subprocess

from tqdm import tqdm
from code_ast import *
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError


def contains_tag(main_string):
    """
    Check if any string in the list of substrings is found in the main string, case insensitive.

    Parameters:
    main_string (str): The main string to search within.

    Returns:
    bool: True if any substring is found in the main string, otherwise False.
    """
    assert type(main_string) is str
    substrings = ["<inter-mask>", "<mask>",
                  "<code_window>", "</code_window>", 
                  "<prompt>", "</prompt>", 
                  "<prior_edits>", "</prior_edits>",
                  "<edit>", "</edit>",
                  "<keep>", "<replace>", "<delete>",
                  "<null>", "<insert>", "<block-split>",
                  "<block-delete>", "</block-delete>",
                  "<block-insert>", "</block-insert>",
                  "<replace-by>", "</replace-by>"]
    main_string_lower = main_string.lower()
    return any(substring.lower() in main_string_lower for substring in substrings)

def detect_extension(file_names: list[str]):
    # 使用os.path.basename获取文件名
    for file_name in file_names:
        filename = os.path.basename(file_name)
        # 使用splitext分割文件名和后缀
        file_name_elements = filename.split('.')
        if len(file_name_elements) == 2:
            extension = '.'+file_name_elements[-1]
        else:
            extension =  '.'+'.'.join(file_name_elements[-2:])
        white_list = ['.go', '.js', '.java', '.py', '.ts', '.tsx']
        if extension not in white_list:
            return True
    return False
    
def convert_diff_section_to_snapshot(file_w_diff: str):
    diff_content = file_w_diff.splitlines(keepends=True)
    snapshot = []
    consecutive_code = []
    under_edit = False
    edits = []
    for line in diff_content:
        if line.startswith(" ") and under_edit == False:
            consecutive_code.append(line[1:])
        elif line.startswith(" ") and under_edit == True:
            under_edit = False
            if edit["type"] == "replace" and edit["after"] == []:
                edit["type"] = "delete"
            snapshot.append(edit.copy())
            consecutive_code.append(line[1:]) 
        elif line.startswith("-") and under_edit == False:
            under_edit = True
            if consecutive_code != []:
                snapshot.append(consecutive_code.copy())
            consecutive_code = []
            edit = {
                "type": "replace",
                "before": [],
                "after": []
            }
            edit["before"].append(line[1:])
        elif line.startswith("+") and under_edit == False:
            under_edit = True
            if consecutive_code != []:
                snapshot.append(consecutive_code.copy())
            consecutive_code = []
            edit = {
                "type": "insert",
                "before": [],
                "after": []
            }
            edit["after"].append(line[1:])
        elif line.startswith("+") and under_edit == True:
            edit["after"].append(line[1:])
        elif line.startswith("-") and under_edit == True:
            edit["before"].append(line[1:])
    if under_edit == True:
        if edit["type"] == "replace" and edit["after"] == []:
            edit["type"] = "delete"
        snapshot.append(edit.copy())
    if under_edit == False:
        snapshot.append(consecutive_code.copy())
    
    for window in snapshot:
        if type(window) == dict:
            edits.append(window)
    return snapshot, edits

def finer_grain_snapshot(snapshot: list, lang: str):
    finer_grain_snapshot = []
    edits = []
    for window in snapshot:
        if type(window) == list:
            finer_grain_snapshot.append(window)
            continue
        elif type(window) == dict and window["type"] != "replace":
            finer_grain_snapshot.append(window)
            edits.append(window)
        else:
            try:
                blocks = finer_grain_window(window["before"], window["after"], lang)
            except:
                return None, None
            # concat all blocks' after may not equal to window['after'], because we may delete some trivial insertion like '\n'
            new_after = []
            for block in blocks:
                new_after += block['after']
            window = {
                "type": "replace",
                "before": window["before"],
                "after": new_after,
                "blocks": blocks
            }
            finer_grain_snapshot.append(window)
            edits.append(window)
    
    return finer_grain_snapshot, edits

def git_parse_diff(commit_url: str, lang: str, strict: bool=True):
    from a0 import REPOS_PATH
    proj_name = commit_url.split('/')[-3]
    repo_path = os.path.join(REPOS_PATH, proj_name)
    sha = commit_url.split('/')[-1]
    
    result_dict = {}
    # 1. get git diff 
    command = f'git -C {repo_path} diff -U1000 {sha}^ {sha}'
    try:
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except:
        raise ValueError(f'1 {commit_url} Error: Error in git diff')
    git_diff_str = result.stdout
    if git_diff_str.strip() == '':
        raise ValueError(f'1 {commit_url} Error: Error in git diff')
    
    # 2. parse all file names (w/ path), check if they have undesired extension
    file_name_matches = re.finditer(r'diff --git a/(.+) b/(.+)', git_diff_str)
    file_names = []
    for match in file_name_matches:
        before_filename = match.group(1)
        after_filename = match.group(2)
        try:
            assert before_filename == after_filename
        except:
            raise ValueError(f"2 {commit_url} Error: Contain edit changes file name: {before_filename} -> {after_filename}")
        file_names.append(before_filename)
    
    # Rule 11: do not contain edit on less than 2 files
    file_names = list(set(file_names))
    if len(file_names) < 2:
        raise ValueError(f'11 {commit_url} Error: Contain edit on less than 2 files')
    
    # Rule 1: do not contain auto-generated files
    if detect_extension(file_names):
        raise ValueError(f'3 {commit_url} Error: Contain edit on non-source files')
        
    # 3. split into diff section, 1 section = 1 file
    diff_sections = re.findall(r'diff --git[^\n]*\n.*?(?=\ndiff --git|$)', git_diff_str, re.DOTALL)
    all_edit_num = 0
    for i, section in enumerate(diff_sections):
        # 2.1 parse file name (w/ path), make sure edit don't change file name
        file_name_match = re.match(r'diff --git a/(.+) b/(.+)', section)
        if file_name_match:
            file_name = file_name_match.group(1)
        else:
            raise ValueError(f"5 {commit_url} Error: file name contain non-ascii char")
        
        # 2.2 get the diff of the whole file
        # (if -U{number} is set large enough, a file should contain only 1 @@ -xx,xx +xx,xx @@)
        # we can only make snapshot based on the diff of the whole file
        match = re.search(r'@@[^\n]*\n(.+)', section, re.DOTALL)
        if not match:
            raise ValueError(f"4 {commit_url} Error: Edit fail to match @@ -xx,xx +xx,xx @@")
        # 匹配@@行之后的内容
        after_at_symbol_content = match.group(1)
        # Rule 2: do not contain non-ascii chars
        if not after_at_symbol_content.isascii():
            raise ValueError(f"5 {commit_url} Error: Edit/file contain non-ascii char")
        # Rule 12: do not contain <mask> or <MASK>
        if contains_tag(after_at_symbol_content):
            raise ValueError(f"12 {commit_url} Error: Edit/file contain edit tags")
        # form snapshot: each element:
        # type 1: list of line of code, unchanged
        # type 2: dict of edit, have key: "type", "before", "after"
        snapshot, _ = convert_diff_section_to_snapshot(after_at_symbol_content)
        snapshot, edits = finer_grain_snapshot(snapshot, lang)
        if snapshot is None and edits is None:
            raise ValueError(f"13 {commit_url} Error: Fail to parse finer grain snapshot")

        if len(snapshot) == len(edits):
            raise ValueError(f"9 {commit_url} Error: file contain only edit")
        if type(snapshot[0]) == dict and snapshot[0]['type'] == 'insert':
            raise ValueError(f"10 {commit_url} Error: file contain insert edit at first line")
        all_edit_num += len(edits)
        # Rule 5: contain > 3 hunk and < 15 hunk
        if all_edit_num > 15 and strict: # early stop
            raise ValueError(f'6 {commit_url} Error: Commit contain more than 15 hunk, hunk num >= {all_edit_num}')
        if all_edit_num > 30 and not strict: # need to stop even if not strict
            raise ValueError(f'6 {commit_url} Error: Commit contain more than 15 hunk, hunk num >= {all_edit_num}')
        for edit in edits:
            # Rule 3: edit less than 15 lines
            if len(edit['before']) > 15 or len(edit['after']) > 15:
                raise ValueError(f'7 {commit_url} Error: Edit longer than 15 lines, before: {len(edit["before"])} lines, after: {len(edit["after"])} lines')
            # Rule 4: edit can not be trivial
            if edit['type'] == 'replace' and \
             "".join(edit['before']).strip() == "".join(edit['after']).strip():
                raise ValueError(f'8 {commit_url} Error: Edit is trivial: {edit["before"]} -> {edit["after"]}')
            if edit['type'] == 'insert' and "".join(edit['after']).strip() == '':
                raise ValueError(f'8 {commit_url} Error: Edit is trivial: {edit["before"]} -> {edit["after"]}')
            if edit['type'] == 'delete' and "".join(edit['before']).strip() == '':
                raise ValueError(f'8 {commit_url} Error: Edit is trivial: {edit["before"]} -> {edit["after"]}')
        result_dict[file_name] = snapshot
    # Rule 5: contain > 3 hunk and < 15 hunk
    if all_edit_num < 3:
        raise ValueError(f'6 {commit_url} Error: Commit contain less than 3 hunk, hunk num: {all_edit_num}')
    return result_dict

def clean_edit(lang):
    from a0 import ROOT_PATH
    with open(os.path.join(ROOT_PATH, f'commit_info/{lang}_filtered_commit_urls.json'), 'r') as f:
        commit_urls = json.load(f)
    
    cnt = 0
    error_cnt = {}
    commit_snapshots = {}
    cnt_lock = threading.Lock()
    error_cnt_lock = threading.Lock()
    snapshots_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for commit_idx, commit_url in enumerate(commit_urls):
            future = executor.submit(git_parse_diff, commit_url, lang)
            futures.append((future, commit_url))
        
        for future, commit_url in tqdm(futures):
            try:
                result_dict = future.result(timeout=10)  # 10秒超时
                with cnt_lock:
                    cnt += 1
                with snapshots_lock:
                    commit_snapshots[commit_url] = result_dict
            except FuturesTimeoutError:
                with error_cnt_lock:
                    if '14' not in error_cnt:
                        error_cnt['14'] = 1
                    else:
                        error_cnt['14'] += 1
            except Exception as e:
                label = str(e).split(' ')[0]
                if label not in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14']:
                    print('other error: ', e)
                    print(commit_url)
                    break
                else:
                    with error_cnt_lock:
                        if label not in error_cnt:
                            error_cnt[label] = 1
                        else:
                            error_cnt[label] += 1
    
    os.makedirs(os.path.join(ROOT_PATH, 'qualified_commit'), exist_ok=True)
    with open(os.path.join(ROOT_PATH, 'qualified_commit', f'{lang}_qualified_commit_snapshots.json'), 'w') as f:
        json.dump(commit_snapshots, f, indent=4)
    
    print(f'{lang} have {cnt} left, survive rate: {cnt/len(commit_urls)*100:.2f}%')
    print('Commit filtered out because:')
    error_dict = {
        "1": "Error in acquire git diff",
        "2": "Contain edit that changes file name",
        "3": "Contain edit on non-source files",
        "4": "Edit fail to match @@ -xx,xx +xx,xx @@",
        "5": "Edit/file contain non-ascii char",
        "6": "Commit contain > 15 hunks or < 3 hunks",
        "7": "Edit longer than 15 lines",
        "8": "Edit is trivial",
        "9": "File contain only edit",
        "10": "File contain insert edit at first line",
        "11": "Contain edit on less than 2 files",
        "12": "Edit/file contain edit tags",
        "13": "Fail to parse finer grain snapshot",
        "14": "Runtime exceeded 10 seconds"
    }
    for error_idx, error_num in error_cnt.items():
        print(f'Rule {error_idx} {error_dict[error_idx]}: {error_num}')

if __name__ == '__main__':
    lang = 'python'
    clean_edit(lang)