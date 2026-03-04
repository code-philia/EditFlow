import os
import re
import json
import torch
import difflib
import platform
import warnings
import subprocess
import numpy as np
import rapidfuzz.fuzz as fuzz

from .construct_input import formalize_input
from dotenv import load_dotenv
from jsonschema import validate
from collections import defaultdict
from tree_sitter import Language, Parser
from transformers import RobertaTokenizer, RobertaModel

CURR_FILE_DIR=os.path.dirname(os.path.abspath(__file__))
ENV_DIR=os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ENV_PATH = os.path.join(ENV_DIR, ".config")
load_dotenv(ENV_PATH)
REPOS_PATH=os.getenv("REPOS_PATH")

def format_commit_data(commit_data):
    bullet_points = []
    
    # Summary
    bullet_points.append(f"- Summary: {commit_data['summary']}")
    
    # File changes
    bullet_points.append("- File Changes:")
    for file, description in commit_data["info"].items():
        bullet_points.append(f"  - `{file}`: {description}")
    
    # Impact Analysis
    bullet_points.append(f"- Impact Analysis: {commit_data['impact_analysis']}")
    
    # Edit Types
    bullet_points.append("- Edit Types:")
    for file, edits in commit_data["edit_types"].items():
        edit_list = ", ".join(edits)
        bullet_points.append(f"  - `{file}`: {edit_list}")
    
    # Affected Components
    bullet_points.append("- Affected Components: " + ", ".join(commit_data["affected_components"]))
    
    return "\n".join(bullet_points)

# load codebert model
tokenizer = RobertaTokenizer.from_pretrained("microsoft/codebert-base")
model = RobertaModel.from_pretrained("microsoft/codebert-base")

