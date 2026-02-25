import os
import math
import time
import json
import requests
import platform

from dotenv import load_dotenv
from tree_sitter import Language, Parser

current_path = os.path.abspath(os.path.dirname(__file__))
root_path = os.path.abspath(os.path.join(current_path, "../../"))
load_dotenv(dotenv_path=os.path.join(root_path, ".config"))

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_TOKEN = os.getenv("OPENAI_TOKEN")

def write_project(project: dict, project_name: str, repos_dir: str):
    """
    Write the project to local.
    """
    project_dir = os.path.join(repos_dir, project_name)
    os.makedirs(project_dir, exist_ok=True)

    for file_name, file_content in project.items():
        file_path = os.path.join(project_dir, file_name)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        if isinstance(file_content, bytes):
            # Handle binary content
            with open(file_path, "wb") as f:
                f.write(file_content)
        else:
            # Handle list[list[str]|dict]
            str_content = ""
            for window in file_content:
                if isinstance(window, list):
                    str_content += "".join(window)
                else:
                    str_content += "".join(window["after"])

            with open(file_path, "w") as f:
                f.write(str_content)

def indexing_edits_within_snapshots(snapshots): # Also used in simulation/utils.py
    """
    Indexing edits within snapshots.
    """
    idx = 0
    for file_path, snapshot in snapshots.items():
        for window in snapshot:
            if isinstance(window, list):
                continue
            window["idx"] = idx
            idx += 1
    return snapshots

def chatgpt_token_probs(prompt, model="gpt-4.1", temperature=0.0, top_p=1, stop=None, max_tokens=256, presence_penalty=0, frequency_penalty=0, logit_bias={}, timeout=90):
    """
    Return per-token probabilities for a single completion as:
      List[{"token": str, "prob": float}]
    """
    
    messages = [{"role": "user", "content": prompt}]
    payload = {
        "messages": messages,
        "model": model,
        "temperature": temperature,
        "n": 1,                      # enforce single completion -> list[dict]
        "top_p": top_p,
        "stop": stop,
        "max_tokens": max_tokens,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
        "logit_bias": logit_bias,
        "logprobs": True,            # request per-token logprobs
        "top_logprobs": 0            # we don't need alternatives
    }

    retries = 0
    while True:
        try:
            r = requests.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            if r.status_code != 200:
                print(f"Status code: {r.status_code}, retry")
                retries += 1
                time.sleep(1)
            else:
                break
        except requests.exceptions.ReadTimeout:
            print("ReadTimeout, retry")
            time.sleep(1); retries += 1
        except requests.exceptions.ConnectionError:
            print("ConnectionError, retry")
            time.sleep(1); retries += 1

    data = r.json()
    choices = data.get("choices", [])
    if not choices:
        return []

    ch = choices[0]
    # Primary schema: choice["logprobs"]["content"] -> list of items with "token" and "logprob"
    content_lp = None
    if isinstance(ch.get("logprobs"), dict):
        content_lp = ch["logprobs"].get("content")

    token_probs = []
    if isinstance(content_lp, list):
        for item in content_lp:
            tok = item.get("token")
            logp = item.get("logprob")
            if tok is not None and logp is not None:
                try:
                    token_probs.append({"token": tok, "prob": math.exp(logp)})
                except Exception:
                    token_probs.append({"token": tok, "prob": None})
    else:
        # Fallback for older/alternative schemas
        lp = ch.get("logprobs")
        toks = lp.get("tokens") if isinstance(lp, dict) else None
        lps = (lp.get("token_logprobs") or lp.get("logprobs")) if isinstance(lp, dict) else None
        if isinstance(toks, list) and isinstance(lps, list) and len(toks) == len(lps):
            for tok, logp in zip(toks, lps):
                try:
                    token_probs.append({"token": tok, "prob": math.exp(logp) if logp is not None else None})
                except Exception:
                    token_probs.append({"token": tok, "prob": None})
        else:
            raise RuntimeError("This model/endpoint did not return per-token logprobs.")

    generated_text = ch.get("message", {}).get("content", "")
    label_prob = get_label_prob(token_probs)

    return generated_text, label_prob

