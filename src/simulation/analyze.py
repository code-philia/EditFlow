import os
import json

def remove_repetitive_recommendation(data):
    matched_with = {}
    jump_cannot_comeback = 0
    for idx, detail_record in enumerate(data["SUT_prediction_records"][1:], start=1):
        actual_applied_edit_idx= data["simulation_order"][idx]
        for file_path, snapshot in detail_record["pred_snapshots"].items():
            for window in snapshot:
                if isinstance(window, list):
                    continue
                if "matchWith" in window:
                    if window["matchWith"] not in matched_with:
                        matched_with[window["matchWith"]] = [("keep", idx) if window["flowKeeping"] else ("jump", idx)]
                    else:
                        if not window["flowKeeping"] and window["idx"] == actual_applied_edit_idx:
                            jump_cannot_comeback += 1
                        matched_with[window["matchWith"]].append(("keep", idx) if window["flowKeeping"] else ("jump", idx))
            
    return matched_with, jump_cannot_comeback
        
def remove_repetitive_recommendation_editflow(data):
    matched_with = {}
    for record in data:
        for matched_location in record["matched_locations"]:
            if matched_location["matchWith"] not in matched_with:
                matched_with[matched_location["matchWith"]] = ["keep" if matched_location["flowKeeping"] else "jump"]
            else:
                if ("keep" if matched_location["flowKeeping"] else "jump") not in matched_with[matched_location["matchWith"]]:
                    matched_with[matched_location["matchWith"]].append("keep" if matched_location["flowKeeping"] else "jump")
           
    return matched_with