def rate_edit_hunk_pair(edit_hunk1: dict, edit_hunk2: dict, print_info=False):
    """
    Create a feature vector for comparing pairs of hunks.
    
    Rating rules:
    1. If 2 hunks in the same file, + 0/1 point
    2. If 2 hunks share k same logic path, + k/len(logic path) points
    3. If 2 hunks share same diff-identifiers (same identifiers added / removed), + 1 point
    4. If 2 hunks are lexically similar, + [0,1] point
    5. If 1 hunk resides in a function/method/class/struct that invoked by the other hunk, + 1 point
    
    Args:
        edit_hunk1: dict, the first edit hunk
        edit_hunk2: dict, the second edit hunk
        
    Returns:
        score: int, the score of the probability of the 2 edit hunks exist a partial order
    """
    vector = []
    
    # Rule 1: If 2 hunks in the same file, + 1 point
    if edit_hunk1["file_path"] == edit_hunk2["file_path"]:
        vector.append(1)
        if print_info:
            print(f"Same file (1 pt): {edit_hunk1['file_path']}")
    else:
        vector.append(0)
    
    # Rule 2: If 2 hunks share k same logic path, + k points
    logic_path_score = 0
    for i in range(min(len(edit_hunk1["structural_path"]), len(edit_hunk2["structural_path"]))):
        if edit_hunk1["structural_path"][i] == edit_hunk2["structural_path"][i]:
            logic_path_score += 1
            if print_info:
              print(f"Same logic path (1 pt): {edit_hunk1['structural_path'][i]['signature']}")
        else:
            break
          
    if (len(edit_hunk1["structural_path"]) + len(edit_hunk2["structural_path"])) == 0:
        vector.append(0)
    else:
      vector.append(logic_path_score / max(len(edit_hunk1["structural_path"]), len(edit_hunk2["structural_path"])))
    
    # Rule 3: If 2 hunks share same diff-identifiers (same identifiers added / removed), + 1 point
    hit = False
    h1_del_identifiers = set(edit_hunk1["identifiers_before"]) - set(edit_hunk1["identifiers_after"])
    h2_del_identifiers = set(edit_hunk2["identifiers_before"]) - set(edit_hunk2["identifiers_after"])
    if len(h1_del_identifiers & h2_del_identifiers) > 0:
        hit = True
    
    h1_add_identifiers = set(edit_hunk1["identifiers_after"]) - set(edit_hunk1["identifiers_before"])
    h2_add_identifiers = set(edit_hunk2["identifiers_after"]) - set(edit_hunk2["identifiers_before"])
    if len(h1_add_identifiers & h2_add_identifiers) > 0:
        hit = True
    if hit:
        vector.append(1)
        if print_info:
            print(f"Same diff-identifiers (1 pt): {h1_add_identifiers & h2_add_identifiers}")
    else:
        vector.append(0)
    
    # Rule 4: If 2 hunks are lexically similar, + [0,1] point
    score = 0
    before_similarity = fuzz.ratio("".join(edit_hunk1["before"]), "".join(edit_hunk2["before"])) / 100
    after_similarity = fuzz.ratio("".join(edit_hunk1["after"]), "".join(edit_hunk2["after"])) / 100
    cross_similarity1 = fuzz.ratio("".join(edit_hunk1["before"]), "".join(edit_hunk2["after"])) / 100
    cross_similarity2 = fuzz.ratio("".join(edit_hunk1["after"]), "".join(edit_hunk2["before"])) / 100
    cross_similarity = (cross_similarity1 + cross_similarity2) / 2
    correspond_similarity = (before_similarity + after_similarity) / 2
    score += max(correspond_similarity, cross_similarity)
    vector.append(score)
    if print_info:
        print(f"Lexical similarity ({(before_similarity + after_similarity) / 2}pt)")
    
    score = 0
    # Tokenize the before and after code snippets
    inputs1 = tokenizer("".join(edit_hunk1["before"]), return_tensors="pt", truncation=True, padding=True)
    inputs2 = tokenizer("".join(edit_hunk2["before"]), return_tensors="pt", truncation=True, padding=True)
    inputs3 = tokenizer("".join(edit_hunk1["after"]), return_tensors="pt", truncation=True, padding=True)
    inputs4 = tokenizer("".join(edit_hunk2["after"]), return_tensors="pt", truncation=True, padding=True)
    # Move tensors to GPU if available
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    inputs1 = {key: value.to(device) for key, value in inputs1.items()}
    inputs2 = {key: value.to(device) for key, value in inputs2.items()}
    inputs3 = {key: value.to(device) for key, value in inputs3.items()}
    inputs4 = {key: value.to(device) for key, value in inputs4.items()}
    model.to(device)
    # Compute embeddings
    with torch.no_grad():
        embeddings1 = model(**inputs1).last_hidden_state.mean(dim=1)
        embeddings2 = model(**inputs2).last_hidden_state.mean(dim=1)
        embeddings3 = model(**inputs3).last_hidden_state.mean(dim=1)
        embeddings4 = model(**inputs4).last_hidden_state.mean(dim=1)
    # Compute cosine similarity
    before_similarity = torch.nn.functional.cosine_similarity(embeddings1, embeddings2).item()
    after_similarity = torch.nn.functional.cosine_similarity(embeddings3, embeddings4).item()
    # Add to score
    score += (before_similarity + after_similarity) / 2
    vector.append(score)
    if print_info:
        print(f"Lexical similarity ({(before_similarity + after_similarity) / 2}pt)")
    
    # Rule 5: If 1 hunk resides in a function/method/class/struct that invoked by the other hunk, + 1 point
    hunk1_logic_path_identifiers = [path["name"] for path in edit_hunk1["structural_path"]]
    hunk2_logic_path_identifiers = [path["name"] for path in edit_hunk2["structural_path"]]
    hit = False
    for identifier in hunk1_logic_path_identifiers:
        if identifier in "".join(edit_hunk2["before"]) or identifier in "".join(edit_hunk2["after"]):
            hit = True
            break
    for identifier in hunk2_logic_path_identifiers:
        if identifier in "".join(edit_hunk1["before"]) or identifier in "".join(edit_hunk1["after"]):
            hit = True
            break
    if hit:
        vector.append(1)
        if print_info:
            print(f"Invoked by: {edit_hunk1['idx']} {edit_hunk2['idx']}")
    else:
        vector.append(0)
        
    # Rule 6: Same Edit Operation
    edit_type1 = edit_hunk1.get("edit_type", "")
    edit_type2 = edit_hunk2.get("edit_type", "")
    if edit_type1 and edit_type2:
        op_score = 1.0 if edit_type1 == edit_type2 else 0.0
    else:
        op_score = 0.0  # or handle missing info differently
    vector.append(op_score)
            
    # Rule 7: Different Edit Operation
    if edit_type1 and edit_type2:
        op_score = 1.0 if edit_type1 != edit_type2 else 0.0
    else:
        op_score = 0.0
    vector.append(op_score)
    if print_info:
        if op_score:
            print(f"Matching edit type (+1): {edit_type1}")
        else:
            print(f"Different edit types: {edit_type1} vs {edit_type2}")
        
    score = sum(vector)
    return score, vector

