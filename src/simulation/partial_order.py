import os
import json
import time
import fuzzy_json
import networkx as nx
import concurrent.futures

from .utils import *
from tqdm import tqdm
from dotenv import load_dotenv
from itertools import combinations

current_path = os.path.abspath(os.path.dirname(__file__))
root_path = os.path.join(current_path, "../..")
load_dotenv(dotenv_path=os.path.join(root_path, ".config"))
ANNOTATED_PARTIAL_ORDER_DIR = os.getenv("ANNOTATED_PARTIAL_ORDER_DIR")

def restore_edit_order(commit_snapshot, commit_url, mock_order=True):
    """
    Restore the partial order of edits from the commit snapshot.

    Args:
        commit_snapshot: dict, key is the file path (rel to the repo root), value is a file snapshot, of type list[list[str] | dict], where list[str] is a list of lines of code without any changes, and dict is an edit, with keys: "before", "after" and more
    Returns:
        partial_order_graph: dict, key is node and edge. 
    """
    # If this commit url from human annotated dataset, load the annotated partial order directly
    commit_sha = commit_url.split("/")[-1]
    commit_proj = commit_url.split("/")[-3]
    annotated_file = os.path.join(ANNOTATED_PARTIAL_ORDER_DIR, f"{commit_proj}-{commit_sha}.json")
    if ANNOTATED_PARTIAL_ORDER_DIR and os.path.exists(annotated_file):
        with open(annotated_file, "r") as f:
            data = json.load(f)
        print(f"[MESSAGE:SIM] Load human annotated partial order from {annotated_file}")
        
        G = nx.DiGraph()
        partial_orders = []
        for pair in data["partial_orders"]:
            if pair["edit_order"] == "bi-directional":
                G.add_edge(pair["edit_hunk_pair"][0], pair["edit_hunk_pair"][1])
                G.add_edge(pair["edit_hunk_pair"][1], pair["edit_hunk_pair"][0])
                partial_orders.append({
                    "src": pair["edit_hunk_pair"][0],
                    "tgt": pair["edit_hunk_pair"][1],
                    "reason": ""
                })
                partial_orders.append({
                    "src": pair["edit_hunk_pair"][1],
                    "tgt": pair["edit_hunk_pair"][0],
                    "reason": ""
                })
            elif pair["edit_order"] == "0 before 1":
                G.add_edge(pair["edit_hunk_pair"][0], pair["edit_hunk_pair"][1])
                partial_orders.append({
                    "src": pair["edit_hunk_pair"][0],
                    "tgt": pair["edit_hunk_pair"][1],
                    "reason": ""
                })
            elif pair["edit_order"] == "1 before 0":
                G.add_edge(pair["edit_hunk_pair"][1], pair["edit_hunk_pair"][0])
                partial_orders.append({
                    "src": pair["edit_hunk_pair"][1],
                    "tgt": pair["edit_hunk_pair"][0],
                    "reason": ""
                })
        
        for file_path, snapshot in data["commit_snapshots"].items():
            for window in snapshot:
                if isinstance(window, dict):
                    if not G.has_node(window["idx"]):
                        G.add_node(window["idx"])
          
        degrees = dict(G.in_degree())
        min_deg = min(degrees.values())
        allowed_init_edits = [n for n, d in degrees.items() if d == min_deg]
          
        return partial_orders, allowed_init_edits
    
    print("[WARNING:SIM] At src/simulation/partial_order.py: restore_edit_order(), the implementation is not done yet.")
    commit_sha = commit_url.split('/')[-1]
    project_name = commit_url.split('/')[-3]

    tgt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "predicted_partial_orders")
    os.makedirs(tgt_dir, exist_ok=True)
    tgt_file = os.path.normpath(os.path.join(tgt_dir, f"{project_name}-{commit_sha}.json"))
    if os.path.exists(tgt_file):
        with open(tgt_file, "r") as f:
            data = json.load(f)
        print(f"[MESSAGE:SUT] Load predicted partial order from {tgt_file}")
        return data["partial_orders"], data["allowed_init_edits"]

    edits = []
    for file_path, file_snapshot in commit_snapshot.items():
        for window in file_snapshot:
            if isinstance(window, dict):
                edits.append(window)

    if mock_order:
        allowed_init_edits = [0]
        partial_orders = []
        for i in range(len(edits) - 1):
            current_edit = edits[i]
            next_edit = edits[i + 1]
            partial_orders.append({
                "src": current_edit["idx"],
                "tgt": next_edit["idx"]
            })
        return partial_orders, allowed_init_edits
    
    edit_pairs = list(combinations(edits, 2))
    tasks = []
    for pair in edit_pairs:
        e0, e1 = pair
        e0_str, e1_str = formalize_input(e0, e1)
        task = {
            "text": f"<edit 0>\n{e0_str}</edit 0>\n<edit 1>\n{e1_str}</edit 1>",
            "edit_hunk_pair": [e0["idx"], e1["idx"]]
        }
        tasks.append(task)

    num_threads = max(1, os.cpu_count() - 1) 
    current_file_at_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(current_file_at_dir,"..","prompts","prompt_template.md"), "r") as f:
        prompt_template = f.read()
    with open(os.path.join(current_file_at_dir,"..","prompts","core_instruction.md"), "r") as f:
        core_instruction = f.read()

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        # Create a list of futures for each task
        futures = [
            executor.submit(predict_partial_order, task, prompt_template, core_instruction) 
            for task in tasks
        ]

        # Use tqdm wrap as_completed iterator to show progress
        for future in tqdm(
            concurrent.futures.as_completed(futures),
            total=len(futures),
            desc="Predict commit's editing partial order graph"
        ):
            try:
                result = future.result()
                results.append(result)
            except Exception:
                raise ValueError("Error in evaluating a prompt:", future.exception())

    partial_orders = []
    print("[MESSAGE:SIM] Predicted edit partial orders:")
    for result in results:
        print("\t\t",result["edit_hunk_pair"], ":", result["pred"])
        if result["pred"] == "0 before 1":
            partial_orders.append({
                "src": result["edit_hunk_pair"][0],
                "tgt": result["edit_hunk_pair"][1],
                "reason": result["pred_reason"]
            })
        elif result["pred"] == "1 before 0":
            partial_orders.append({
                "src": result["edit_hunk_pair"][1],
                "tgt": result["edit_hunk_pair"][0],
                "reason": result["pred_reason"]
            })
        elif result["pred"] == "bi-directional":
            partial_orders.append({
                "src": result["edit_hunk_pair"][0],
                "tgt": result["edit_hunk_pair"][1],
                "reason": result["pred_reason"]
            })
            partial_orders.append({
                "src": result["edit_hunk_pair"][1],
                "tgt": result["edit_hunk_pair"][0],
                "reason": result["pred_reason"]
            })
        else: # no relation edge should not be included
            continue
    
    G = nx.DiGraph()
    for edge in partial_orders:
        G.add_edge(edge["src"], edge["tgt"])

    G.add_nodes_from([e["idx"] for e in edits])  # 显式补充所有编辑节点

    degrees = dict(G.in_degree())
    min_deg = min(degrees.values())
    allowed_init_edits = [n for n, d in degrees.items() if d == min_deg]

    # Save the predicted partial order
    with open(tgt_file, "w") as f:
        json.dump(
            {
                "partial_orders": partial_orders, 
                "allowed_init_edits": allowed_init_edits
            }, 
            f, 
            indent=4
        )

    return partial_orders, allowed_init_edits

