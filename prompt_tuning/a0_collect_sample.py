import os
import sys
import json
import networkx as nx

sys.path.append("..")
from common_utils.utils import extract_hunks, get_hunk_diff, get_edits
from common_utils.dependency import analyze_dependency, add_dep_to_snapshot
from common_utils.heuristic_relation import find_copy_paste_relationship, add_clone_to_snapshot

commit_url = ""

language = ""
commit_sha = commit_url.split("/")[-1]
commit_proj = commit_url.split("/")[-3]
commit_message, commit_snapshots = extract_hunks(commit_url)
commit_snapshots = get_hunk_diff(commit_snapshots)
commit = {
    "language": language,
    "commit_url": commit_url,
    "commit_message": commit_message,
    "commit_snapshots": commit_snapshots,
    "partial_orders": []
}
# Construct edits from commit snapshots
edits = get_edits(commit_snapshots)

# Analyze the static relationships between each pair of edits
copy_paste_edges = find_copy_paste_relationship(edits, language)
dependency_edges = analyze_dependency(commit)
add_dep_to_snapshot(commit, dependency_edges)
add_clone_to_snapshot(commit, copy_paste_edges)
"""
Commit:
    language:           str, programming language
    commit_url:         str, commit url
    commit_message:     str, commit message
    commit_snapshots:   list[list[str]|dict]
    partial_orders:     list[dict], each dict contains:
        source:           int, source node index, 0-based
        target:           int, target node index, 0-based
        reason:           str        
"""

# ------------- Add partial orders for this commit -------------
"""
Example:

commit["partial_orders"].append({
    "edit_hunk_pair": [
        0,
        1
    ],
    "edit_order": "bi-directional",
    "reason": "",
    "scenario of 0 -> 1": "",
    "scenario of 1 -> 0": ""
})

Note:
    if the edge is bidirectional, you need to add two edges.
"""

# ------------- Finish adding partial orders for this commit -------------

# Convert commit partial orders to graph
# graph = nx.DiGraph()
# for partial_order in commit["partial_orders"]:
#     graph.add_edge(partial_order["source"], partial_order["target"], reason=partial_order["reason"])

# # Remove redundant edges
# remove_redundant_edges(graph)

# # Convert graph to commit
# commit["partial_orders"] = []
# for edge in graph.edges:
#     commit["partial_orders"].append({
#         "source": edge[0],
#         "target": edge[1],
#         "reason": graph.edges[edge]["reason"]
#     })

# ------------- Save to database -------------------
os.makedirs("database", exist_ok=True)
with open(f"database/{commit_proj}-{commit_sha}.json", "w") as f:
    json.dump(commit, f, indent=4)
    
from common_utils.visualize import datasample2graph
graph = datasample2graph(f"database/{commit_proj}-{commit_sha}.json", remove_redundant=False)
assert isinstance(graph, nx.Graph)