def find_code_structure(code, line_index, language):
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
        
        return function_name, call_info if function_name else (None, None)

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
        # 定义返回的声明和名称
        declaration = ""
        name = None

        # 解析类声明
        if node.type == node_types['class']:
            for child in node.children:
                if child.type == "modifiers":  # 修饰符 (e.g., public, static)
                    for grandchild in child.children:
                        if grandchild.text.decode("utf-8").startswith("@"):
                            continue
                        declaration += grandchild.text.decode("utf-8") + " "
                elif child.type == "class":
                    declaration += "class "
                elif child.type == "identifier":  # 类名
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "type_parameters":  # 泛型类型参数
                    declaration += child.text.decode("utf-8")
                elif child.type == "superclass":
                    declaration += " " + child.text.decode("utf-8")
                elif child.type == "implements":  # 实现的接口
                    declaration += " implements "
                    for grandchild in child.children:  # 处理 implements 后面的接口
                        declaration += grandchild.text.decode("utf-8") + ", "
                    declaration = declaration.rstrip(", ")  # 去掉多余的逗号
                elif child.type == "{":  # 类体开始
                    declaration += " {"
            return declaration, name

        # 解析方法声明
        elif node.type == node_types['function']:
            for child in node.children:
                if child.type == "modifiers":  # 修饰符 (e.g., public, static)
                    for grandchild in child.children:
                        if grandchild.text.decode("utf-8").startswith("@"):
                            continue
                        declaration += grandchild.text.decode("utf-8") + " "
                elif child.type == "type":  # 方法返回类型
                    declaration += child.text.decode("utf-8") + " "
                elif child.type == "identifier":  # 方法名
                    declaration += child.text.decode("utf-8")
                    name = child.text.decode("utf-8")
                elif child.type == "parameters":  # 参数列表
                    declaration += child.text.decode("utf-8")
                elif child.type == "formal_parameters":
                    declaration += child.text.decode("utf-8")
                elif child.type.endswith("_type"):
                    declaration += child.text.decode("utf-8") + " "
                elif child.type == "throws":  # 抛出的异常
                    # declaration += " throws "
                    for grandchild in child.children:  # 处理 throws 后面的异常类型
                        if "throws" in grandchild.text.decode("utf-8"):
                            declaration += " "
                        declaration += grandchild.text.decode("utf-8") + " "
                    declaration = declaration.rstrip(", ")  # 去掉多余的逗号
                elif child.type == "{":  # 方法体开始
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
            "get_signature_fn": get_declaration_text_py,
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
                    
                    # Add argument information if found
                    if argument_info:
                        call_entry["argument"] = argument_info
                    
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

    # 获取行号的结构路径
    structure_path = traverse(root_node)
    return structure_path

