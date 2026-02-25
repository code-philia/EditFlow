# Prepare Prompt tuning Dataset

import os
import json
import random
import common_utils.construct_input as construct_input
from itertools import combinations

# Edit order:
# 0 before 1: 0
# 1 before 0: 1
# bi-directional: 2
# no relation: 3

if __name__ == "__main__":
    projects = []
    nodes_num = []
    edges_num = []

    for filename in os.listdir("database"):
        with open(os.path.join("database", filename), "r") as f:
            commit = json.load(f)
        commit_url = commit["commit_url"]
        project_name = commit_url.split("/")[-3]
        if project_name not in projects:
            projects.append(project_name)

        window_num = 0
        for file_path, snapshot in commit["commit_snapshots"].items():
            for window in snapshot:
                if isinstance(window, dict):
                    window_num += 1

        nodes_num.append(window_num)

        edge_num = 0
        for edge in commit["partial_orders"]:
            if edge["edit_order"] == "bi-directional":
                edge_num += 2
            elif edge["edit_order"] != "no relation":
                edge_num += 1
        edges_num.append(edge_num)


    print(f"Human labelled database contain:")
    print("{} files".format(len(os.listdir('database'))))
    print("{} projects".format(len(projects)))
    print("{} nodes".format(sum(nodes_num)))
    print("{} edges".format(sum(edges_num)))
    print("="*20)

    datasets = []
    
    for file_name in os.listdir("database"):
        with open(os.path.join("database", file_name), "r") as f:
            data_sample = json.load(f)

        edits = []
        for file_path, snapshot in data_sample["commit_snapshots"].items():
            for window in snapshot:
                if isinstance(window, dict):
                    window["commit_url"] = data_sample["commit_url"]
                    edits.append(window)

        for edit_pair in list(combinations(edits, 2)):
            e0, e1 = edit_pair
            e0_idx = e0["idx"]
            e1_idx = e1["idx"]

            find_edge = False
            e0_str, e1_str = construct_input.formalize_input(e0, e1)
            for edge in data_sample["partial_orders"]:
                if set([e0_idx, e1_idx]) != set(edge["edit_hunk_pair"]):
                    continue
                
                if edge["edit_order"] == "no relation":
                    continue
                elif edge["edit_order"] == "bi-directional":
                    datasets.append({
                        "text": f"<edit 0>\n{e0_str}</edit 0>\n<edit 1>\n{e1_str}</edit 1>",
                        "label": "bi-directional",
                        "commit_url": data_sample["commit_url"],
                        "edit_hunk_pair": edge["edit_hunk_pair"]
                    })
                    find_edge = True
                    break
                elif edge["edit_order"] == "0 before 1":
                    if [e0_idx, e1_idx] == edge["edit_hunk_pair"]:
                        datasets.append({
                            "text": f"<edit 0>\n{e0_str}</edit 0>\n<edit 1>\n{e1_str}</edit 1>",
                            "label": "0 before 1",
                            "commit_url": data_sample["commit_url"],
                            "edit_hunk_pair": edge["edit_hunk_pair"]
                        })
                    else:
                        datasets.append({
                            "text": f"<edit 0>\n{e0_str}</edit 0>\n<edit 1>\n{e1_str}</edit 1>",
                            "label": "1 before 0",
                            "commit_url": data_sample["commit_url"],
                            "edit_hunk_pair": edge["edit_hunk_pair"]
                        })
                    find_edge = True
                    break

                elif edge["edit_order"] == "1 before 0":
                    if [e0_idx, e1_idx] == edge["edit_hunk_pair"]:
                        datasets.append({
                            "text": f"<edit 0>\n{e0_str}</edit 0>\n<edit 1>\n{e1_str}</edit 1>",
                            "label": "1 before 0",
                            "commit_url": data_sample["commit_url"],
                            "edit_hunk_pair": edge["edit_hunk_pair"]
                        })
                    else:
                        datasets.append(
                            {
                                "text": f"<edit 0>\n{e0_str}</edit 0>\n<edit 1>\n{e1_str}</edit 1>",
                                "label": "0 before 1",
                                "commit_url": data_sample["commit_url"],
                                "edit_hunk_pair": edge["edit_hunk_pair"]
                            }
                        )
                    find_edge = True
                    break

            if find_edge == False:
                datasets.append({
                    "text": f"<edit 0>\n{e0_str}</edit 0>\n<edit 1>\n{e1_str}</edit 1>",
                    "label": "no relation",
                    "commit_url": data_sample["commit_url"],
                    "edit_hunk_pair": [e0_idx, e1_idx]
                })

    # split into train and test in 7:3 ratio
    train_datasets = datasets[:int(len(datasets) * 0.7)]
    random.shuffle(train_datasets)
    test_datasets = datasets[int(len(datasets) * 0.7):]
    random.shuffle(test_datasets)

    os.makedirs("dataset", exist_ok=True)
    print(f"Converted to Prompt tuning Train dataset size: {len(train_datasets)}")
    with open("dataset/train.json", "w") as f:
        json.dump(train_datasets, f, indent=4)

    print(f"Converted to Prompt tuning Test dataset size: {len(test_datasets)}")
    with open("dataset/test.json", "w") as f:
        json.dump(test_datasets, f, indent=4)