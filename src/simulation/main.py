import os
import copy
import json
import random

from .utils import *
from .commit import Commit
from dotenv import load_dotenv
from optimization.rerank import rerank

current_path = os.path.abspath(os.path.dirname(__file__))
root_path = os.path.abspath(os.path.join(current_path, "../../"))
load_dotenv(dotenv_path=os.path.join(root_path, ".config"))
REPOS_DIR = os.getenv("REPOS_DIR") # this directory should be the absolute path to the repository directory inside backend host
OUTPUT_DIR = os.getenv("OUTPUT_DIR")
os.makedirs(REPOS_DIR, exist_ok=True)
COMMIT = None

def main(json_input: dict):
    global COMMIT
    
    commit_url = json_input["commit_url"]
    system_under_test = json_input["system_under_test"]
    status = json_input["status"]
    suggestion_type = json_input["suggestion_type"]
    assert suggestion_type in ["Original suggestion", "Flow-aligned suggestion"]

    if system_under_test == "CoEdPilot":
        import systemUnderTest.CoEdPilot.main as SUT
    elif system_under_test == "Cursor":
        import systemUnderTest.Cursor.main as SUT
    elif system_under_test == "Cursor_CLI":
        import systemUnderTest.Cursor_CLI.main as SUT
    elif system_under_test == "TRAE":
        import systemUnderTest.TRAE.main as SUT
    elif system_under_test == "Claude":
        import systemUnderTest.Claude.main as SUT

    if status == "init":
        # Parse edit hunks and edit orders from given commit URL
        COMMIT = Commit(commit_url, REPOS_DIR, system_under_test)

        # If this commit under this system under test has been simulated before, return the previous results
        if len(COMMIT.SUT_prediction_records) == len(COMMIT.get_edits()):
            print("[MESSAGE:SIM] This commit has been simulated before. Returning the previous results.")
            response_message = COMMIT.SUT_prediction_records[len(COMMIT.replay_progress)]
            COMMIT.replay_progress.append(COMMIT.simulation_order[len(COMMIT.replay_progress)])
            return response_message
        
        # Select init edit and update edits status
        init_edit_idx = random.choice(COMMIT.allowed_next_edit_idxs)
        COMMIT.update_edit_status(init_edit_idx, "simulated", True)
        COMMIT.update_allowed_as_next()

        # Setup the system under test
        print(f"[MESSAGE:SIM] Setting up {system_under_test} for commit {commit_url}...")
        
        json_input = {
            "id": COMMIT.commit_sha,
            "project_name": COMMIT.project_name,
            "status": "init",
            "repo_dir": COMMIT.repo_dir,
            "prior_edits": COMMIT.get_prior_edits(), # Prior edit is the init edit
            "edit_description": COMMIT.commit_message
        }
        SUT.main(json_input)

        print(f"[MESSAGE:SIM] Successfully set up {system_under_test} as System Under Test.")

        # Prepare the initial pred snapshot, where only contain the init edit
        pred_snapshots = copy.deepcopy(COMMIT.get_next_edit_snapshots(init_edit_idx))
        
        # Update the project status with the new edit index
        sync_project(COMMIT.get_current_version(), COMMIT.repo_dir)
        evaluation_entropy = {
            "entropy": {
                "coedit": round(random.uniform(0, 16), 2),
                "solo": round(random.uniform(0, 16), 2)
            }
        }
        response_message =  {
            "pred_snapshots": pred_snapshots,
            "gdth_snapshots": COMMIT.commit_snapshots,
            "evaluations": {
                    "flow_pattern": {
                        "flow_keeping": [init_edit_idx],
                        "flow_jumping": [],
                        "flow_breaking": [],
                        "flow_reverting": []
                    },
                    "matched_locations": [],
                },
            "status": "init",
            "next_edit_snapshots": pred_snapshots,
            "partial_order_graph": COMMIT.get_partial_order_graph(),
            "evaluation_entropy": evaluation_entropy,
        }
        COMMIT.SUT_prediction_records.append(response_message)
        return response_message

    elif status == "suggestion":
        # Environment check
        if COMMIT is None:
            raise ValueError("COMMIT is not initialized. Please run the init step first.")
        edits = COMMIT.get_edits()
        unsimulated_edits = [edit for edit in edits if edit["simulated"] == False]
        # Check 1: commit URL matches
        assert COMMIT.commit_url == json_input["commit_url"], "[ERROR:SIM] At src/simulation/main.py: main(), Commit URL mismatch. Please ensure the same commit is used for both init and suggestion steps."

        # If this commit under this system under test has been simulated before, return the previous results
        if len(COMMIT.SUT_prediction_records) == len(COMMIT.get_edits()):
            print("[MESSAGE:SIM] This commit has been simulated before. Returning the previous results.")
            response_message = COMMIT.SUT_prediction_records[len(COMMIT.replay_progress)]
            COMMIT.replay_progress.append(COMMIT.simulation_order[len(COMMIT.replay_progress)])
            return response_message
        
        # Check 2: exist edits to simulate
        assert unsimulated_edits != [], "[ERROR:SIM] At src/simulation/main.py: main(), No unsimulated edits found. Please check the commit snapshot."
        
        # Print current simulation status
        COMMIT.simulation_status()

        # Acquire subsequent edit recommendation from system under test
        # NOTE: This snapshots are a comparison between: 
        # NOTE: Current simulation status V.S. suggested edit version
        # NOTE: Not the commit base version V.S. suggested edit version
        json_input = {
            "id": COMMIT.commit_sha,
            "project_name": COMMIT.project_name,
            "status": "suggestion",
            "repo_dir": COMMIT.repo_dir,
            "prior_edits": COMMIT.get_prior_edits(),
            "edit_description": COMMIT.commit_message,
            "changed_files": COMMIT.commit_snapshots.keys(),
        }
        pred_snapshots, costs = SUT.main(json_input)
        pred_snapshots = indexing_edits_within_snapshots(pred_snapshots)
        if suggestion_type == "flow-keeping":
            pred_snapshots, rerank_cost = rerank(pred_snapshots, [COMMIT.get_edit(COMMIT.simulation_order[-1])])
        
        # Compare predicted snapshots with current ground-truth snapshots
        # NOTE: COMMIT.get_not_simulated_edit_snapshots() returns the gold
        # NOTE: Current simulation status V.S commit head version
        # Deepcopy is necessary as edit status will have update
        current_snapshots = copy.deepcopy(COMMIT.get_not_simulated_edit_snapshots())
        previously_applied_locations = copy.deepcopy(COMMIT.get_previously_applied_locations())
        # with open("./current_snapshots.json", "w") as f:
        #     json.dump(current_snapshots, f, indent=4)
        # with open("./pred_snapshots.json", "w") as f:
        #     json.dump(pred_snapshots, f, indent=4)
        flow_pattern, traditional_metrics, matched_locations, pred_snapshots = evaluate(pred_snapshots, current_snapshots, previously_applied_locations)
        print(f"[MESSAGE:SIM] Flow pattern: {json.dumps(flow_pattern, indent=4)}")
        
        # Update simulation progress for COMMIT
        new_edit_idx = update_simulation_progress(COMMIT, matched_locations)
        next_edit_snapshots = copy.deepcopy(COMMIT.get_next_edit_snapshots(new_edit_idx))

        # Update the project status with the new edit index
        sync_project(COMMIT.get_current_version(), COMMIT.repo_dir)

        # If all edits have been simulated, return the final results
        edits = COMMIT.get_edits()
        unsimulated_edits = [edit for edit in edits if edit["simulated"] == False]
        evaluation_entropy = {
            "entropy": {
                "coedit": round(random.uniform(0, 16), 2),
                "solo": round(random.uniform(0, 16), 2)
            }
        }
        if len(unsimulated_edits) == 0:
            print("[MESSAGE:SIM] All edits have been simulated. Simulation completed.")
            # NOTE: The pred_snapshots are a comparison between:
            # NOTE: The current version V.S. suggested edit version
            # NOTE: The next_edit_snapshots are a comparsion between:
            # NOTE: The current version V.S. the next step version with next edit applied
            response_message =  {
                "pred_snapshots": pred_snapshots,
                "gdth_snapshots": COMMIT.commit_snapshots,
                "curr_gdth_snapshots": current_snapshots,
                "previously_applied_locations": previously_applied_locations,
                "evaluations": {
                    "flow_pattern": flow_pattern,
                    "matched_locations": matched_locations,
                    "precision": traditional_metrics["precision"],
                    "recall": traditional_metrics["recall"],
                    "f1_score": traditional_metrics["f1_score"],
                    "tp": traditional_metrics["tp"],
                    "fp": traditional_metrics["fp"],
                    "fn": traditional_metrics["fn"],
                    "time": costs["time"],
                    "token": costs["token"],
                    "price": costs["price"],
                },
                "status": "done",
                "next_edit_snapshots": next_edit_snapshots,
                "partial_order_graph": COMMIT.get_partial_order_graph(),
                "evaluation_entropy": evaluation_entropy,
            }
            COMMIT.SUT_prediction_records.append(response_message)
            COMMIT.save_simulation_results()
            json_input = {
                "id": COMMIT.commit_sha,
                "project_name": COMMIT.project_name,
                "status": "end",
                "repo_dir": COMMIT.repo_dir,
                "prior_edits": COMMIT.get_prior_edits(),
                "edit_description": COMMIT.commit_message
            }
            SUT.main(json_input)
        else:
            response_message =  {
                "pred_snapshots": pred_snapshots,
                "gdth_snapshots": COMMIT.commit_snapshots,
                "curr_gdth_snapshots": current_snapshots,
                "previously_applied_locations": previously_applied_locations,
                "evaluations": {
                    "flow_pattern": flow_pattern,
                    "matched_locations": matched_locations,
                    "precision": traditional_metrics["precision"],
                    "recall": traditional_metrics["recall"],
                    "f1_score": traditional_metrics["f1_score"],
                    "tp": traditional_metrics["tp"],
                    "fp": traditional_metrics["fp"],
                    "fn": traditional_metrics["fn"],
                    "time": costs["time"],
                    "token": costs["token"],
                    "price": costs["price"],
                },
                "status": "suggestion",
                "next_edit_snapshots": next_edit_snapshots,
                "partial_order_graph": COMMIT.get_partial_order_graph(),
                "evaluation_entropy": evaluation_entropy,
            }
            COMMIT.SUT_prediction_records.append(response_message)
        
        return response_message