def claude_token_probs(prompt, model="claude-sonnet-4-20250514", temperature=0.0, top_p=1, stop=None, max_tokens=512, presence_penalty=0, frequency_penalty=0, timeout=200):
    cost_table = {
        "claude-sonnet-4-20250514": {
            "input_per_M": 3,
            "output_per_M": 15
        }
    }
    if model not in cost_table:
        raise ValueError(f"Cost information for model {model} is not available.")
    
    messages = [{"role": "user", "content": prompt}]
    payload = {
        "messages": messages,
        "model": model,
        "temperature": temperature,
        "n": 1,
        "top_p": top_p,
        "stop": stop,
        "max_tokens": max_tokens,
        "presence_penalty": presence_penalty,
        "frequency_penalty": frequency_penalty,
    }

    retries = 0
    time_cost = None
    while True:
        try:
            start = time.time()
            r = requests.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            end = time.time()
            time_cost = end - start
            if r.status_code != 200:
                print(f"Status code: {r.status_code}, retry")
                retries += 1
                if retries == 3:
                    raise RuntimeError("Max retries exceeded")
                time.sleep(2)
            elif r.status_code == 403:
                raise PermissionError("Access denied! Probability runout of API usage.")
            else:
                break
        except requests.exceptions.ReadTimeout:
            print("ReadTimeout, retry")
            time.sleep(2); retries += 1
            if retries == 3:
                raise RuntimeError("Max retries exceeded")
        except requests.exceptions.ConnectionError:
            print("ConnectionError, retry")
            time.sleep(2); retries += 1
            if retries == 3:
                raise RuntimeError("Max retries exceeded")

    data = r.json()
    choices = data.get("choices", [])
    if not choices:
        return []

    ch = choices[0]
    
    return {
        "message": ch['message']['content'],
        "time": time_cost,
        "token": data['usage']['total_tokens'],
        "price": data['usage']['prompt_tokens'] / 1000000 * cost_table[model]['input_per_M'] + data['usage']['completion_tokens'] / 1000000 * cost_table[model]['output_per_M']
    }

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

def check_language(file_path: str): # Also used in simulation/utils.py
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

def get_parser(language): # Also used in simulation/utils.py
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

def find_code_structure(code, line_index, language): # Also used in simulation/utils.py
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

def find_control_flow(code, line_index, language): # Also used in simulation/utils.py

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
            language = check_language(rel_file_path)

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

            if language is None:
                structural_path = []
                control_flow = []
            else:
                structural_path = find_code_structure(parent_version_content, line_index, language)
                control_flow = find_control_flow(parent_version_content, line_index, language)

            window["control_flow"] = control_flow
            window["structural_path"] = structural_path
            window["file_path"] = rel_file_path

    return snapshots

def formalize_single_input(edit1):
    edit1_str = f"<file_path>{edit1['file_path']}</file_path>\n<structural_path>\n"

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

    def construct_code(s, edit):
        codes = []
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

            s += f"{code['before_idx']:>{max_len}} {code['after_idx']:>{max_len}} {special_token}   {code['code']}"

        s += "</code>\n"
        return s
        
    edit1_str = construct_code(edit1_str, edit1)

    return edit1_str 

def get_label_prob(token_probs):
    last_10_token_probs = token_probs[-20:]
    labels = ["0 before 1", "1 before 1", "bi-directional", "no relation"]
    
    label_prob = 0
    selected_tokens = []
    selected_probs = []
    for token_prob in last_10_token_probs:
        if any(label.startswith("".join(selected_tokens)+token_prob["token"]) for label in labels):
            selected_tokens.append(token_prob["token"])
            selected_probs.append(token_prob["prob"])
            if "".join(selected_tokens) in labels:
                break
        else:
            selected_tokens = []
            selected_probs = []
        
    return sum(selected_probs) / len(selected_probs)

def extract_prior_edits(edit_snapshots):
    edit_snapshots = add_info_to_snapshots(edit_snapshots)
    prior_edits = []
    for rel_file_path, snapshot in edit_snapshots.items():
        for window in snapshot:
            if isinstance(window, dict):
                prior_edits.append(window)

    # sort in ascending order based on timestamp
    prior_edits.sort(key=lambda x: max(x["head_timestamps"] + x["base_timestamps"]))
    return prior_edits

if __name__ == "__main__":
    claude_token_probs("Hello, how are you?", model="claude-sonnet-4-20250514")