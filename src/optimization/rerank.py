import re
import json
import fuzzy_json
import concurrent.futures

from .utils import *
from tqdm import tqdm

def rerank(pred_snapshots, prior_edits):
    """
    Re-rank the predicted snapshots.
    """
    pred_snapshots = add_info_to_snapshots(pred_snapshots)
    edit0_strs = [(edit["idx"], formalize_single_input(edit)) for edit in prior_edits[-1:]]

    rerank_tasks = []
    for file_path, snapshot in pred_snapshots.items():
        for window in snapshot:
            if isinstance(window, dict):
                edit1_str = formalize_single_input(window)
                for edit_idx, edit0_str in edit0_strs:
                    rerank_tasks.append({
                        "text": f"<edit 0>\n{edit0_str}</edit 0>\n<edit 1>\n{edit1_str}</edit 1>",
                        "pred_edit_idx": window["idx"],
                        "prior_edit_idx": edit_idx,
                    })

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
            executor.submit(predict_rerank, task, prompt_template, core_instruction) 
            for task in rerank_tasks
        ]

        # Use tqdm wrap as_completed iterator to show progress
        for future in tqdm(
            concurrent.futures.as_completed(futures),
            total=len(futures),
            desc="Rerank predicted edits"
        ):
            try:
                result = future.result()
                results.append(result)
            except Exception:
                raise ValueError("Error in evaluating a prompt:", future.exception())
    
    
    total_time = max([result.get("time", 0) for result in results]) if results else 0  # as they are parallel
    total_token = sum([result.get("token", 0) for result in results]) if results else 0
    total_price = sum([result.get("price", 0) for result in results]) if results else 0
    print(f"[RERANK] Total time cost: {total_time:.2f}s, total token usage: {total_token}, total price: ${total_price:.6f}")
    valid_results = []
    for result in results:
        if result["pred"] in ["no relation", "1 before 0"]:
            # this predicted edit is not flow keeping
            continue
        else:
            valid_results.append(result)

    valid_results = deduplicate_by_edit_idx(valid_results)
    valid_results = sorted(valid_results, key=lambda x: x["label_prob"], reverse=True)
    pred_snapshots = update_pred_snapshots(pred_snapshots, valid_results)
    rerank_cost = {
        "time": total_time,
        "token": total_token,
        "price": total_price
    }
    return pred_snapshots, rerank_cost

def deduplicate_by_edit_idx(data):
    """
    Deduplicate a list of dicts by pred_edit_idx, 
    keeping only the one with the highest label_prob.
    
    Args:
        data (list[dict]): Each dict must contain keys:
            - "pred_edit_idx" (hashable, used as key)
            - "label_prob" (numeric, used for comparison)
    
    Returns:
        list[dict]: Deduplicated list.
    """
    unique = {}
    for item in data:
        idx = item["pred_edit_idx"]
        if idx not in unique or item["label_prob"] > unique[idx]["label_prob"]:
            unique[idx] = item
    return list(unique.values())
            
def predict_rerank(task, prompt_template, core_instruction):
    text = task["text"]
    pred_edit_idx = task["pred_edit_idx"]
    prior_edit_idx = task["prior_edit_idx"]

    prompt = prompt_template.replace("{{text}}", text)
    prompt = prompt.replace("{{core_instruction}}", core_instruction)

    max_retry = 5
    for retry_cnt in range(max_retry + 1):
        try:
            infos = claude_token_probs(prompt)
            generated_text = infos["message"]
            time_cost = infos.get("time", 0) # must not use "time" as variable name, which collides with time module
            token = infos.get("token", 0)
            price = infos.get("price", 0)
            
            response = None
            parse_success = False
            
            # Try fuzzy_json first
            if not parse_success:
                try:
                    response = fuzzy_json.loads(generated_text)
                    parse_success = True
                except Exception:
                    pass
            
            # Try regex extraction if fuzzy_json failed
            if not parse_success:
                json_match = re.search(r'\{.*\}', generated_text, re.DOTALL)
                if json_match:
                    try:
                        response = json.loads(json_match.group())
                        parse_success = True
                        print("Saved via regex")
                    except Exception:
                        pass
            
            # Check if parsing succeeded
            if not parse_success:
                raise ValueError("JSON parsing failed")
            
            # Validate required fields
            if not all(field in response for field in ["order", "pred_reason", "confidence"]):
                raise ValueError("Missing required fields")
            
            # Extract results and exit loop
            pred = response['order']
            pred_reason = response['pred_reason']
            label_prob = response["confidence"]
            break
            
        except Exception as e:
            print(f"[ERROR:OPTIMIZE] Encountered error: {e}")
            print(f"[ERROR:OPTIMIZE] Mark {pred_edit_idx} as no relation to piror edit {prior_edit_idx}.")
            if retry_cnt == max_retry:
                return {
                    "pred": "no relation",
                    "pred_reason": "",
                    "label_prob": 0,
                    "pred_edit_idx": pred_edit_idx,
                    "time": time_cost,
                    "token": token,
                    "price": price
                }
            
            time.sleep(1)

    return {
        "pred": pred,
        "pred_reason": pred_reason,
        "label_prob": label_prob,
        "pred_edit_idx": pred_edit_idx,
        "time": time_cost,
        "token": token,
        "price": price
    }

def update_pred_snapshots(pred_snapshots, valid_results):
    new_pred_snapshots = {}
    for file_path, snapshot in pred_snapshots.items():
        new_pred_snapshots[file_path] = []
        for window in snapshot:
            if isinstance(window, list):
                if len(new_pred_snapshots[file_path]) > 0 and isinstance(new_pred_snapshots[file_path][-1], list):
                    new_pred_snapshots[file_path][-1].extend(window.copy())
                else:
                    new_pred_snapshots[file_path].append(window.copy())
            else:
                edit_idx = window["idx"]
                is_valid = False
                for rank, result in enumerate(valid_results):
                    if result["pred_edit_idx"] == edit_idx:
                        is_valid = True
                        confidence = result["label_prob"]
                        suggestionRank = rank
                        break
                if is_valid:
                    window["confidence"] = confidence
                    window["suggestionRank"] = suggestionRank
                    new_pred_snapshots[file_path].append(window)
                else:
                    if len(new_pred_snapshots[file_path]) == 0:
                        new_pred_snapshots[file_path].append(window["before"].copy())
                    elif isinstance(new_pred_snapshots[file_path][-1], list):
                        new_pred_snapshots[file_path][-1].extend(window["before"].copy())
                    elif isinstance(new_pred_snapshots[file_path][-1], dict):
                        new_pred_snapshots[file_path].append(window["before"].copy())

    no_edit_files = []
    for file_path, snapshot in new_pred_snapshots.items():
        if len(snapshot) == 1 and isinstance(snapshot[0], list):
            # remove this key-value pair from new_pred_snapshots
            no_edit_files.append(file_path)
    for file_path in no_edit_files:
        del new_pred_snapshots[file_path]
    return new_pred_snapshots
