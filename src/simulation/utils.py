import os
import re
import time
import requests
import platform
import subprocess

from dotenv import load_dotenv
from collections import defaultdict
from tree_sitter import Language, Parser
from .bleu import direct_computeMaps, bleuFromMaps

curr_file_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(curr_file_dir, "../../.config"))
OPENAI_KEY = os.getenv("OPENAI_TOKEN")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")

def clone_repo(user_name: str, project_name: str, target_dir: str):
    """
    Clone the repository to local
    
    Args:
        user_name: str, the user name of the repository
        project_name: str, the name of the repository
        target_dir: str, the target directory to clone the repository
    Returns:
        None
    """
    command = f"git clone https://github.com/{user_name}/{project_name}.git {target_dir}/{project_name}"
    subprocess.run(command, shell=True)

def detect_extension(file_names: list[str]):
    # 使用os.path.basename 获取文件名
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

def check_language(file_path: str): # Also used in optimization/utils.py
    # Use os.path.splitext to get the file extension
    _, extension = os.path.splitext(file_path)
    if extension == '.go':
        return 'go'
    elif extension == '.js':
        return 'javascript'
    elif extension == '.java':
        return 'java'
    elif extension == '.py':
        return 'python'
    elif extension == '.ts' or extension == '.tsx':
        return 'typescript'
    else:
        return None

