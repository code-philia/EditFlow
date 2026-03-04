# Given a commit url, construct an edit partial order graph with pure heuristic rules
import warnings
warnings.filterwarnings("ignore")

import itertools
import rapidfuzz.fuzz as fuzz

from .utils import string_diff_dict

def find_cut_paste_relationship(edit_hunks):
    edges = []
    for hunk1, hunk2 in itertools.combinations(edit_hunks, 2):
        # Edit relationship 1: Cut-paste
        if hunk1["before"] == [] and hunk2["after"] == [] and \
          hunk1['type'] == "insert" and hunk2['type'] == "delete":
            if fuzz.ratio("".join(hunk1["after"]), "".join(hunk2["before"])) / 100 > 0.8:
                edges.append({
                    "source": hunk2["idx"],
                    "target": hunk1["idx"],
                    "reason": "Cut-paste",
                    "direction": "unidirectional"
                })
        elif hunk1["after"] == [] and hunk2["before"] == [] and \
          hunk1['type'] == "delete" and hunk2['type'] == "insert":
            if fuzz.ratio("".join(hunk1["before"]), "".join(hunk2["after"])) / 100 > 0.8:
                edges.append({
                    "source": hunk1["idx"],
                    "target": hunk2["idx"],
                    "reason": "Cut-paste",
                    "direction": "unidirectional"
                })
    return edges

def find_copy_paste_relationship(edit_hunks, language):
    edges = []
    for hunk1, hunk2 in itertools.combinations(edit_hunks, 2):
        # both are of same type
        if not (hunk1['type'] == "delete" and hunk2['type'] == "delete"  or \
        hunk1['type'] == "insert" and hunk2['type'] == "insert" or \
        hunk1['type'] == "replace" and hunk2['type'] == "replace"):
            continue

        if fuzz.ratio("".join(hunk1["before"]).strip(), "".join(hunk2["before"]).strip()) / 100 > 0.85 and \
        fuzz.ratio("".join(hunk1["after"]).strip(), "".join(hunk2["after"]).strip()) / 100 > 0.85:
            edges.append({
                "source": hunk1["idx"],
                "target": hunk2["idx"],
                "reason": "Copy-paste",
                "direction": "bidirectional"
            })
        else:
            hunk1_diff = string_diff_dict("".join(hunk1["before"]), "".join(hunk1["after"]), language)
            hunk2_diff = string_diff_dict("".join(hunk2["before"]), "".join(hunk2["after"]), language)
            
            empty_diff = {'deleted': [], 'added': []}
            if hunk1_diff == hunk2_diff and hunk1_diff != empty_diff:
                edges.append({
                    "source": hunk1["idx"],
                    "target": hunk2["idx"],
                    "reason": "Copy-paste",
                    "direction": "bidirectional"
                })
    return edges

def find_positional_relationship(edit_hunks):
    edges = []
    for hunk1, hunk2 in itertools.combinations(edit_hunks, 2):
        if hunk1["file_path"] == hunk2["file_path"] and \
            abs(hunk1["idx"] - hunk2["idx"]) == 1:       # this only applies to adjacent edit hunks 
            # If two edit hunks are in the same file and adjacent, they are in positional order
            if hunk1["idx"] < hunk2["idx"]:
                prev_hunk = hunk1
                next_hunk = hunk2
            else:
                prev_hunk = hunk2
                next_hunk = hunk1
            
            # We know these hunks are in the same file, same class, and same function.
            # Further check if they are close enough in the codebase
            if next_hunk["parent_version_range"]["start"] - prev_hunk["parent_version_range"]["end"] <= 10 or \
            next_hunk["child_version_range"]["start"] - prev_hunk["child_version_range"]["end"] <= 10: # not more than 10 lines apart
                edges.append({
                    "source": prev_hunk["idx"],
                    "target": next_hunk["idx"],
                    "reason": "Positional order",
                    "direction": "unidirectional"
                })
    return edges

def add_clone_to_snapshot(data, clone_edges):
    for _, snapshot in data["commit_snapshots"].items():
        for window in snapshot:
            if isinstance(window, list):
                continue
            if "other_clones" not in window:
                window["other_clones"] = []

    for edge in clone_edges:
        for _, snapshot in data["commit_snapshots"].items():
            for window in snapshot:
                if isinstance(window, list):
                    continue
                if window["idx"] == edge["source"] and edge["target"] not in window["other_clones"]:
                    window["other_clones"].append(edge["target"])
                if window["idx"] == edge["target"] and edge["source"] not in window["other_clones"]:
                    window["other_clones"].append(edge["source"])
