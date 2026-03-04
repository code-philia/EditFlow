import os
import sys
import json
import platform
import subprocess
from .utils import get_parser
import warnings
from dotenv import load_dotenv

CURR_FILE_DIR=os.path.dirname(os.path.abspath(__file__))
ENV_DIR=os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ENV_PATH = os.path.join(ENV_DIR, ".config")
load_dotenv(ENV_PATH)
REPOS_PATH=os.getenv("REPOS_PATH")

warnings.warn(
    "get_all_identifiers()/imported_identifier() only works for Python, and the identifier kind is not accurate for other languages. ",
    category=UserWarning,
    stacklevel=2
)

def parse(code, language):
    parser = get_parser(language)
    tree = parser.parse(bytes(code, "utf8"))
    return tree

def get_all_identifiers(tree):
    """
    Get all named identifiers from the AST tree with their positions and types.
    
    Returns:
        list[dict]: List of identifiers, each containing:
            - identifier: str, the identifier name
            - position: dict, the position in file {start: {line, column}, end: {line, column}}
            - type: str, the node type
            - kind: str, one of ["function", "class", "method", "variable", "parameter", "import", "unknown"]
    """
    identifiers = []
    
    def get_identifier_kind(node):
        def is_import_node(n):
            return n and n.type in ["import_statement", "import_from_statement"]
        
        def check_ancestors_for_import(n):
            current = n
            while current:
                if is_import_node(current):
                    return True
                current = current.parent
            return False
            
        if check_ancestors_for_import(node):
            return "import"
            
        parent = node.parent
        if not parent:
            return "unknown"
            
        # 根据不同语言的语法树结构判断标识符类型
        if parent.type == "function_definition" or parent.type == "function_declaration" or parent.type == "type_declaration":
            return "function"
        elif parent.type == "class_definition" or parent.type == "class_declaration":
            return "class"
        elif parent.type == "method_definition" or parent.type == "method_declaration":
            return "method"
        elif parent.type == "parameter" or "parameter" in parent.type:
            return "parameter"
        elif parent.type in ["variable_declarator", "assignment", "variable_declaration"]:
            return "variable"
        
        # 向上查找更多的父节点来确定类型
        grandparent = parent.parent
        if grandparent:
            if grandparent.type == "method_definition" or grandparent.type == "method_declaration":
                return "method"
            elif "class" in grandparent.type and parent.type == "identifier":
                return "class"
                
        return "unknown"
    
    def imported_identifier(node):
        """
        Return True if the identifier is:
        - Not in an import statement, or
        - In the `import` part of `import_from_statement` (i.e., actually imported symbol), or
        - In an `import_statement`
        """
        # WARNING: This implementation only works for python
        def is_descendant(child, ancestor):
            while child is not None:
                if child == ancestor:
                    return True
                child = child.parent
            return False

        # Walk up the tree to find enclosing import-related node
        parent = node
        while parent is not None and parent.type not in ("import_statement", "import_from_statement"):
            parent = parent.parent

        if parent is None:
            return True  # not inside import => keep

        if parent.type == "import_statement":
            return True  # e.g. import os.path

        if parent.type == "import_from_statement":
            found_import = False
            for child in parent.children:
                if child.type == "import":
                    found_import = True
                    continue
                if found_import and is_descendant(node, child):
                    return True  # Node is under part after 'import'
            return False  # Node is in 'from' part

        return True  # fallback

    def visit_node(node):
        if node.is_named:  # 只处理命名节点
            if node.type == "identifier" or "identifier" in node.type:
                # if node text is a keyword, skip it
                if node.text.decode("utf-8") in ["if", "else", "while", "for", "return", "break", "continue", "pass", "import", "from", "class", "def", "async", "await", "try", "except", "finally", "with", "as", "assert", "del", "global", "nonlocal", "yield", "raise", "import", "from", "as", "assert", "del", "global", "nonlocal", "yield", "raise", "assert", "del", "global", "nonlocal", "yield", "raise", "int", "float", "str", "bool", "None", "True", "False"]:
                    return
                kind = get_identifier_kind(node)
                if kind == "import":
                    if not imported_identifier(node):
                        return
                identifiers.append({
                    "identifier": node.text.decode("utf-8"),
                    "position": {
                        "start": {"line": node.start_point[0], "column": node.start_point[1]},
                        "end": {"line": node.end_point[0], "column": node.end_point[1]}
                    },
                    "type": node.type,
                    "kind": kind
                })
        
        # 递归访问所有子节点
        for child in node.children:
            visit_node(child)
    
    visit_node(tree.root_node)
    return identifiers