def main(sut, dir, base):
    fk = 0
    fj = 0
    fb = 0
    fr = 0
    tp = 0
    fp = 0
    fn = 0
    no_repeat_tp_normal = 0
    # ------
    fk_fk = 0
    fk_fj = 0
    fk_fb = 0
    fk_fr = 0
    fk_tp = 0
    fk_fp = 0
    fk_fn = 0
    no_repeat_tp_editflow = 0
    
    simulated_file_num = 0
    fk_file_num = 0
    record_num = 0
    keep_only_reduction = 0
    jump_only_reduction = 0
    jump_keep_reduction = 0
    
    for output in os.listdir(dir):
        if f"-{sut}-" not in output:
            continue
        
        if "flow-keeper" in output: 
            continue
        with open(os.path.join(dir, output), "r") as f:
            data = json.load(f)

        # calculate normal stats
        simulated_file_num += 1
        with open(os.path.join(dir, output), "r") as f:
            data = json.load(f)
        
        normal_matched_with, jump_cannot_comeback = remove_repetitive_recommendation(data)
        no_repeat_tp_normal += len(normal_matched_with)
        
        for record in data["SUT_prediction_records"][1:]:
            record_num += 1
            fk += len(record["evaluations"]["flow_pattern"]["flow_keeping"])
            fj += len(record["evaluations"]["flow_pattern"]["flow_jumping"])
            fb += len(record["evaluations"]["flow_pattern"]["flow_breaking"])
            fr += len(record["evaluations"]["flow_pattern"]["flow_reverting"])
            
            tp += record["evaluations"]["tp"]
            fp += record["evaluations"]["fp"]
            fn += record["evaluations"]["fn"]
        
        # calculate flow-keeper stats
        fk_output = output.replace(".json", "-flow-keeper.json")
        fk_file_num += 1
        with open(os.path.join(dir, fk_output), "r") as f:
            fk_data = json.load(f)

            editflow_matched_with = remove_repetitive_recommendation_editflow(fk_data)
            no_repeat_tp_editflow += len(editflow_matched_with)
        
        for record in fk_data:
            fk_fk += len(record["flow_pattern"]["flow_keeping"])
            fk_fj += len(record["flow_pattern"]["flow_jumping"])
            fk_fb += len(record["flow_pattern"]["flow_breaking"])
            fk_fr += len(record["flow_pattern"]["flow_reverting"])
            fk_tp += record["tp"]
            fk_fp += record["fp"]
            fk_fn += record["fn"]  
        
        if len(normal_matched_with) > len(editflow_matched_with):
            for key in normal_matched_with:
                if key not in editflow_matched_with:
                    labels = [a[0] for a in normal_matched_with[key]]
                    if "jump" in labels and "keep" in labels:
                        jump_keep_reduction += 1
                    elif "jump" in labels and "keep" not in labels:
                        jump_only_reduction += 1
                    elif "keep" in labels and "jump" not in labels:
                        keep_only_reduction += 1
        
    print(f"Simulated file num: {simulated_file_num}")
    fk_percent = fk/(fk+fj+fb+fr)*100
    fj_percent = fj/(fk+fj+fb+fr)*100
    fr_percent = fr/(fk+fj+fb+fr)*100
    fb_percent = fb/(fk+fj+fb+fr)*100
    
    print(f"Flow-keeping: \t{fk:04d} ({fk_percent:05.2f}%)")
    print(f"Flow-jumping: \t{fj:04d} ({fj_percent:05.2f}%)")
    print(f"Flow-reverting:\t{fr:04d} ({fr_percent:05.2f}%)")
    print(f"Flow-breaking:\t{fb:04d} ({fb_percent:05.2f}%)")
    print(f"Repetitives:")
    print(f"\tTP: {tp}, FP: {fp}, FN: {fn}")
    print(f"Non-repetitives:")
    print(f"\tTP: {no_repeat_tp_normal}")
    precision = tp/(tp+fp)
    assert tp == fk + fj
    assert fp == fb + fr
    print(f"Precision: {precision*100:.2f}%")
    recall = no_repeat_tp_normal/(base)
    print(f"Recall: {recall*100:.2f}%")
    f1 = 2*precision*recall/(precision+recall)
    f05 = (1.25 * precision * recall) / (0.25 * precision + recall)
    print(f"F1: {f1*100:.2f}%")
    print(f"F0.5: {f05*100:.2f}%")

    print("="*20)
    print("Performance after flow keeper")
    print(f"Simulated file num: {fk_file_num}")
    fk_fk_percent = fk_fk/(fk_fk+fk_fj+fk_fb+fk_fr)*100
    fk_fj_percent = fk_fj/(fk_fk+fk_fj+fk_fb+fk_fr)*100
    fk_fb_percent = fk_fb/(fk_fk+fk_fj+fk_fb+fk_fr)*100
    fk_fr_percent = fk_fr/(fk_fk+fk_fj+fk_fb+fk_fr)*100
    print(f"Flow-keeping: \t{fk_fk:04d} ({fk_fk_percent:05.2f}% ({fk_fk_percent - fk_percent:05.2f}%))")
    print(f"Flow-jumping: \t{fk_fj:04d} ({fk_fj_percent:05.2f}% ({fk_fj_percent - fj_percent:05.2f}%))")
    print(f"Flow-reverting:\t{fk_fr:04d} ({fk_fr_percent:05.2f}% ({fk_fr_percent - fr_percent:05.2f}%))")
    print(f"Flow-breaking: \t{fk_fb:04d} ({fk_fb_percent:05.2f}% ({fk_fb_percent - fb_percent:05.2f}%))")
    # print(f"delta KEEP: {fk_fk - fk}, JUMP: {fk_fj - fj}, REVERT: {fk_fr - fr}, BREAK: {fk_fb - fb}")
    print(f"Repetitives:")
    print(f"\tTP: {fk_tp} ({fk_tp-tp}), FP: {fk_fp} ({fk_fp-fp}), FN: {fk_fn} ({fk_fn-fn})")
    print(f"Non-repetitives:")
    print(f"\tTP: {no_repeat_tp_editflow} ({no_repeat_tp_editflow - no_repeat_tp_normal}) -> keep only: {keep_only_reduction}, jump only: {jump_only_reduction}, jump keep both: {jump_keep_reduction}")
    fk_precision = fk_tp/(fk_tp+fk_fp)
    print(f"Precision: \t{fk_precision*100:05.2f}%, delta: {fk_precision*100-precision*100:05.2f}%")
    fk_recall = no_repeat_tp_editflow/(base)
    print(f"Recall: \t{fk_recall*100:05.2f}%, delta: {fk_recall*100-recall*100:05.2f}%")
    fk_f1 = 2*fk_precision*fk_recall/(fk_precision+fk_recall)
    print(f"F1: \t\t{fk_f1*100:05.2f}%, delta: {fk_f1*100-f1*100:05.2f}%")
    fk_f05 = (1.25 * fk_precision * fk_recall) / (0.25 * fk_precision + fk_recall)
    print(f"F0.5: \t\t{fk_f05*100:05.2f}%, delta: {fk_f05*100-f05*100:05.2f}%")



if __name__ == "__main__":
    
    s = {
        "large": {
            "dir": "../oopsla_initial_submission_output_final",
            "base": 3084
        },
        "small": {
            "dir": "../output",
            "base": 185
        },
        "large_recycle": {
            "dir": "../output_500_recycle",
            "base": 3084
        },
        "small_recycle": {
            "dir": "../output_25_recycle",
            "base": 185
        }
    }
    
    size = "large_recycle"
    # size = "small_recycle"
    dir = s[size]["dir"]
    base = s[size]["base"]
    
    for sut in ["Cursor_CLI", "Claude", "CoEdPilot"]:
        print(f"Evaluating {sut}...")
        main(sut, dir, base)
        print("*"*40)
    