def find_code_structure(code, line_index, language): # Also used in optimization/utils.py
    # Initialize Tree-sitter parser and set language
    parser = get_parser(language)

    # Parse code to generate syntax tree
    tree = parser.parse(bytes(code, "utf8"))
    root_node = tree.root_node

    # Define node types for different languages
    def get_declaration_text_py(node):
        declearation = ""
        name = None 
        
        # Define the declaration text for Python
        if node.type == node_types['class']:
            # get child node of class, identifier, argument_list
            for child in node.children:
                if child.type == "class":
                    declearation += "class "
                elif child.type == "identifier":
                    declearation += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "argument_list":
                    declearation += child.text.decode("utf-8")
                elif child.type == ":":
                    declearation += child.text.decode("utf-8")
            return declearation, name
        elif node.type == node_types['function']:
            # get child node of function, identifier, argument_list
            for child in node.children:
                if child.type == "def":
                    declearation += "def "
                elif child.type == "identifier":
                    declearation += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "parameters":
                    declearation += child.text.decode("utf-8")
                elif child.type == ":":
                    declearation += child.text.decode("utf-8")
                elif child.type == "->":
                    declearation += child.text.decode("utf-8")
                elif child.type == "type":
                    declearation += child.text.decode("utf-8")
            return declearation, name
        return None, None
    
    def get_function_call_info_py(node):
        """
        Extract function call information for Python
        Returns: (function_name, call_signature)
        """
        call_info = ""
        function_name = None
        
        if node.type == "call":
            for child in node.children:
                if child.type == "identifier":
                    # Simple function call like func()
                    function_name = child.text.decode("utf-8")
                    call_info = function_name
                elif child.type == "attribute":
                    # Method call like obj.method()
                    function_name = child.text.decode("utf-8")
                    call_info = function_name
                elif child.type == "argument_list":
                    # Add the argument list to show it's a function call
                    call_info += child.text.decode("utf-8")
                    break  # We only need the first argument_list
        
        return (function_name, call_info) if function_name else (None, None)

    def find_argument_in_call(node, target_line):
        """
        Find which specific argument the target line belongs to in a function call
        Returns: argument_name or argument_value
        """
        if node.type != "call":
            return None
            
        for child in node.children:
            if child.type == "argument_list":
                for arg_child in child.children:
                    if (arg_child.start_point[0] <= target_line <= arg_child.end_point[0] and 
                        arg_child.type not in [",", "(", ")"]):
                        
                        # Check if it's a keyword argument
                        if arg_child.type == "keyword_argument":
                            # Extract the keyword name
                            for kw_child in arg_child.children:
                                if kw_child.type == "identifier":
                                    return f"{kw_child.text.decode('utf-8')}=..."
                        else:
                            # For positional arguments, return the text or a summary
                            arg_text = arg_child.text.decode('utf-8')
                            if len(arg_text) > 30:
                                return f"{arg_text[:30]}..."
                            return arg_text
        return None
    
    def get_declaration_text_go(node):
        declaration = ""
        name = None
        
        if node.type == node_types['function']:
            # Traverse children to extract function details
            for child in node.children:
                if child.type == "func":
                    declaration += "func "
                elif child.type == "identifier":
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "parameter_list":
                    declaration += child.text.decode("utf-8")
                elif child.type == "type":
                    declaration += " " + child.text.decode("utf-8")
            return declaration, name

        elif node.type == node_types['class']:
            # Traverse children to extract type details
            for child in node.children:
                if child.type == "type":
                    declaration += "type "
                elif child.type == "identifier":
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "struct" or child.type == "interface":
                    declaration += " " + child.type
            return declaration, name

        elif node.type == node_types['method']:
            for child in node.children:
                if child.type == "func":
                    declaration += "func "
                elif child.type == "field_identifier":
                    name = child.text.decode("utf-8")
                    declaration += " " + name
                elif child.type == "parameter_list":
                    declaration += child.text.decode("utf-8")
                elif child.type == "type_identifier":
                    declaration += " " + child.text.decode("utf-8")
                
            return declaration, name

        return None, None
    
    def get_declaration_text_java(node):
        # Define the declaration and name to be returned
        declaration = ""
        name = None

        # Parse class declaration
        if node.type == node_types['class']:
            for child in node.children:
                if child.type == "modifiers":  # Modifiers (e.g., public, static)
                    for grandchild in child.children:
                        if grandchild.text.decode("utf-8").startswith("@"):
                            continue
                        declaration += grandchild.text.decode("utf-8") + " "
                elif child.type == "class":
                    declaration += "class "
                elif child.type == "identifier":  # Class name
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "type_parameters":  # Generic type parameters
                    declaration += child.text.decode("utf-8")
                elif child.type == "superclass":
                    declaration += " " + child.text.decode("utf-8")
                elif child.type == "implements":  # Implemented interfaces
                    declaration += " implements "
                    for grandchild in child.children:  # Process interfaces after implements
                        declaration += grandchild.text.decode("utf-8") + ", "
                    declaration = declaration.rstrip(", ")  # Remove the extra comma
                elif child.type == "{":  # Start of class body
                    declaration += " {"
            return declaration, name

        # Parse method declaration
        elif node.type == node_types['function']:
            for child in node.children:
                if child.type == "modifiers":  # Modifiers (e.g., public, static)
                    for grandchild in child.children:
                        if grandchild.text.decode("utf-8").startswith("@"):
                            continue
                        declaration += grandchild.text.decode("utf-8") + " "
                elif child.type == "type":  # Method return type
                    declaration += child.text.decode("utf-8") + " "
                elif child.type == "identifier":  # Method name
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "parameters":  # Parameter list
                    declaration += child.text.decode("utf-8")
                elif child.type == "formal_parameters":
                    declaration += child.text.decode("utf-8")
                elif child.type.endswith("_type"):
                    declaration += child.text.decode("utf-8") + " "
                elif child.type == "throws":  # Thrown exceptions
                    # declaration += " throws "
                    for grandchild in child.children:  # Process exception types after throws
                        if "throws" in grandchild.text.decode("utf-8"):
                            declaration += " "
                        declaration += grandchild.text.decode("utf-8") + " "
                    declaration = declaration.rstrip(", ")  # Remove the extra comma
                elif child.type == "{":  # Start of method body
                    declaration += " {"
            return declaration, name

        return None
    
    def get_declaration_text_js(node):
        """
        Extracts the declaration text and name for classes and methods in JavaScript.
        """
        declaration = ""
        name = None
        if node.type == node_types['class']:
            # Traverse children to extract class details
            for child in node.children:
                if child.type == "class":
                    declaration += "class "
                elif child.type == "identifier":
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "class_heritage":
                    declaration += " " + child.text.decode("utf-8")
            return declaration, name

        elif node.type == node_types['function']:
            # Traverse children to extract method details
            for child in node.children:
                if child.type == "async":
                    declaration += "async "
                elif child.type == "function":
                    declaration += "function "
                elif child.type == "identifier":
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "formal_parameters":
                    declaration += child.text.decode("utf-8")
            return declaration, name
        
        elif node.type == node_types['method']:
            # Traverse children to extract method details
            for child in node.children:
                # print(child.type, child.text.decode("utf-8"))
                if child.type == "async":
                    declaration += "async "
                elif child.type == "property_identifier":
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "formal_parameters":
                    declaration += child.text.decode("utf-8")
            return declaration, name

        return None, None
    
    def get_declaration_text_ts(node):
        declaration = ""
        name = None
        if node.type == node_types['class']:
            for child in node.children:
                print(child.type)
                
        elif node.type == node_types['function']:
            for child in node.children:
                print(child.type)
                if child.type == "function":
                    declaration += "function "
                elif child.type == "identifier":
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "formal_parameters":
                    declaration += child.text.decode("utf-8")
            return declaration, name
                
        elif node.type == node_types['method']:
            for child in node.children:
                print(child.type)
            
        return None, None
    
    # Define node types for different languages
    language_nodes = {
        "python": {
            "class": "class_definition",
            "function": "function_definition", 
            "call": "call",  # Add function call node type
            "get_signature_fn": get_declaration_text_py,
            "get_call_info_fn": get_function_call_info_py  # Add call info function
        },
        "go": {
            "class": "type_declaration",
            "function": "function_declaration",
            "method": "method_declaration",
            "get_signature_fn": get_declaration_text_go
        },
        "java": {
            "class": "class_declaration", 
            "function": "method_declaration",
            "get_signature_fn": get_declaration_text_java
        },
        "javascript": {
            "class": "class_declaration",
            "function": "function_declaration", 
            "method": "method_definition",
            "get_signature_fn": get_declaration_text_js
        },
        "typescript": {
            "class": "class_declaration",
            "function": "function_declaration",
            "get_signature_fn": get_declaration_text_ts
        },
    }

    node_types = language_nodes[language]

    def print_node_structure(node, level=0):
        indent = '  ' * level  # Generate indentation based on the level
        print(f"{indent}Node Type: {node.type}, Text: {node.text if node.text else ''}, Start: {node.start_point}, End: {node.end_point}")

        # Recursively print the structure of child nodes
        for child in node.children:
            print_node_structure(child, level + 1)
            
    # Traverse the syntax tree to find the structure path of the line number
    def traverse(node, current_structure=[]):
        # Check if the current node contains the line number
        if node.start_point[0] <= line_index <= node.end_point[0]:
            # If it is a class definition, add to structure path
            if node.type == node_types['class']:
                class_declaration, class_name = node_types["get_signature_fn"](node)
                current_structure.append({
                    "type": "class",
                    "name": class_name,
                    "signature": class_declaration,
                    "at_line": node.start_point[0]
                })

            # If it is a function definition, add to structure path
            elif node.type == node_types['function']:
                function_declaration, function_name = node_types["get_signature_fn"](node)
                current_structure.append({
                    "type": "function",
                    "name": function_name,
                    "signature": function_declaration,
                    "at_line": node.start_point[0]
                })

            # If it is a function call, add to structure path
            elif node.type == node_types['call']:
                function_name, call_signature = node_types["get_call_info_fn"](node)
                if function_name:
                    # Find which specific argument the line belongs to
                    argument_info = find_argument_in_call(node, line_index)
                    
                    call_entry = {
                        "type": "call",
                        "name": function_name,
                        "signature": call_signature,
                        "at_line": node.start_point[0]
                    }
                    
                    current_structure.append(call_entry)

            elif node_types.get('method') and node.type == node_types['method']:
                
                method_declaration, method_name = node_types["get_signature_fn"](node)
                current_structure.append({
                    "type": "method",
                    "name": method_name,
                    "signature": method_declaration,
                    "at_line": node.start_point[0]
                })
                
            # Check the child in recursion
            for child in node.children:
                result = traverse(child, current_structure)
                if result:
                    return result

            # return the current structure path
            return current_structure

        return []

    # Get the structural path of the line number
    structure_path = traverse(root_node)
    return structure_path