def sync_project(current_version, repo_dir):
    for rel_file_path, file_content in current_version.items():
        file_path = os.path.join(repo_dir, rel_file_path)
        with open(file_path, "w") as f:
            f.write("".join(file_content))

def evaluate(pred_snapshots, gdth_snapshots, previously_applied_locations):
    """
    Evaluate the predicted snapshots against the ground truth snapshots.
    
    Args:
        pred_snapshots (dict): The predicted snapshots.
        gdth_snapshots (dict): The ground truth snapshots.
        previously_applied_locations: list[dict], previously applied locations, 
            each dict has keys:
                "idx": int, the index of the edit
                "file_path": str, the file path of the edit
                "atLines": list[int], the line idx for after edit content
    
    Returns:
        flow_pattern: dict, flow pattern and correspoding predicted edit idx list
        
        matched_locations: list[dict], matched locations, each dict has keys:
            "atLines": list[int], the predicted line idx to replace/insert
            "editType": str, the type of the edit, ["replace", "insert"]
            "confidence": float | None, the confidence of the edit, None if not provided by system under test
            "suggestionRank": int | None, the rank of the edit, None if not provided by system under test
            "matchWith": int, the index of the ground truth edit that matches with this suggested location
            "flowKeeping": bool, the mental flow is kept if matched with allowed subsequent edit, otherwise break the flow
        
        pred_snapshots: dict, predicted snapshots, matched edits with additional keys: matchWith, flowKeeping
    """
    pred_replace_locations, pred_insert_locations = snapshot_2_locations(pred_snapshots)
    gdth_replace_locations, gdth_insert_locations = snapshot_2_locations(gdth_snapshots)

    flow_pattern = {
        "flow_keeping": [],
        "flow_jumping": [],
        "flow_breaking": [],
        "flow_reverting": []
    }

    pred_locations = pred_replace_locations + pred_insert_locations
    for loc in pred_locations:
        assert "confidence" in loc and "suggestionRank" in loc, "[ERROR:SIM] At src/simulation/main.py: evaluate(), Predicted locations must contain 'confidence' and 'suggestionRank' fields."
    for loc in gdth_replace_locations + gdth_insert_locations:
        assert "idx" in loc and "allowed_as_next" in loc, "[ERROR:SIM] At src/simulation/main.py: evaluate(), Ground truth locations must contain 'idx' and 'allowed_as_next' fields."
    
    # first classify the flow-keeping, jumping
    matched_locations = []
    for pred_loc in pred_locations:
        pred_at_lines = pred_loc["atLines"]
        if pred_loc["editType"] == "replace":
            for gdth_loc in gdth_replace_locations:
                if gdth_loc["file_path"] != pred_loc["file_path"]:
                    continue
                gdth_at_lines = gdth_loc["atLines"]
                if overlap_percentage(pred_at_lines, gdth_at_lines) > 0.5 and get_bleu(pred_loc["after"], gdth_loc["after"]) > 50:
                    matched_locations.append({
                        "atLines": pred_at_lines,
                        "editType": pred_loc["editType"],
                        "confidence": pred_loc["confidence"],
                        "suggestionRank": pred_loc["suggestionRank"],
                        "predIdx": pred_loc["idx"],
                        "matchWith": gdth_loc["idx"],
                        "flowKeeping": True if gdth_loc["allowed_as_next"] else False,
                    })
                    for file_path, snapshots in pred_snapshots.items():
                        for window in snapshots:
                            if isinstance(window, list):
                                continue
                            if window["idx"] == pred_loc["idx"]:
                                window["matchWith"] = gdth_loc["idx"]
                                window["flowKeeping"] = True if gdth_loc["allowed_as_next"] else False
                                if window["flowKeeping"]:
                                    flow_pattern["flow_keeping"].append(pred_loc["idx"])
                                else:
                                    flow_pattern["flow_jumping"].append(pred_loc["idx"])
                                break
                    break
        else:
            for gdth_loc in gdth_insert_locations:
                if gdth_loc["file_path"] != pred_loc["file_path"]:
                    continue
                gdth_at_lines = gdth_loc["atLines"]
                if pred_at_lines == gdth_at_lines and get_bleu(pred_loc["after"], gdth_loc["after"]) > 50:
                    matched_locations.append({
                        "atLines": pred_at_lines,
                        "editType": pred_loc["editType"],
                        "confidence": pred_loc["confidence"],
                        "suggestionRank": pred_loc["suggestionRank"],
                        "predIdx": pred_loc["idx"],
                        "matchWith": gdth_loc["idx"],
                        "flowKeeping": True if gdth_loc["allowed_as_next"] else False,
                    })
                    for file_path, snapshots in pred_snapshots.items():
                        for window in snapshots:
                            if isinstance(window, list):
                                continue
                            if window["idx"] == pred_loc["idx"]:
                                window["matchWith"] = gdth_loc["idx"]
                                window["flowKeeping"] = True if gdth_loc["allowed_as_next"] else False
                                if window["flowKeeping"]:
                                    flow_pattern["flow_keeping"].append(pred_loc["idx"])
                                else:
                                    flow_pattern["flow_jumping"].append(pred_loc["idx"])
                                break
                    break

    # then classify the flow-reverting and flow-breaking
    for pred_loc in pred_locations:
        # Filter out predicted hunks already classified as flow-keeping and flow-breaking
        if pred_loc["idx"] in flow_pattern["flow_keeping"] + flow_pattern["flow_jumping"]:
            continue
        pred_at_lines = pred_loc["atLines"]
        is_flow_reverting = False
        for prev_apply_loc in previously_applied_locations:
            if prev_apply_loc["file_path"] == pred_loc["file_path"] and overlap_percentage(pred_at_lines, prev_apply_loc["atLines"]) > 0.5:
                flow_pattern["flow_reverting"].append(pred_loc["idx"])
                is_flow_reverting = True
                break
        if not is_flow_reverting:
            flow_pattern["flow_breaking"].append(pred_loc["idx"])

    assert len(flow_pattern["flow_keeping"]) + len(flow_pattern["flow_jumping"]) + len(flow_pattern["flow_reverting"]) + len(flow_pattern["flow_breaking"]) == len(pred_locations)
    assert len(matched_locations) == len(flow_pattern["flow_keeping"]) + len(flow_pattern["flow_jumping"])

    # Evaluate precision, recall
    gold_locations = gdth_replace_locations + gdth_insert_locations
    allowed_locations = [loc for loc in gold_locations if loc["allowed_as_next"]]
    tp = len(flow_pattern["flow_keeping"]) + len(flow_pattern["flow_jumping"])
    fp = len(pred_locations) - tp
    fn = len(gold_locations) - tp
    
    precision = tp / len(pred_locations) if len(pred_locations) > 0 else 0
    recall = tp / len(gold_locations) if len(gold_locations) > 0 else 0
    f1_score = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    traditional_metrics = {
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }
    
    return flow_pattern, traditional_metrics, matched_locations, pred_snapshots