def filter_identifiers(identifiers, hunk_ranges, file_path):
    filtered_identifiers = []
    for identifier in identifiers:
        for hunk_range in hunk_ranges:
            if identifier["position"]["start"]["line"] >= hunk_range["start"] and identifier["position"]["end"]["line"] < hunk_range["end"]:
                identifier["abs_file_path"] = file_path
                identifier["hunk_idx"] = hunk_range["idx"]
                filtered_identifiers.append(identifier)
    return filtered_identifiers

def apply_LSP(workspace_dir, datasample, language, version):
    import sys
    curr_file_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.join(curr_file_dir, "../.."))
    if language == "java":
        from lib.LSPs.java_lsp import JavaLanguageServer
        LSP = JavaLanguageServer(log=False)
    elif language == "python":
        from lib.LSPs.py_lsp import PyLanguageServer
        LSP = PyLanguageServer(log=False)
    elif language == "go":
        from lib.LSPs.go_lsp import GoLanguageServer
        LSP = GoLanguageServer(log=False)
    elif language == "javascript":
        from lib.LSPs.jsts_lsp import TsLanguageServer
        LSP = TsLanguageServer("javascript", log=False)
    elif language == "typescript":
        from lib.LSPs.jsts_lsp import TsLanguageServer
        LSP = TsLanguageServer("typescript", log=False)
    else:
        raise ValueError(f"Unsupported language: {language}")
    
    LSP.initialize(workspace_dir)
    
    # STEP 1. Use Tree-sitter to parse all identifiers in the hunks
    all_identifiers = []
    abs_file_paths = []
    for file_path, snapshot in datasample["commit_snapshots"].items():
        absolute_file_path = os.path.join(workspace_dir, file_path)
        abs_file_paths.append(absolute_file_path)
        LSP.did_open(absolute_file_path)
        hunk_ranges = []
        for hunk in snapshot:
            if isinstance(hunk, list):
                continue
            elif version == "base":
                hunk_ranges.append({
                    "idx": hunk["idx"],
                    "start": hunk["parent_version_range"]["start"],
                    "end": hunk["parent_version_range"]["end"]
                })
            elif version == "head":
                hunk_ranges.append({
                    "idx": hunk["idx"],
                    "start": hunk["child_version_range"]["start"],
                    "end": hunk["child_version_range"]["end"]
                })
        # parse the file, keep the identifiers in the range
        with open(absolute_file_path, "r") as f:
            code = f.read()
        tree = parse(code, language)
        identifiers = get_all_identifiers(tree)
        filered_identifiers = filter_identifiers(identifiers, hunk_ranges, absolute_file_path)
        all_identifiers.extend(filered_identifiers)

    # print(f"All identifiers: {len(all_identifiers)}")
    # STEP 2. Use LSP to get all identifier dependencies
    dep_edges = []
    skippable_identifiers = []
    for identifier in all_identifiers:
        definition = None
        reference = None
        if identifier['identifier'] in skippable_identifiers:
            continue
        if identifier.get("dependency_checked", False) is True:
            # If the dependency has checked, skip it
            # print(f"Identifier: {identifier['identifier']} has been checked")
            continue
        # print(f"Identifier: {identifier['identifier']}, at position {identifier['position']['start']['line']}:{identifier['position']['start']['column']}, at file {identifier['abs_file_path']}, of type: {identifier['kind']}")
        
        # First find the definition of the identifier
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        location = {"line": identifier["position"]["start"]["line"], "character": (identifier["position"]["start"]["column"] + identifier["position"]["end"]["column"]) // 2}
        try:
            def_response = LSP.definitions(identifier["abs_file_path"], location)
        except:
            def_response = []
        # print(f"Definition Response: \n{def_response}", location)
        
        if def_response != [] and def_response[0]["result"] is not None:
            # Here we dont reverse the condition to do continue, because we still have to decide if this identifier is an import statement
            def_results = def_response[0]["result"]
            
            # check if there are multiple definitions inside the project (exclude those outside the project)
            def_results_inside_project = []
            for def_result in def_results:
                if def_result["uri"][7:] in abs_file_paths:
                    def_results_inside_project.append(def_result)
            if len(def_results_inside_project) > 1:
                # multiple definitions can not simply determine the relation between definition and reference
                # print(f"Multiple definitions found for {identifier['identifier']} in {identifier['abs_file_path']}")
                continue
            for def_result in def_results_inside_project:
                if def_result["uri"][7:] not in abs_file_paths:
                    continue
                else:
                    # match with filtered identifiers
                    for filtered_identifier in all_identifiers:
                        if def_result["uri"][7:] == filtered_identifier["abs_file_path"] and \
                            identifier["identifier"] == filtered_identifier["identifier"] and \
                            def_result["range"]["start"]["line"] == filtered_identifier["position"]["start"]["line"]:
                            # sometimes, lsp can locate the correct line, but may not very accurate about the column, so here we only check the line
                            filtered_identifier["dependency_checked"] = True
                            definition = filtered_identifier.copy()
                            # print(f"Definition: {definition}")
                            break
        
        if definition is None and identifier["kind"] != "import": 
            # if this identifier is not defined in the codebase, skip
            # Unless it is an import statement
            # print(f"Identifier: {identifier['identifier']} is not defined in the codebase")
            continue 
        elif definition is None and identifier["kind"] == "import":
            # if this identifier is an import statement, but not defined in the codebase, still build the dependency between the import and the reference
            # print(f"Identifier: {identifier['identifier']} is an import statement, but not defined in the codebase")
            pass

        # Then find the reference of the identifier
        # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
        try:
            ref_response = LSP.references(identifier["abs_file_path"], {"line": identifier["position"]["start"]["line"], "character": (identifier["position"]["start"]["column"] + identifier["position"]["end"]["column"]) // 2})
        except:
            ref_response = []
        
        if ref_response == [] or ref_response[0]["result"] is None:
            # print(f"Reference Response is empty")
            continue
        results = ref_response[0]["result"]
        
        found_references = []
        for ref_result in results:
            if ref_result["uri"][7:] not in abs_file_paths:
                continue
            else:
                # match with filtered identifiers
                for filtered_identifier in all_identifiers:
                    if ref_result["uri"][7:] == filtered_identifier["abs_file_path"] and \
                        identifier["identifier"] == filtered_identifier["identifier"] and \
                        ref_result["range"]["start"]["line"] == filtered_identifier["position"]["start"]["line"] and \
                        ref_result["range"]["start"]["character"] == filtered_identifier["position"]["start"]["column"] and \
                        ref_result["range"]["end"]["line"] == filtered_identifier["position"]["end"]["line"] and \
                        ref_result["range"]["end"]["character"] == filtered_identifier["position"]["end"]["column"]:
                        filtered_identifier["dependency_checked"] = True
                        found_references.append(filtered_identifier.copy())
                        # print(f"Referece: {filtered_identifier}")
                        break
            
        import_identifiers = []
        for ref in found_references:
            if ref["kind"] == "import":
                import_identifiers.append(ref)
        
        if len(import_identifiers) > 0 and definition is not None:
            # If we have definition, import and referemce, any 2 of them can form a dependency
            for reference in found_references:
                if reference["kind"] == "import":
                    continue
                else:
                    dep_edges.append({
                        "callee_hunk_idx": definition["hunk_idx"], 
                        "caller_hunk_idx": reference["hunk_idx"],
                        "callee_detail": definition,
                        "caller_detail": reference,
                        "version": version,
                        "is_import_use": False
                })
                # print(f"Hunk {definition['hunk_idx']} -- is depended by ---> Hunk {reference['hunk_idx']}, since {definition['identifier']} is defined at line {definition['position']['start']['line']} is imported in {reference['identifier']} at line {reference['position']['start']['line']}")
            # then add dep between import and reference
            for import_identifier in import_identifiers:
                for reference in found_references:
                    if import_identifier["abs_file_path"] != reference["abs_file_path"]:
                        continue
                    if import_identifier == reference:
                        continue
                    else:
                        dep_edges.append({
                            "callee_hunk_idx": import_identifier["hunk_idx"], 
                            "caller_hunk_idx": reference["hunk_idx"],
                            "callee_detail": import_identifier,
                            "caller_detail": reference,
                            "version": version,
                            "is_import_use": True
                        })
                        # print(f"Hunk {import_identifier['hunk_idx']} -- is depended by ---> Hunk {reference['hunk_idx']}, since {import_identifier['identifier']} is imported in {reference['identifier']} at line {reference['position']['start']['line']}")
            # last add dep between definition and import
            for import_identifier in import_identifiers:
                dep_edges.append({
                    "callee_hunk_idx": definition["hunk_idx"], 
                    "caller_hunk_idx": import_identifier["hunk_idx"],
                    "callee_detail": definition,
                    "caller_detail": import_identifier,
                    "version": version,
                    "is_import_use": False
                })
        elif len(import_identifiers) == 0 and definition is not None:
            # only add dep between definition and reference
            for reference in found_references: 
                if definition == reference:
                    # In some lsp, they cannot return only reference without definition
                    continue
                # Add the dependency edge
                dep_edges.append({
                    "callee_hunk_idx": definition["hunk_idx"], 
                    "caller_hunk_idx": reference["hunk_idx"],
                    "callee_detail": definition,
                    "caller_detail": reference,
                    "version": version,
                    "is_import_use": False
                })
                # print(f"Hunk {definition['hunk_idx']} -- is depended by ---> Hunk {reference['hunk_idx']}, since {definition['identifier']} is defined at line {definition['position']['start']['line']} is used in {reference['identifier']} at line {reference['position']['start']['line']}")
        elif len(import_identifiers) > 0 and definition is None:
            # only add dep between import and reference
            for import_identifier in import_identifiers:
                for reference in found_references:
                    if import_identifier["abs_file_path"] != reference["abs_file_path"]:
                        continue
                    if import_identifier == reference:
                        continue
                    else:
                        dep_edges.append({
                            "callee_hunk_idx": import_identifier["hunk_idx"], 
                            "caller_hunk_idx": reference["hunk_idx"],
                            "callee_detail": import_identifier,
                            "caller_detail": reference,
                            "version": version,
                            "is_import_use": True
                        })
                        # print(f"Hunk {import_identifier['hunk_idx']} -- is depended by ---> Hunk {reference['hunk_idx']}, since {import_identifier['identifier']} is imported in {reference['identifier']} at line {reference['position']['start']['line']}")
        else:
            pass
    
    filtered_dep_edges = []
    for dep_edge in dep_edges:
        if dep_edge["callee_hunk_idx"] == dep_edge["caller_hunk_idx"]:
            continue
        else:
            filtered_dep_edges.append(dep_edge)
    try:
        LSP.close()
    except:
        pass
    
    return filtered_dep_edges
            
def analyze_dependency(datasample, to_remove_consistent_edges=False):
    """
    Analyze the Import-use, dependency and compiler error relationship between 2 edit hunks
    
    Args:
        datasample: dict {
            "language": str, language of the codebase
            "commit_url": str, commit url
            "commit_message": str, commit message
            "commit_snapshots": dict, commit snapshots
            "partial_orders": list[dict], partial orders
        }
        to_remove_consistent_edges: bool, whether to remove the consistent dependency edges that exist in both base and head version
    """
    language = datasample["language"]
    commit_sha = datasample["commit_url"].split("/")[-1]
    project_name = datasample["commit_url"].split("/")[-3]
    
    # STEP 1. Analyze Import-use case and dependency case
    # STEP 1.1. Extract the dependency graph of the codebase at commit base version
    # First clean the untracked files
    workspace_dir = os.path.join(REPOS_PATH, project_name)

    clean_command = ["git", "-C", workspace_dir, "clean", "-fd"]
    subprocess.run(clean_command, shell=False, stdout=subprocess.DEVNULL)

    # Then force switch commit
    command = ["git", "-C", workspace_dir, "checkout", "-f", f"{commit_sha}^"]
    subprocess.run(command, shell=False, stdout=subprocess.DEVNULL)
    
    base_hunk_dependency_edges = apply_LSP(workspace_dir, datasample, language, version="base")
    print(f"Base hunk dependency edges: {len(base_hunk_dependency_edges)}")
    for edge in base_hunk_dependency_edges:
        print(f">>>>>> Dependency: {edge['callee_hunk_idx']} --- depeneded by ---> {edge['caller_hunk_idx']}, is import use: {edge['is_import_use']}, reason: {edge['callee_detail']['identifier']}")
    
    # STEP 1.2. Extract the dependency graph of the codebase at commit head version
    # First clean the untracked files
    clean_command = ["git", "-C", workspace_dir, "clean", "-fd"]
    subprocess.run(clean_command, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Then force switch commit
    command = ["git", "-C", workspace_dir, "checkout", "-f", f"{commit_sha}"]
    subprocess.run(command, shell=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    head_hunk_dependency_edges = apply_LSP(workspace_dir, datasample, language, version="head")
    print(f"Head hunk dependency edges: {len(head_hunk_dependency_edges)}")
    for edge in head_hunk_dependency_edges:
        print(f">>>>>> Dependency: {edge['callee_hunk_idx']} --- depeneded by ---> {edge['caller_hunk_idx']}, is import use: {edge['is_import_use']}, reason: {edge['callee_detail']['identifier']}")
           
    directed_edges = []
    if to_remove_consistent_edges:
        edges = {
            "base_hunk_dependency_edges": base_hunk_dependency_edges, "head_hunk_dependency_edges": head_hunk_dependency_edges
        }
        edges = remove_consistent_edges(edges)
    else:
        edges = base_hunk_dependency_edges + head_hunk_dependency_edges
    
    for edge in edges:
        if edge["is_import_use"] is True:
            # For import-use, use first, then import. 
            # Hence, src is the caller, dest is the callee
            new_edge = {
                "source": edge["caller_hunk_idx"],
                "target": edge["callee_hunk_idx"],
                "caller_hunk_idx": edge["caller_hunk_idx"],
                "callee_hunk_idx": edge["callee_hunk_idx"],
                "at_version": edge["version"],
                "identifier": edge["callee_detail"]["identifier"],
                "callee_detail": edge["callee_detail"],
                "caller_detail": edge["caller_detail"],
                "is_import_use": True
            }
            if new_edge not in directed_edges:
                directed_edges.append(new_edge)
        else:
            # For dependency, callee is the source, caller is the destination
            new_edge = {
                "source": edge["callee_hunk_idx"],
                "target": edge["caller_hunk_idx"],
                "caller_hunk_idx": edge["caller_hunk_idx"],
                "callee_hunk_idx": edge["callee_hunk_idx"],
                "at_version": edge["version"],
                "identifier": edge["callee_detail"]["identifier"],
                "callee_detail": edge["callee_detail"],
                "caller_detail": edge["caller_detail"],
                "is_import_use": False
            }
            if new_edge not in directed_edges:
                directed_edges.append(new_edge)
    
    return directed_edges
    
def remove_consistent_edges(edges):
    """
    If there exist a dependency exist between both base and head version, indicating that the dependency is consistent between the two versions, remove it
    
    Args:
        edges: dict, of 2 keys: "base_hunk_dependency_edges" and "head_hunk_dependency_edges"
    """
    base_edges = edges["base_hunk_dependency_edges"]
    head_edges = edges["head_hunk_dependency_edges"]
    
    edges_to_remove = []
    
    for base_edge in base_edges:
        base_callee_hunk_idx = base_edge["callee_hunk_idx"]
        base_caller_hunk_idx = base_edge["caller_hunk_idx"]
        base_identifier = base_edge["callee_detail"]["identifier"]
        for head_edge in head_edges:
            head_callee_hunk_idx = head_edge["callee_hunk_idx"]
            head_caller_hunk_idx = head_edge["caller_hunk_idx"]
            head_identifier = head_edge["callee_detail"]["identifier"]
            if base_callee_hunk_idx == head_callee_hunk_idx and base_caller_hunk_idx == head_caller_hunk_idx and base_identifier == head_identifier:
                edges_to_remove.append(base_edge)
                edges_to_remove.append(head_edge)
    
    total_edges = base_edges + head_edges
    for edge in edges_to_remove:
        total_edges.remove(edge)
    
    return total_edges

def add_dep_to_snapshot(data, dependency_edges):
    for _, snapshot in data["commit_snapshots"].items():
        for window in snapshot:
            if isinstance(window, list):
                continue
            if "base_dependency" not in window:
                window["base_dependency_callee"] = []
                window["base_dependency_caller"] = []
            if "head_dependency" not in window:
                window["head_dependency_callee"] = []
                window["head_dependency_caller"] = []

    for edge in dependency_edges:
        for _, snapshot in data["commit_snapshots"].items():
            for window in snapshot:
                if isinstance(window, list):
                    continue
                if window["idx"] == edge["caller_hunk_idx"]:
                    if edge["at_version"] == "base" and edge["callee_hunk_idx"] not in window["base_dependency_callee"]:
                        window["base_dependency_callee"].append({
                            "to_hunk_idx": edge["callee_hunk_idx"],
                            "detail": edge["caller_detail"]
                        })
                    elif edge["at_version"] == "head" and edge["callee_hunk_idx"] not in window["head_dependency_callee"]:
                        window["head_dependency_callee"].append({
                            "to_hunk_idx": edge["callee_hunk_idx"],
                            "detail": edge["caller_detail"]
                        })
                
                if window["idx"] == edge["callee_hunk_idx"]:
                    if edge["at_version"] == "base" and edge["caller_hunk_idx"] not in window["base_dependency_caller"]:
                        window["base_dependency_caller"].append({
                            "to_hunk_idx": edge["caller_hunk_idx"],
                            "detail": edge["callee_detail"]
                        })
                    elif edge["at_version"] == "head" and edge["caller_hunk_idx"] not in window["head_dependency_caller"]:
                        window["head_dependency_caller"].append({
                            "to_hunk_idx": edge["caller_hunk_idx"],
                            "detail": edge["callee_detail"]
                        })
                