def get_parser(language): # Also used in optimization/utils.py
    assert language in ["python"], "Currently only Python is supported"
    system = platform.system().lower()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    tree_sitter_dir = os.path.normpath(os.path.join(base_dir, "../libs/tree-sitter"))
    if system == "darwin":
        build_file_path = os.path.join(tree_sitter_dir, "macos_build/my-languages.so")
    elif system == "linux":
        build_file_path = os.path.join(tree_sitter_dir, "linux_build/my-languages.so")
    elif system == "windows":
        build_file_path = os.path.join(tree_sitter_dir, "windows_build/my-languages.dll")
    try:
        LANGUAGES = Language(build_file_path, language)
    except:
        # build so
        Language.build_library(
            build_file_path,
            [
                os.path.join(tree_sitter_dir, "tree-sitter-python"),
                os.path.join(tree_sitter_dir, "tree-sitter-go"),
                os.path.join(tree_sitter_dir, "tree-sitter-java"),
                os.path.join(tree_sitter_dir, "tree-sitter-javascript"),
                os.path.join(tree_sitter_dir, "tree-sitter-typescript")
            ]
        )
        LANGUAGES = Language(build_file_path, language)
    
    parser = Parser()
    parser.set_language(LANGUAGES)
    return parser

def parse(code, language):
    parser = get_parser(language)
    tree = parser.parse(bytes(code, "utf8"))
    return tree