def get_parser(language):
    assert language in ["python", "go", "java", "javascript", "typescript"], "Currently only python, go, java, javascript and typescript are supported"
    system = platform.system().lower()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    tree_sitter_dir = os.path.normpath(os.path.join(base_dir, "../lib/tree-sitter"))
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

def find_control_flow(code, line_index, language):

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

def check_language(file_path: str):
    # 使用os.path.splitext获取文件名和后缀
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

def snapshot2file(snapshot: list, after_edit_hunk: list[dict]|dict = []):
    if isinstance(after_edit_hunk, dict):
        after_edit_hunk = [after_edit_hunk]
    file_content = ""
    for window in snapshot:
        if type(window) == list:
            file_content += "".join(window)
        else:
            if window in after_edit_hunk:
                file_content += "".join(window["after"])
            else:
                file_content += "".join(window["before"])
    return file_content

def extract_hunks(commit_url: str):
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

    command = f"git -C {repo_path} checkout {commit_sha}^"
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
    for file_path, snapshot in commit_snapshots.items():
        file_path = os.path.join(repo_path, file_path)
        for window in snapshot:
            if type(window) is list:
                continue
            # only deal with edit hunks

            line_index = window["parent_version_range"]["start"]
            language = check_language(file_path)

            with open(file_path, "r") as f:
                file_content = f.read()
                    
            if window["before"] == [] and window["after"] != []:
                line_index -= 1
                    
            structural_path = find_code_structure(file_content, line_index, language)
            control_flow = find_control_flow(file_content, line_index, language)
            window["control_flow"] = control_flow
            window["structural_path"] = structural_path
            window["idx"] = hunk_idx
            hunk_idx += 1
            
    return commit_message, commit_snapshots

def pick_identifiers(code: str, language: str):
    """
    Given a code snippet, pick identifiers from the code
    
    Args:
        code: str, the code snippet
        language: str, the programming language
        
    Returns:
        identifiers: list[str], the identifiers in the code
    """
    parser = get_parser(language)
    # 解析代码生成语法树
    tree = parser.parse(bytes(code, "utf8"))
    root_node = tree.root_node
    
    # 定义不同语言的标识符节点类型
    identifier_types = {
        'python': ['identifier'],
        'go': ['identifier', 'field_identifier', 'type_identifier'],
        'java': ['identifier', 'type_identifier'],
        'javascript': ['identifier', 'property_identifier'],
        'typescript': ['identifier', 'property_identifier', 'type_identifier']
    }
    
    current_language_identifiers = identifier_types[language]
    identifiers = []
    
    # 递归遍历语法树查找标识符
    def traverse_tree(node):
        if node.type in current_language_identifiers:
            identifier = node.text.decode('utf-8')
            if identifier not in identifiers:
                identifiers.append(identifier)
                
        # 递归处理所有子节点
        for child in node.children:
            traverse_tree(child)
    
    # 开始遍历
    traverse_tree(root_node)
    
    identifiers = list(set(identifiers))
    identifiers.sort()
    
    return identifiers
    