def update_simulation_progress(COMMIT, matched_locations):
    """
    Update the simulation progress of a commit.
    
    Args:
        COMMIT (Commit): The commit to update.
        matched_locations (list[dict]): The evaluation results.
    """
    new_edit_idx = None
    # Find the first flow matching edit, assign as the subsequent edit
    for edit in matched_locations:
        if edit["flowKeeping"]:
            new_edit_idx = edit["matchWith"]
            COMMIT.update_edit_status(edit["matchWith"], "simulated", True)
            print(f"[MESSAGE:SUT] Suggestion matches with Edit {edit['matchWith']}, apply to project")
            break
    
    # Otherwise, randomly select from allowed next edit idxs as the subsequent edit
    if new_edit_idx is None:
        edits = COMMIT.get_edits()
        allowed_next_edit_idxs = [edit["idx"] for edit in edits if edit["allowed_as_next"] == True]
        if len(allowed_next_edit_idxs) > 0:
            new_edit_idx = random.choice(allowed_next_edit_idxs)
        else:
            new_edit_idx = random.choice([edit["idx"] for edit in edits if edit["simulated"] == False])
        COMMIT.update_edit_status(new_edit_idx, "simulated", True)
        print(f"[MESSAGE:SUT] Suggestion does not match with any edit, randomly pick Edit {new_edit_idx} as subsequent edit, apply to project")
    
    COMMIT.update_allowed_as_next()
    return new_edit_idx