def find_control_flow(code, line_index, language): # Also used in optimization/utils.py

    def get_statement(node, source_bytes):
        start = node.start_byte
        end = node.end_byte
        colon_index = source_bytes.find(b':', start, end)
        if colon_index == -1:
            # fallback, should not happen in valid control statements
            colon_index = end
        return source_bytes[start:colon_index + 1].decode("utf-8").strip()
    
    def traverse(node, source_bytes, line_index, current_structure=[]):
        CONTROL_FLOW_TYPES = {
            "if_statement",
            "while_statement",
            "for_statement",
            "try_statement",
            "with_statement",
            "match_statement",
            "except_clause",  # optional: narrower scope
            "else_clause",
            "finally_clause"
        }

        # Check if the current node contains the line number
        if node.start_point[0] <= line_index <= node.end_point[0]:
            # complete here, extract the control flow structure
            if node.type in CONTROL_FLOW_TYPES:
                statement = get_statement(node, source_bytes)
                current_structure.append({
                    "type": node.type,
                    "statement": statement,
                    "start_line": node.start_point[0],
                    "end_line": node.end_point[0]
                })

            for child in node.children:
                result = traverse(child, source_bytes, line_index, current_structure)
                if result:
                    return result
                
            return current_structure

        return []

    assert language == "python", "Currently only python is supported"
    parser = get_parser(language)

    # Parse the code
    tree = parser.parse(bytes(code, "utf8"))
    root_node = tree.root_node

    structure_path = traverse(root_node, bytes(code, "utf8"), line_index)
    return structure_path