def get_hunk_diff(snapshots: dict):
    for file_path, snapshot in snapshots.items():
        for widx, window in enumerate(snapshot):
            # Skip if window is actually a list
            if isinstance(window, list):
                continue
            
            # Determine prefix and suffix from neighboring windows
            prev_window = snapshot[widx-1] if widx > 0 else None
            next_window = snapshot[widx+1] if widx < len(snapshot)-1 else None

            # Prefix lines
            if prev_window and isinstance(prev_window, list) and prev_window:
                prefix_text = prev_window[-min(3, len(prev_window)):]
            else:
                prefix_text = []

            # Suffix lines
            if next_window and isinstance(next_window, list) and next_window:
                suffix_text = next_window[:min(3, len(next_window))]
            else:
                suffix_text = []
                
            prefix_parent_version_range = list(range(window["parent_version_range"]["start"]-len(prefix_text), window["parent_version_range"]["start"]))
            prefix_child_version_range = list(range(window["child_version_range"]["start"]-len(prefix_text), window["child_version_range"]["start"]))
            suffix_parent_version_range = list(range(window["parent_version_range"]["end"], window["parent_version_range"]["end"]+len(suffix_text)))
            suffix_child_version_range = list(range(window["child_version_range"]["end"], window["child_version_range"]["end"]+len(suffix_text)))
            
            parent_version_range = prefix_parent_version_range + list(range(window["parent_version_range"]["start"], window["parent_version_range"]["end"])) + suffix_parent_version_range
            assert len(parent_version_range) == len(prefix_text) + len(window["before"]) + len(suffix_text)
            
            parent_version_range = [i for i in parent_version_range] # 0-indexed
            
            child_version_range = prefix_child_version_range + list(range(window["child_version_range"]["start"], window["child_version_range"]["end"])) + suffix_child_version_range
            assert len(child_version_range) == len(prefix_text) + len(window["after"]) + len(suffix_text)
            
            child_version_range = [i for i in child_version_range] # 0-indexed
            max_digits = max(len(str(abs(num))) for num in parent_version_range + child_version_range)

            # Strip trailing newline from suffix
            if len(suffix_text) > 0:
                suffix_text[-1] = suffix_text[-1].rstrip("\n")

            # Extract before/after code changes
            before_lines = window.get("before", [])
            after_lines = window.get("after", [])

            # Construct logic path
            logic_paths = window.get("structural_path", [])
            
            # hunk_diff = f"At file: {file_path}\nCode:\n"
            hunk_diff = f"File: {file_path}\nCode:\n"
            indent = 0
            if logic_paths == []:
                hunk_diff += "  ...\n"
            for structural_path in logic_paths:
                if structural_path["at_line"] in parent_version_range:
                    indent += 1
                else:
                  hunk_diff += f"{' '* max_digits} {' '* max_digits}    {indent*'    '}{structural_path['signature']}\n"
                  indent += 1
                  hunk_diff += f"{' '* max_digits} {' '* max_digits}    {indent*'    '}...\n"
                    
            
            parent_line_index = 0
            child_line_index = 0
            for line in prefix_text:
                hunk_diff += f"{parent_version_range[parent_line_index]:>{max_digits}} {child_version_range[child_line_index]:>{max_digits}}    {line}"
                # hunk_diff += f"  {line}"
                parent_line_index += 1
                child_line_index += 1
            for line in before_lines:
                hunk_diff += f"{parent_version_range[parent_line_index]:>{max_digits}} {' '*max_digits}  - {line}"
                # hunk_diff += f"- {line}"
                parent_line_index += 1
            for line in after_lines:
                hunk_diff += f"{' '*max_digits} {child_version_range[child_line_index]:>{max_digits}}  + {line}"
                # hunk_diff += f"+ {line}"
                child_line_index += 1
            for line in suffix_text:
                hunk_diff += f"{parent_version_range[parent_line_index]:>{max_digits}} {child_version_range[child_line_index]:>{max_digits}}    {line}"
                # hunk_diff += f"  {line}"
                parent_line_index += 1
                child_line_index += 1
            hunk_diff += f"\n{' '* max_digits} {' '* max_digits}  ...\n"
            
            window["hunk_diff"] = hunk_diff
    return snapshots