def predict_partial_order(task, prompt_template, core_instruction):
    """
    Predict the partial order of two edits.

    Args:
        task: dict, key is "text", value is the text of the task, and "edit_hunk_pair" is the pair of edit hunk indices.
        prompt_template: str, the template of the prompt.
    
    Returns:
        result: dict, key is "edit_hunk_pair", value is the partial order of the two edits.
    """
    text = task["text"]
    edit_hunk_pair = task["edit_hunk_pair"]

    prompt = prompt_template.replace("{{text}}", text)
    prompt = prompt.replace("{{core_instruction}}", core_instruction)

    max_retry = 5
    for retry_cnt in range(max_retry + 1):
        try:
            output = chatgpt(prompt)[0]

            parse_success = False
            # Try fuzzy_json first
            if not parse_success:
                try:
                    response = fuzzy_json.loads(output)
                    parse_success = True
                except Exception:
                    pass
            
            # Try regex extraction if fuzzy_json failed
            if not parse_success:
                json_match = re.search(r'\{.*\}', output, re.DOTALL)
                if json_match:
                    try:
                        response = json.loads(json_match.group())
                        parse_success = True
                        print("Saved via regex")
                    except Exception:
                        pass
                
            # Check if parsing succeeded
            if not parse_success:
                raise ValueError("Failed to parse output")
            
            # Validate response structure
            if 'order' not in response or 'pred_reason' not in response:
                raise ValueError("Invalid response structure")
            
            # Extract order and pred_reason
            pred = response['order']
            pred_reason = response['pred_reason']

            break

        except Exception as e:
            print(f"[ERROR:SIM] Encountered error: {e}")
            if retry_cnt == max_retry:
                raise e
            time.sleep(1)
            continue

    return {
        "pred": pred,
        "pred_reason": pred_reason,
        "edit_hunk_pair": edit_hunk_pair
    }