def extract_hunks(commit_url: str, REPOS_PATH: str) -> tuple:
    """
    Given commit url, extract edit hunks from the commit, with its file path and code logic path
    
    Args:
        commit_url: str, the url of the commit
        
    Returns:
        commit_message: str, the message of the commit
        commit_snapshots: dict, key is file path, value is list of snapshot of the file
    """
    commit_sha = commit_url.split("/")[-1]
    project_name = commit_url.split("/")[-3]
    user_name = commit_url.split("/")[-4]
    repo_path = os.path.join(REPOS_PATH, project_name)

    # if not exist, clone to local
    os.makedirs(REPOS_PATH, exist_ok=True)
    if not os.path.exists(repo_path):
        clone_repo(user_name, project_name, REPOS_PATH)
    
    command = f"git -C {repo_path} show {commit_sha} --pretty=%B --no-patch"
    try:
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except:
        raise ValueError(f'1 {commit_url} Error: Error in retrieving commit message')
    commit_message = result.stdout.strip()

    command = f"git -C {repo_path} checkout --force {commit_sha}^"
    try:
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except:
        raise ValueError(f'2 {commit_url} Error: Error in git checkout')
    
    command = f'git -C {repo_path} diff -U10000000 {commit_sha}^ {commit_sha}'
    try:
        result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except:
        raise ValueError(f'1 {commit_url} Error: Error in git diff')
    git_diff_str = result.stdout
    
    file_name_matches = re.finditer(r'diff --git a/(.+) b/(.+)', git_diff_str)
    file_names = []
    for match in file_name_matches:
        before_filename = match.group(1)
        after_filename = match.group(2)
        try:
            assert before_filename == after_filename
        except:
            raise ValueError(f"{commit_url} Error: Contain edit changes file name: {before_filename} -> {after_filename}")
        file_names.append(before_filename)
    
    if detect_extension(file_names):
        raise ValueError(f'{commit_url} Error: Contain edit on non-source files')
    
    # Split into diff section, 1 section = 1 file
    diff_sections = re.findall(r'diff --git[^\n]*\n.*?(?=\ndiff --git|$)', git_diff_str, re.DOTALL)
    all_edit_num = 0
    commit_snapshots = {}
    for i, section in enumerate(diff_sections):
        # Parse file name (w/ path), make sure edit don't change file name
        file_name_match = re.match(r'diff --git a/(.+) b/(.+)', section)
        if file_name_match:
            file_name = file_name_match.group(1)
        else:
            raise ValueError(f"5 {commit_url} Error: file name contain non-ascii char")
        
        # Get the diff of the whole file
        # (if -U{number} is set large enough, a file should contain only 1 @@ -xx,xx +xx,xx @@)
        # we can only make snapshot based on the diff of the whole file
        match = re.search(r'@@[^\n]*\n(.+)', section, re.DOTALL)
        if not match:
            raise ValueError(f"4 {commit_url} Error: Edit fail to match @@ -xx,xx +xx,xx @@")
        # 匹配@@行之后的内容
        after_at_symbol_content = match.group(1)
        # form snapshot: each element:
        # type 1: list of line of code, unchanged
        # type 2: dict of edit, have key: "type", "before", "after"
        snapshot, _ = convert_diff_section_to_snapshot(after_at_symbol_content)
        
        # count line index
        parent_version_line_index = 0
        child_version_line_index = 0
        for window in snapshot:
            if type(window) is list:
                parent_version_line_index += len(window)
                child_version_line_index += len(window)
            else:
                window["parent_version_range"] = {
                    "start": parent_version_line_index,
                    "end": parent_version_line_index + len(window["before"])
                }
                window["child_version_range"] = {
                    "start": child_version_line_index,
                    "end": child_version_line_index + len(window["after"])
                }
                if window["before"] != []:
                    parent_version_line_index += len(window["before"])
                if window["after"] != []:
                    child_version_line_index += len(window["after"])
        commit_snapshots[file_name] = snapshot
        
    # extract code logic path for each hunk
    hunk_idx = 0
    for rel_file_path, snapshot in commit_snapshots.items():
        abs_file_path = os.path.join(repo_path, rel_file_path)
        file_content = ""
        for window in snapshot:
            if isinstance(window, list):
                file_content += "".join(window)
            else:
                file_content += "".join(window["before"])

        for widx, window in enumerate(snapshot):
            if type(window) is list:
                continue
            # only deal with edit hunks

            line_index = window["parent_version_range"]["start"]
            language = check_language(abs_file_path)
                    
            if window["before"] == [] and window["after"] != []:
                line_index -= 1

            prev_window = snapshot[widx-1] if widx > 0 else None
            next_window = snapshot[widx+1] if widx < len(snapshot)-1 else None
            
            if prev_window is None:
                window["prefix"] = []
            else:
                window["prefix"] = prev_window[-1 * min(3, len(prev_window)):]
            
            if next_window is None:
                window["suffix"] = []
            else:
                window["suffix"] = next_window[:min(3, len(next_window))]
                    
            structural_path = find_code_structure(file_content, line_index, language)
            control_flow = find_control_flow(file_content, line_index, language)
            window["control_flow"] = control_flow
            window["structural_path"] = structural_path
            window["idx"] = hunk_idx
            window["simulated"] = False
            window["allowed_as_next"] = False
            window["file_path"] = rel_file_path
            hunk_idx += 1
            
    return commit_message, commit_snapshots

def get_version(snapshot, version):
    assert version in ["parent", "child"]
    version_content = []
    for window in snapshot:
        if isinstance(window, list):
            version_content.extend(window)
        else:
            if version == "parent":
                version_content.extend(window["before"])
            else:
                version_content.extend(window["after"])
        
    return version_content