def retrieve_relevant_examples(database_vector, vector_index, edit1, edit2, retrive_K=1):
    _, query_vector = rate_edit_hunk_pair(edit1, edit2)
        
    # Calculate mse between query_vector and database_vector
    mse = np.mean((database_vector - query_vector) ** 2, axis=1)
    # Get the top k similar edit hunk pairs index
    topk_index = np.argsort(mse) # TODO: update the number of topk pairs
    # Get the top k similar edit hunk pairs' informaton, including: at which commit, the edit index of 2 hunks
    topk_pairs = [vector_index[str(i)] for i in topk_index]
    retrieved_pairs = []
    for pair in topk_pairs:
        if len(retrieved_pairs) >= retrive_K:
            break
        database_file, hunk1_idx, hunk2_idx = pair

        # open file to get this retrieved edge
        with open(os.path.join(CURR_FILE_DIR, "..", "database", database_file), "r") as f:
            datasample = json.load(f)
            
        edits = get_edits(datasample["commit_snapshots"])
        hunk1 = edits[hunk1_idx]
        hunk2 = edits[hunk2_idx]
        hunk1["commit_url"] = datasample["commit_url"]
        hunk2["commit_url"] = datasample["commit_url"]
        edge = None
        for relation in datasample["partial_orders"]:
            if set([hunk1["idx"], hunk2["idx"]]) == set(relation["edit_hunk_pair"]) and set(relation["edit_hunk_pair"]) != set([edit1["idx"], edit2["idx"]]):
                edge = relation
                break
        if edge:
            retrieved_pairs.append((hunk1, hunk2, edge))
        
    example_str = ""
    for eidx, retrieved_pair in enumerate(retrieved_pairs):
        example_str += f"\nExample {eidx+1}:\n"
        hunk1, hunk2, edge = retrieved_pair
        hunk1_diff, hunk2_diff = formalize_input(hunk1, hunk2)
        example_str += f"<Example Edit 0>\n{hunk1_diff}\n</Example Edit 0>\n"
        example_str += f"<Example Edit 1>\n{hunk2_diff}\n</Example Edit 1>\n"
        example_str += f"Response: \n"
        answer = """{\n\t"context": "...",\n\t"reason": "{reason}",\n\t"edit_order": "{edit_order}",\n\t"confidence_score": 0.7\n}"""
        answer = answer.replace("{reason}", edge["reason"])
        answer = answer.replace("{edit_order}", edge["edit_order"])
        example_str += answer
    return example_str

def get_static_information(cut_paste_edges, copy_paste_edges, positional_edges, edit_idx1, edit_idx2):
    cut_paste_info = []
    for edge in cut_paste_edges:
        if edge["source"] == edit_idx1 and edge["target"] == edit_idx2:
            cut_paste_info.append(f"- Cut-paste relationship: Edit 0 is cut and pasted to Edit 1.\n")
        elif edge["source"] == edit_idx2 and edge["target"] == edit_idx1:
            cut_paste_info.append(f"- Cut-paste relationship: Edit 1 is cut and pasted to Edit 0.\n")
    
    copy_paste_info = []
    for edge in copy_paste_edges:
        if edge["source"] == edit_idx1 and edge["target"] == edit_idx2:
            copy_paste_info.append(f"- Copy-paste relationship: Edit 0 is copied and pasted to Edit 1.\n")
        elif edge["source"] == edit_idx2 and edge["target"] == edit_idx1:
            copy_paste_info.append(f"- Copy-paste relationship: Edit 1 is copied and pasted to Edit 0.\n")
    
    positional_info = []
    for edge in positional_edges:
        if edge["source"] == edit_idx1 and edge["target"] == edit_idx2:
            positional_info.append(f"- Positional order relationship: Edit 0 is before Edit 1.\n")
        elif edge["source"] == edit_idx2 and edge["target"] == edit_idx1:
            positional_info.append(f"- Positional order relationship: Edit 1 is before Edit 0.\n")
    
    return cut_paste_info, copy_paste_info, positional_info

