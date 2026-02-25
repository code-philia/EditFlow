import os
import json
import concurrent.futures

from tqdm import tqdm
from .rerank import predict_rerank
from .utils import formalize_single_input, add_info_to_snapshots

load_dotenv(dotenv_path=os.path.join(root_path, ".config"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR")

def recycle(rejection_bank, prior_edit):
    prior_edit_str = formalize_single_input(prior_edit)
    rerank_tasks = []
    for rejected_suggestion in rejection_bank:
        rerank_tasks.append({
            "text": f"<edit 0>\n{prior_edit_str}</edit 0>\n<edit 1>\n{rejected_suggestion['edit_text']}</edit 1>",
            "pred_edit_idx": {"round": rejected_suggestion["recommendation_round"], "idx": rejected_suggestion["idx"]},
            "prior_edit_idx": prior_edit["idx"],
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
            
    valid_results = []
    for result in results:
        if result["pred"] in ["no relation", "1 before 0"]:
            # this predicted edit is not flow keeping
            continue
        else:
            valid_results.append(result)
            
    recycled_suggestions = []
    new_rejection_bank = []
    
    for suggestion in rejection_bank:
        id = {"round": suggestion["recommendation_round"], "idx": suggestion["idx"]}
        
        matched_results = [res for res in valid_results if res["pred_edit_idx"] == id]
        if matched_results:
            recycled_suggestions.append(suggestion)
        else:
            new_rejection_bank.append(suggestion)
            
    return recycled_suggestions, new_rejection_bank

def main(sut, output_dir, new_output_dir):
    total_query = 0
    
    with open("attention_flow_keeper_files.json", "r") as f:
        attention_files = json.load(f)
        
    for file in os.listdir(output_dir):
        if "flow-keeper" in file:
            continue
        if sut not in file:
            continue
        
        if file not in attention_files:
            print(f"[SKIP] file: {file} copied to {new_output_dir}.")
            # copy file and editflow file to new output dir directly
            os.makedirs(new_output_dir, exist_ok=True)
            # copy main file in 1 line
            os.system(f"cp {os.path.join(output_dir, file)} {os.path.join(new_output_dir, file)}")
            # copy editflow file in 1 line
            keeper_file = file.replace(".json", "-flow-keeper.json")
            os.system(f"cp {os.path.join(output_dir, keeper_file)} {os.path.join(new_output_dir, keeper_file)}")
            continue
        # if os.path.exists(os.path.join(new_output_dir, file)):
        #     print(f"[SKIP] {file} already processed.")
        #     continue
        
        keeper_file = file.replace(".json", "-flow-keeper.json")
        
        with open(os.path.join(output_dir, file), "r") as f:
            data = json.load(f)
        
        with open(os.path.join(output_dir, keeper_file), "r") as f:
            keeper_data = json.load(f)
            
        rejection_bank = []
        total_edits = len(data["simulation_order"])
        for round, (original_record, editflow_record) in enumerate(zip(data["SUT_prediction_records"][2:], keeper_data[1:]), start=2):
            print(f"[PROCESSING] file: {file}, round: {round}")
            previous_original_pred_snapshots = data["SUT_prediction_records"][round - 1]["pred_snapshots"]
            previous_original_pred_snapshots = add_info_to_snapshots(previous_original_pred_snapshots)
            
            previous_suggestions = []
            for f, snapshot in previous_original_pred_snapshots.items():
                for window in snapshot:
                    if isinstance(window, dict):
                        window["recommendation_round"] = round - 1
                        window["edit_text"] = formalize_single_input(window)
                        previous_suggestions.append(window)
            
            print(f"Round {round}: has {len(previous_suggestions)} previous suggestions")
            previous_editflow_record = keeper_data[round - 2]           
            previous_remained_suggestion_idx = previous_editflow_record["flow_pattern"]["flow_keeping"] + previous_editflow_record["flow_pattern"]["flow_jumping"] + previous_editflow_record["flow_pattern"]["flow_reverting"] + previous_editflow_record["flow_pattern"]["flow_breaking"]
            
            print(f"Round {round}: has {len(previous_remained_suggestion_idx)} previous survived EditFlow: [{previous_remained_suggestion_idx}]")
            
            
            previous_applied_edit_idx = data["simulation_order"][round - 1]
            previous_applied_edit = None
            for f, snapshot in data["commit_snapshots"].items():
                for window in snapshot:
                    if isinstance(window, dict) and window["idx"] == previous_applied_edit_idx:
                        previous_applied_edit = window
                        break
                if previous_applied_edit is not None:
                    break
                
            assert previous_applied_edit is not None, "Previous applied edit not found in commit snapshots."
            
            previous_discared_suggestions = [previous_suggestions[idx] for idx in range(len(previous_suggestions)) if idx not in previous_remained_suggestion_idx]
            print(f"Round {round}: has {len(previous_discared_suggestions)} previous discarded suggestions: [{[s['idx'] for s in previous_discared_suggestions]}]")
            
            rejection_bank.extend(previous_discared_suggestions)
            
            total_query += len(rejection_bank)
            # continue
            
            # let editflow filter these rejected suggestions
            recycled_suggestions, rejection_bank = recycle(rejection_bank, previous_applied_edit)
            
            # update retrained suggestions to editflow record
            for recycled_suggestion in recycled_suggestions:
                if "matchWith" in recycled_suggestion:
                    editflow_record["tp"] += 1
                    iskeep = False
                    for edge in data["partial_orders"]:
                        if edge["src"] == previous_applied_edit_idx and edge["tgt"] == recycled_suggestion["matchWith"]:
                            editflow_record["flow_pattern"]["flow_keeping"].append( {"round": recycled_suggestion["recommendation_round"], "idx": recycled_suggestion["idx"]} )
                            
                            new_matched_loc = None
                            for matched_loc in data["SUT_prediction_records"][recycled_suggestion["recommendation_round"]]["evaluations"]["matched_locations"]:
                                if matched_loc["predIdx"] == recycled_suggestion["idx"]:
                                    new_matched_loc = matched_loc.copy()
                            assert new_matched_loc is not None, f"file {os.path.join(output_dir,file)}, recycled_suggestion at round {recycled_suggestion['recommendation_round']} idx {recycled_suggestion['idx']}"
                            new_matched_loc["predIdx"] = {"round": recycled_suggestion["recommendation_round"], "idx": recycled_suggestion["idx"]}
                            new_matched_loc["flowKeeping"] = True
                            editflow_record["matched_locations"].append(new_matched_loc)
                            iskeep = True
                            break
                    if not iskeep:
                        editflow_record["flow_pattern"]["flow_jumping"].append( {"round": recycled_suggestion["recommendation_round"], "idx": recycled_suggestion["idx"]} )
                        
                        new_matched_loc = None
                        for matched_loc in data["SUT_prediction_records"][recycled_suggestion["recommendation_round"]]["evaluations"]["matched_locations"]:
                            if matched_loc["predIdx"] == recycled_suggestion["idx"]:
                                new_matched_loc = matched_loc.copy()
                                break
                        assert new_matched_loc is not None
                        new_matched_loc["predIdx"] = {"round": recycled_suggestion["recommendation_round"], "idx": recycled_suggestion["idx"]}
                        new_matched_loc["flowKeeping"] = False
                        editflow_record["matched_locations"].append(new_matched_loc)
                else:
                    editflow_record["fp"] += 1
                    editflow_record["flow_pattern"]["flow_breaking"].append( {"round": recycled_suggestion["recommendation_round"], "idx": recycled_suggestion["idx"]} )
                
            assert len(editflow_record["matched_locations"]) == editflow_record["tp"] == len(editflow_record["flow_pattern"]["flow_keeping"]) + len(editflow_record["flow_pattern"]["flow_jumping"])
            
            editflow_record["fn"] = total_edits - round - editflow_record["tp"]
            
            editflow_record["precision"] = editflow_record["tp"] / (editflow_record["tp"] + editflow_record["fp"]) if (editflow_record["tp"] + editflow_record["fp"]) > 0 else 0.0
            
            editflow_record["recall"] = editflow_record["tp"] / (editflow_record["tp"] + editflow_record["fn"]) if (editflow_record["tp"] + editflow_record["fn"]) > 0 else 0.0
            
            editflow_record["f1"] = 2 * editflow_record["precision"] * editflow_record["recall"] / (editflow_record["precision"] + editflow_record["recall"]) if (editflow_record["precision"] + editflow_record["recall"]) > 0 else 0.0
            
    
        os.makedirs(new_output_dir, exist_ok=True)
        with open(os.path.join(new_output_dir, file), "w") as f:
            json.dump(data, f, indent=4)
            
        with open(os.path.join(new_output_dir, keeper_file), "w") as f:
            json.dump(keeper_data, f, indent=4)
    
    print(f"[SUMMARY] Total recycle query count for sut {sut}: {total_query}")
    
if __name__ == "__main__":
    sut = "CoEdPilot"
    new_output_dir = OUTPUT_DIR + "_recycle"
    main(sut, OUTPUT_DIR, new_output_dir)
            
            