def add_info_to_snapshots(snapshots):
    for rel_file_path, snapshot in snapshots.items():
        pre_edit_line_idx = 0
        post_edit_line_idx = 0
        parent_version_content = "".join(get_version(snapshot, "parent"))
        for widx, window in enumerate(snapshot):
            if isinstance(window, list):
                pre_edit_line_idx += len(window)
                post_edit_line_idx += len(window)
                continue
            window["parent_version_range"] = {
                "start": pre_edit_line_idx,
                "end": pre_edit_line_idx + len(window["before"]),
            }
            pre_edit_line_idx += len(window["before"])
            window["child_version_range"] = {
                "start": post_edit_line_idx,
                "end": post_edit_line_idx + len(window["after"]),
            }
            post_edit_line_idx += len(window["after"])

            pre_edit_line_idx = window["parent_version_range"]["start"]
            post_edit_line_idx = window["parent_version_range"]["end"]

            line_index = window["parent_version_range"]["start"]
            language = "python" #check_language(rel_file_path)
            # print("[WARNING:SUT] At src/optimization/utils.py, assume language is python")

            if window["before"] == [] and window["after"] != []:
                line_index -= 1

            prev_window = snapshot[widx-1] if widx > 0 else None
            next_window = snapshot[widx+1] if widx < len(snapshot)-1 else None
            
            if prev_window is None:
                window["prefix"] = []
            else:
                window["prefix"] = prev_window[-1 * min(3, len(prev_window)):]
            
            if next_window is None:
                window["suffix"] = []
            else:
                window["suffix"] = next_window[:min(3, len(next_window))]

            structural_path = find_code_structure(parent_version_content, line_index, language)
            control_flow = find_control_flow(parent_version_content, line_index, language)

            window["control_flow"] = control_flow
            window["structural_path"] = structural_path
            window["file_path"] = rel_file_path

    return snapshots

def snapshot_2_locations(snapshots):
    """
    Convert snapshots to edit locations.
    """
    enriched_snapshots = add_info_to_snapshots(snapshots)
    replace_edit_locations = []
    insert_edit_locations = []

    has_confidence = False
    for file_path, snapshot in snapshots.items():
        line_idx = 0
        for window in snapshot:
            if isinstance(window, list):
                line_idx += len(window)
            else:
                if "confidence" in window and window["confidence"] is not None:
                    has_confidence = True
                if window["before"]:
                    loc = {
                        "file_path": file_path,
                        "atLines": [i for i in range(line_idx, line_idx + len(window["before"]))],
                        "editType": "replace",
                        "after": window["after"],
                        "confidence": window.get("confidence", None),
                        "suggestionRank": None
                    }
                    if "idx" in window:
                        loc["idx"] = window["idx"]
                    if "allowed_as_next" in window:
                        loc["allowed_as_next"] = window["allowed_as_next"]
                    replace_edit_locations.append(loc)
                    line_idx += len(window["before"])
                else:
                    loc = {
                        "file_path": file_path,
                        "atLines": [line_idx],
                        "editType": "insert",
                        "after": window["after"],
                        "structural_path": window["structural_path"],
                        "confidence": window.get("confidence", None),
                        "suggestionRank": None
                    }
                    if "idx" in window:
                        loc["idx"] = window["idx"]
                    if "allowed_as_next" in window:
                        loc["allowed_as_next"] = window["allowed_as_next"]
                    insert_edit_locations.append(loc)

    if has_confidence:
        confidences = [loc["confidence"] for loc in replace_edit_locations + insert_edit_locations]
        sorted_confidences = sorted(confidences, reverse=True)
        for i, loc in enumerate(replace_edit_locations + insert_edit_locations):
            loc["suggestionRank"] = sorted_confidences.index(loc["confidence"])
    
    return replace_edit_locations, insert_edit_locations

def overlap_percentage(list_a, list_b):
    set_a = set(list_a)
    set_b = set(list_b)
    overlap = set_a & set_b
    avg_len = (len(list_a) + len(list_b)) / 2
    return len(overlap) / avg_len if avg_len > 0 else 0.0