def construct_causal_relation_prompt(
    edit1: dict,
    edit2: dict,
    example_str: str,
    info_dict: dict,
    data: dict
) -> str:
    """
    Construct prompt to query for the causal relationship between 2 edit hunks
    
    Args: 
        edit1: dict, contain keys including: idx, hunk_diff, structural_path
        example_str: str, example edit pairs, in string
        info_dict: dict
        
    Returns:
        prompt: a prompt with slots filled
    """
    prompt = info_dict["prompt_template"]
    prompt = prompt.replace("{examples}", example_str)
            
    edit1["commit_url"] = data["commit_url"]
    edit2["commit_url"] = data["commit_url"]
    diff1, diff2 = formalize_input(edit1, edit2)
    edit_idx1 = edit1["idx"]
    edit_idx2 = edit2["idx"]
    
    diff1 = f"<Edit 0> \n" + diff1 + f"</Edit 0>"
    diff2 = f"<Edit 1> \n" + diff2 + f"</Edit 1>"
    
    # Fill in the hunk diffs
    prompt = prompt.replace("{hunk1}", diff1).replace("{hunk2}", diff2).replace("{edit_idx1}", str(edit_idx1)).replace("{edit_idx2}", str(edit_idx2))
    
    # Fill in commit message and summary
    prompt = prompt.replace("{commit_message}", info_dict["commit_message"])
    prompt = prompt.replace("{summary}", format_commit_data(json.loads(info_dict["summary"])))
    
    return prompt

def add_to_graph(info_dict, partial_orders, edit_idx1, edit_idx2, response):
    def no_dep_between(edit_idx1, edit_idx2, dependency_edges):
        edge_dependency_map = defaultdict(list)
        for edge in dependency_edges:
            edge_dependency_map[(edge["caller_hunk_idx"], edge["callee_hunk_idx"])].append(edge)
            edge_dependency_map[(edge["callee_hunk_idx"], edge["caller_hunk_idx"])].append(edge)
        
        if (edit_idx1, edit_idx2) in edge_dependency_map:
            return False
        else:
            return True
    
    if response["edit_order"] == "no relation":
        return partial_orders
    
    if response['confidence_score'] < 0.5:
        return partial_orders
    
    if response["dependency_as_reason"]:
        response["edit_order"] = "bi-directional"

    assert response["edit_order"] in ["0 before 1", "1 before 0", "bi-directional"]

    if response["dependency_as_reason"] and no_dep_between(edit_idx1, edit_idx2, info_dict["dependency_edges"]):
        return partial_orders
    
    response["edit_hunk_pair"] = [edit_idx1, edit_idx2]
    response["llm"] = info_dict["llm_option"]
    print(f"Add edge: ({edit_idx1}, {edit_idx2}), {response['edit_order']}")
    partial_orders.append(response)
        
    return partial_orders

def contain_minimum_overlap(edit1, edit2, language):
    edit1_old = "".join(edit1["before"])
    edit1_new = "".join(edit1["after"])
    edit2_old = "".join(edit2["before"])
    edit2_new = "".join(edit2["after"])
    edit1_logic = "\n".join([l["signature"] for l in edit1["structural_path"]])
    edit2_logic = "\n".join([l["signature"] for l in edit2["structural_path"]])

    edit1_token_bag = set(pick_identifiers(edit1_old, language) + pick_identifiers(edit1_new, language) + pick_identifiers(edit1_logic, language))
    edit2_token_bag = set(pick_identifiers(edit2_old, language) + pick_identifiers(edit2_new, language) + pick_identifiers(edit2_logic, language))

    if edit1_token_bag.intersection(edit2_token_bag):
        return True
    else:
        return False

def tokenize_by_tree_sitter(code: str, language: str) -> list:
    """
    Tokenize code at a fine-grained level using Tree-sitter.

    Args:
        code (str): Source code as a string.
        language (str): The programming language (e.g., "python", "javascript").

    Returns:
        List[str]: A sequence of tokens extracted from the syntax tree, in order.
    """
    parser = get_parser(language)
    code_bytes = code.encode('utf-8')

    tree = parser.parse(code_bytes)
    root_node = tree.root_node
    tokens = []

    def walk(node):
        if node.child_count == 0:  # Leaf node
            token = code_bytes[node.start_byte:node.end_byte].decode('utf-8').strip()
            tokens.append(token)
        else:
            for child in node.children:
                walk(child)

    walk(root_node)
    return tokens

