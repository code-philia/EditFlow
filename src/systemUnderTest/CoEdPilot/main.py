import os
import time
import torch
from .discriminator import select_files
from .generator import load_model as load_generator_model, predict as generator_predict
from .locator import load_model as load_locator_model, predict as locator_predict

LOCATOR, LOCATOR_TOKENIZER = None, None
GENERATOR, GENERATOR_TOKENIZER = None, None

def main(json_input: dict):
    if json_input["status"] == "init":
        return setup(json_input)
    elif json_input["status"] == "suggestion":
        return subsequent_edit_recommendation(json_input)
    elif json_input["status"] == "end":
        return None

def get_device():
    if torch.cuda.is_available():
        device_id = os.getenv("DEVICE_ID")
        return torch.device(f"cuda:{device_id}")
    elif torch.backends.mps.is_available():
        return torch.device("mps")
    else:
        return torch.device("cpu")

def setup(json_input: dict):
    """
    Setup the system under test (CoEdPilot) for the given commit URL.
    CoEdPilot setup is loading models.
    
    Args:
        json_input (dict): The input json dict.
    """
    this_fp = os.path.dirname(__file__)

    model_path = os.path.join(this_fp, "models", "multilingual", "locator_model.bin")
    global LOCATOR, LOCATOR_TOKENIZER
    if LOCATOR is None or LOCATOR_TOKENIZER is None:
        LOCATOR, LOCATOR_TOKENIZER = load_locator_model(model_path, get_device())
        print("[MESSAGE:SUT] Locator model and tokenizer loaded successfully.")

    model_path = os.path.join(this_fp, "models", "multilingual", "generator_model.bin")
    global GENERATOR, GENERATOR_TOKENIZER
    if GENERATOR is None or GENERATOR_TOKENIZER is None:
        GENERATOR, GENERATOR_TOKENIZER = load_generator_model(model_path, get_device())
        print("[MESSAGE:SUT] Generator model and tokenizer loaded successfully.")


def subsequent_edit_recommendation(json_input):
    selected_files = select_files(json_input["repo_dir"], json_input["prior_edits"])
    input = {
        "device": get_device(),
        "model": LOCATOR,
        "tokenizer": LOCATOR_TOKENIZER,
        "files": selected_files,
        "commitMessage": json_input["edit_description"],
        "prevEdits": json_input["prior_edits"],
    }
    
    total_time = None
    total_price = None
    start = time.time()
    locations, locator_tokens = locator_predict(input)
    end = time.time()
    total_time = end - start
    if len(locations) == 0:
        return {}, {
            "time": total_time,
            "token": locator_tokens,
            "price": locator_tokens / 1000000 * 0.01,  # Assume $0.01 per 1M tokens
        }
    
    input["locations"] = locations
    input["model"] = GENERATOR
    input["tokenizer"] = GENERATOR_TOKENIZER

    start = time.time()
    locations_w_solutions, generator_tokens = generator_predict(input)
    end = time.time()
    total_time += end - start
    total_tokens = locator_tokens + generator_tokens
    
    pred_snapshots = suggestions_to_snapshots(locations_w_solutions, selected_files)
    
    costs = {
        "time": total_time,
        "token": total_tokens,
        "price": total_tokens / 1000000 * 0.01,  # Assume $0.01 per 1M tokens
    }
    return pred_snapshots, costs


def suggestions_to_snapshots(locations_w_solutions, current_version):
    """
    Convert the locations with solutions to snapshots
    """
    for location in locations_w_solutions:
        target_file_path = location["targetFilePath"]
        current_file_snapshot = current_version[target_file_path]

        lineidx = 0
        for widx, window in enumerate(current_file_snapshot):
            if isinstance(window, dict) and window["before"] == []:
                # In this case, the lineidx does not refer to this insert edit dict, but the line of code after it.
                continue
            if lineidx in location["atLines"]:
                if location["editType"] == "add":
                    d = {
                        "before": [],
                        "after": location["replacements"][0].splitlines(keepends=True),
                        "confidence": location["confidence"]
                    }
                    current_file_snapshot.insert(widx+1, d)
                    break

                elif location["editType"] == "replace":
                    d = {
                        "before": current_file_snapshot[widx: widx + len(location["atLines"])],
                        "after": location["replacements"][0].splitlines(keepends=True),
                        "confidence": location["confidence"]
                    }
                    if "".join(d["before"]).strip() == "".join(d["after"]).strip():
                        # Not really an edit
                        break
                    del current_file_snapshot[widx : widx + len(location["atLines"])]
                    current_file_snapshot.insert(widx, d)
                    break
            
            else:
                if isinstance(window, str):
                    lineidx += 1
                elif isinstance(window, dict):
                    lineidx += len(window["before"])

    pred_snapshots = {}
    for file_path, current_file_snapshot in current_version.items():
        pred_snapshots[file_path] = []
        for window in current_file_snapshot:
            if isinstance(window, str):
                if len(pred_snapshots[file_path]) == 0 or not isinstance(pred_snapshots[file_path][-1], list):
                    pred_snapshots[file_path].append([])
                pred_snapshots[file_path][-1].append(window)
            elif isinstance(window, dict):
                # If there are 2 adjacent edit dicts, we merge them into 1
                if len(pred_snapshots[file_path]) > 0 and isinstance(pred_snapshots[file_path][-1], dict):
                    new_d = {
                        "before": pred_snapshots[file_path][-1]["before"] + window["before"],
                        "after": pred_snapshots[file_path][-1]["after"] + window["after"],
                        "confidence": (pred_snapshots[file_path][-1]["confidence"]+ window["confidence"])/2
                    }
                    pred_snapshots[file_path][-1] = new_d
                else:
                    pred_snapshots[file_path].append(window)    

    return pred_snapshots