def rq3_origin(url, sut):
    init_input = {
        "commit_url": url,
        "system_under_test": sut,
        "status": "init",
        "suggestion_type": "naive"
    }
    response = main(init_input)
    edit_num = 0
    for file_path, snapshot in response["gdth_snapshots"].items():
        for window in snapshot:
            if isinstance(window, dict):
                edit_num += 1

    for i in range(edit_num - 1):
        input = {
            "commit_url": url,
            "system_under_test": sut,
            "status": "suggestion",
            "suggestion_type": "naive"
        }
        main(input)

def rq3_flow_keeper(url, sut):
    # Find the simulation output of commit url
    commit_sha = url.split("/")[-1][:10]
    project_name = url.split("/")[-3]
    if os.path.exists(os.path.join(OUTPUT_DIR, f"{project_name}-{commit_sha}-{sut}-simulation-results-flow-keeper.json")):
        return None
    assert os.path.exists(os.path.join(OUTPUT_DIR, f"{project_name}-{commit_sha}-{sut}-simulation-results.json"))
    with open(os.path.join(OUTPUT_DIR, f"{project_name}-{commit_sha}-{sut}-simulation-results.json"), "r") as f:
        data = json.load(f)

    simulation_order = data["simulation_order"]
    gdth_snapshots = data["commit_snapshots"]
    edits = []
    for file_path, snapshot in gdth_snapshots.items():
        for window in snapshot:
            if isinstance(window, dict):
                edits.append(window)
    prior_edits = []
    for edit_idx in simulation_order:
        assert edits[edit_idx]["idx"] == edit_idx
        prior_edits.append(edits[edit_idx])

    all_evaluations = []
    for simulation_round, simulation_response in enumerate(data["SUT_prediction_records"][1:], start=1):
        pred_snapshots = simulation_response["pred_snapshots"]
        current_snapshots = simulation_response["curr_gdth_snapshots"]
        previously_applied_locations = simulation_response["previously_applied_locations"]
        reranked_pred_snapshots, rerank_cost = rerank(pred_snapshots, prior_edits[:simulation_round])

        flow_pattern, traditional_metrics, matched_locations, _ = evaluate(reranked_pred_snapshots, current_snapshots, previously_applied_locations)

        assert traditional_metrics["fn"] >= simulation_response["evaluations"]["fn"], f"Have original {simulation_response['evaluations']['fn']} fns, but get {traditional_metrics['fn']} fns"
        evaluations = {
            "flow_pattern": flow_pattern,
            "matched_locations": matched_locations,
            "precision": traditional_metrics["precision"],
            "recall": traditional_metrics["recall"],
            "f1_score": traditional_metrics["f1_score"],
            "tp": traditional_metrics["tp"],
            "fp": traditional_metrics["fp"],
            "fn": traditional_metrics["fn"],
            "time": rerank_cost["time"],
            "token": rerank_cost["token"],
            "price": rerank_cost["price"],
        }
        all_evaluations.append(evaluations)

    with open(os.path.join(OUTPUT_DIR, f"{project_name}-{commit_sha}-{sut}-simulation-results-flow-keeper.json"), "w") as f:
        json.dump(all_evaluations, f, indent=4)

if __name__ == "__main__":
    # sut = "CoEdPilot"
    sut = "Claude"
    # sut = "Cursor_CLI"

    with open("simulation/urls.json", "r") as f:
        urls = json.load(f)

    simulated_urls = 0
    for url in urls:
        print(url)
        if simulated_urls == 500:
            print(f"RQ3 for {sut} is DONE !") 
            break
        rq3_origin(url, sut)
        rq3_flow_keeper(url, sut)
        simulated_urls += 1
                
        