def indexing_edits_within_snapshots(snapshots): # Also used in optimization/utils.py
    """
    Indexing edits within snapshots.
    """
    idx = 0
    for file_path, snapshot in snapshots.items():
        for window in snapshot:
            if isinstance(window, list):
                continue
            if not isinstance(window, dict):
                import json
                with open("debug.json", "w") as f:
                    json.dump(snapshots, f, indent=4)
                raise ValueError("Window is not a dict")
            window["idx"] = idx
            idx += 1
    return snapshots

def get_bleu(pred, gdth):
    if isinstance(pred, list):
        pred = "".join(pred)
    if isinstance(gdth, list):
        gdth = "".join(gdth)

    (goldMap, predictionMap) = direct_computeMaps(pred, gdth)
    bleu_score = bleuFromMaps(goldMap, predictionMap)
    return bleu_score[0]

def deduplicate_edits(edit_list):
    seen = set()
    deduped = []

    for item in edit_list:
        detail = item["detail"]
        key = (
            detail["abs_file_path"],
            item["version"],
            tuple(sorted(detail["position"].items()))  # (start, end)
        )
        # position dict → tuple of tuples
        key = (
            detail["abs_file_path"],
            item["version"],
            (
                detail["position"]["start"]["line"],
                detail["position"]["start"]["column"],
                detail["position"]["end"]["line"],
                detail["position"]["end"]["column"],
            )
        )
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return deduped