def string_diff_dict(a: str, b: str, language) -> dict:
    """
    Compute the delta (diff) between two strings.

    Args:
        a (str): The original string.
        b (str): The modified string.
        language (str): The programming language (e.g., "python", "javascript").

    Returns:
        dict: A dictionary with two lists:
            - 'deleted': tokens or lines that exist in `a` but not in `b`
            - 'added': tokens or lines that exist in `b` but not in `a`
    """
    a_tokens = tokenize_by_tree_sitter(a, language)
    b_tokens = tokenize_by_tree_sitter(b, language)

    diff = difflib.ndiff(a_tokens, b_tokens)

    added = []
    deleted = []

    for line in diff:
        if line.startswith('- '):
            deleted.append(line[2:])
        elif line.startswith('+ '):
            added.append(line[2:])

    return {'deleted': deleted, 'added': added}

def get_edits(commit_snapshots):
    edits = []
    for file_path, snapshot in commit_snapshots.items():
        for widx, window in enumerate(snapshot):
            if isinstance(window, dict):
                window["file_path"] = file_path
                window["identifiers_before"] = pick_identifiers("".join(window["before"]), "python")
                window["identifiers_after"] = pick_identifiers("".join(window["after"]), "python")
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
                
                assert window["suffix"] is not None 
                assert window["prefix"] is not None
                edits.append(window)
    return edits

def graph_satisfy_schema(graph):
    schema = {
        "type": "object",
        "properties": {
            "language": {"type": "string"},
            "commit_url": {"type": "string", "format": "uri"},
            "commit_message": {"type": "string"},
            "commit_snapshots": {
                "type": "object",
                "additionalProperties": {
                    "type": "array",
                    "items": {
                        "anyOf": [
                            {
                                "type": "array",
                                "items": {"type": "string"}
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "before": {"type": "array"},
                                    "after": {"type": "array"},
                                    "parent_version_range": {"type": "object"},
                                    "child_version_range": {"type": "object"},
                                    "control_flow": {"type": "array"},
                                    "structural_path": {"type": "array"},
                                    "idx": {"type": "integer"},
                                    "hunk_diff": {"type": "string"},
                                    "file_path": {"type": "string"},
                                    "identifiers_before": {"type": "array"},
                                    "identifiers_after": {"type": "array"},
                                    "prefix": {"type": "array"},
                                    "suffix": {"type": "array"},
                                    "base_dependency_callee": {"type": "array"},
                                    "base_dependency_caller": {"type": "array"},
                                    "head_dependency_callee": {"type": "array"},
                                    "head_dependency_caller": {"type": "array"},
                                    "other_clones": {"type": "array"},
                                },
                                "required": ["type", "before", "after", "parent_version_range", "child_version_range", "control_flow", "structural_path", "idx", "hunk_diff", "file_path", "identifiers_before", "identifiers_after", "prefix", "suffix", "base_dependency_callee", "base_dependency_caller", "head_dependency_callee", "head_dependency_caller", "other_clones"],
                                "additionalProperties": False
                            }
                        ]
                    }
                }
            },
            "partial_orders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "edit_hunk_pair": {"type": "array"},
                        "edit_order": {"type": "string"},
                        "reason": {"type": "string"}
                    },
                    "required": ["edit_hunk_pair", "edit_order", "reason"]
                }
            }
        },
        "required": ["language", "commit_url", "commit_message", "commit_snapshots", "partial_orders"]
    }

    try:
        validate(instance=graph, schema=schema)
        return True
    except Exception as e:
        print(e)
        return False
    
if __name__ == "__main__":
    commit_url = "https://github.com/localstack/localstack/commit/d47f509bf2495f17f5716e1d7b8e3d80164adc"
    commit_message, commit_snapshots = extract_hunks(commit_url)
    commit_snapshots = get_hunk_diff(commit_snapshots)
    edits = get_edits(commit_snapshots)

    for file_path, snapshot in commit_snapshots.items():
        for window in snapshot:
            if isinstance(window, dict) and window["idx"] == 9:
                window["file_path"] = file_path
                print(formalize_single_input(window))