def formalize_input(edit1, edit2):
    edit1_str = f"<file_path>{edit1['file_path']}</file_path>\n<structural_path>\n"
    edit2_str = f"<file_path>{edit2['file_path']}</file_path>\n<structural_path>\n"

    def construct_structual_and_control_flow(s, edit):
        for idx, structural_path in enumerate(edit['structural_path']):
            indent = "\t"* idx
            s += f"{indent}{structural_path['signature']}\n"
        s += "</structural_path>\n"
        # s += "<control_flow>\n"
        # if edit["control_flow"] is None:
        #     edit["control_flow"] = []
        # for idx, control_flow in enumerate(edit['control_flow'], start=len(edit['structural_path'])):
        #     indent = "\t"* idx
        #     s += f"{indent}{control_flow['statement']}\n"
        # s += "</control_flow>\n"
        s += "<code>\n"
        return s

    edit1_str = construct_structual_and_control_flow(edit1_str, edit1)
    edit2_str = construct_structual_and_control_flow(edit2_str, edit2)
    
    edit1_dep_info = []
    edit2_dep_info = []
    for dep_info in edit1["base_dependency_caller"] + edit1["base_dependency_callee"]:
        if dep_info["to_hunk_idx"] == edit2['idx']:
            dep_info["version"] = "base"
            edit1_dep_info.append(dep_info)
    for dep_info in edit1["head_dependency_callee"] + edit1["head_dependency_caller"]:
        if dep_info["to_hunk_idx"] == edit2['idx']:
            dep_info["version"] = "head"
            edit1_dep_info.append(dep_info)
    
    for dep_info in edit2["base_dependency_caller"] + edit2["base_dependency_callee"]:
        if dep_info["to_hunk_idx"] == edit1['idx']:
            dep_info["version"] = "base"
            edit2_dep_info.append(dep_info)
    for dep_info in edit2["head_dependency_callee"] + edit2["head_dependency_caller"]:
        if dep_info["to_hunk_idx"] == edit1['idx']:
            dep_info["version"] = "head"
            edit2_dep_info.append(dep_info)

    def construct_code(s, edit, dep_infos):
        dep_infos = deduplicate_edits(dep_infos)
        codes = []
        # for idx, code in enumerate(edit["prefix"], start=-len(edit["prefix"])):
        for idx, code in enumerate(edit["prefix"][-1:], start=-1):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["before"], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["start"] + idx,
                "after_idx": None,
                "code": code
            })
        
        for idx, code in enumerate(edit["after"], start = 0):
            codes.append({
                "before_idx": None,
                "after_idx": edit["child_version_range"]["start"] + idx,
                "code": code
            })

        for idx, code in enumerate(edit["suffix"][:1], start = 0):
            codes.append({
                "before_idx": edit["parent_version_range"]["end"] + idx,
                "after_idx": edit["child_version_range"]["end"] + idx,
                "code": code
            })

        idxs = [len(str(code["before_idx"])) for code in codes if code["before_idx"] is not None]
        idxs.extend([len(str(code["after_idx"])) for code in codes if code["after_idx"] is not None])
        max_len = max(idxs) if idxs else 0

        for code in codes:
            if code["before_idx"] is None:
                code["before_idx"] = " " * max_len
                special_token = "+"
            elif code["after_idx"] is None:
                code["after_idx"] = " " * max_len
                special_token = "-"
            else:
                special_token = " "

            deps_at_this_line = []
            for dep in dep_infos:
                if dep["version"] == "base" and special_token == "-" and dep["detail"]["position"]["start"]["line"] == code["before_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
                elif dep["version"] == "head" and special_token == "+" and dep["detail"]["position"]["start"]["line"] == code["after_idx"]:
                    deps_at_this_line.append([dep["detail"]["position"]["start"]["column"], dep["detail"]["position"]["end"]["column"]])
            # sort by start column
            deps_at_this_line.sort(key=lambda x: x[0])
            for idx, dep in enumerate(deps_at_this_line):
                # add offset to column
                dep[0] += 11 * idx
                dep[1] += 11 * idx
                # insert </dep> at dep[1] for code["code"]
                code["code"] = code["code"][:dep[1]] + "</dep>" + code["code"][dep[1]:]
                # insert <dep> at dep[0] for code["code"]
                code["code"] = code["code"][:dep[0]] + "<dep>" + code["code"][dep[0]:]

            s += f"{code['before_idx']:>{max_len}} {code['after_idx']:>{max_len}} {special_token}   {code['code']}"

        s += "</code>\n"
        return s
        
    edit1_str = construct_code(edit1_str, edit1, edit1_dep_info)
    edit2_str = construct_code(edit2_str, edit2, edit2_dep_info)

    return edit1_str, edit2_str 

def chatgpt(prompt, model="claude-sonnet-4-20250514", temperature=0.0, n=1, top_p=1, stop=None, max_tokens=4096, 
                  presence_penalty=0, frequency_penalty=0, logit_bias={}, timeout=120):
    """
    Query chatgpt for response
    """
    messages = [{"role": "user", "content": prompt}]
    payload = {
        "messages": messages,
        "model": model,
        "temperature": temperature,
        "n": n, # the number of different completions
        "top_p": top_p,
        "stop": stop,
        "max_tokens": max_tokens,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
        "logit_bias": logit_bias
    }
    retries = 0
    while True:
        try:
            r = requests.post(f'{OPENAI_BASE_URL}/chat/completions',
                headers = {
                    "Authorization": f"Bearer {OPENAI_KEY}",
                    "Content-Type": "application/json"
                },
                json = payload,
                timeout=timeout
            )
            if r.status_code != 200:
                print(f"Status code: {r.status_code}, retry")
                retries += 1
                time.sleep(1)
            else:
                break
        except requests.exceptions.ReadTimeout:
            print("ReadTimeout, retry")
            time.sleep(1)
            retries += 1
        except requests.exceptions.ConnectionError:
            print("ConnectionError, retry")
            time.sleep(1)
            retries += 1
    r = r.json()
    # NOTE: this return type should not be changed, as this func is used for multiple purposes.
    return [choice['message']['content'] for choice in r['choices']]

def get_full_project(COMMIT: str) -> dict[str, list[str] | bytes]:
    # git checkout to base version of this commit
    result = subprocess.run(
        ['git', 'checkout', "-f", f"{COMMIT.commit_sha}^"],
        cwd=COMMIT.repo_dir,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Checkout failed:\n{result.stderr}")
    else:
        print(f"[MESSAGE:SUT] Checked out to base version.")

    project = {}
    for root, _, files in os.walk(COMMIT.repo_dir):
        for file in files:
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, COMMIT.repo_dir)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    project[rel_path] = f.read().splitlines(keepends=True)
            except Exception:
                try:
                    with open(file_path, "rb") as f:
                        project[rel_path] = f.read()  # store raw bytes
                except Exception:
                    continue  # skip unreadable files completely
    return project