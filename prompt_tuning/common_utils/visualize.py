import json
import sys
import networkx as nx
from typing import Dict, Any
sys.path.append("../../")
from lib.pyvis.network import Network
import matplotlib.pyplot as plt

def recurse(graph, cycle_edges):
    if len(cycle_edges) == 0:
        graphs.append(graph.copy())
        return
        
    for u, v in cycle_edges:
        copy = cycle_edges.copy()
        copy.remove((u, v))
        if (v, u) in copy:
            copy.remove((v, u))
        graph.remove_edge(u, v)
        recurse(graph, copy)
        graph.add_edge(u, v)

def remove_redundant_edges(graph):
    while True:
        for edge in graph.edges:
            A, C = edge
            for B in graph.successors(A):
                if B != C and graph.has_edge(B, C):
                    graph.remove_edge(A, C)
                    break
            else:
                continue
            break
        break

def datasample2graph(sample_path: str, remove_redundant: bool = True, gold : bool = True) -> nx.DiGraph:
    with open(sample_path, 'r', encoding='utf-8') as f:
        sample = json.load(f)
    graph = nx.DiGraph()

    color_list = [
        '#00ff1e', '#162347', '#dd4b39', '#1e90ff', '#ff8c00',
        '#8a2be2', '#ffd700', '#32cd32', '#ff1493', '#00ced1'
    ]

    def get_color(index: int) -> str:
        return color_list[index % len(color_list)]

    commit_snapshots = sample.get("commit_snapshots", {})
    for file_idx, (file_path, snapshots) in enumerate(commit_snapshots.items()):
        node_color = get_color(file_idx)

        for widx, window in enumerate(snapshots):
            if isinstance(window, list):
                continue

            prev_window = snapshots[widx-1] if widx > 0 else None
            next_window = snapshots[widx+1] if widx < len(snapshots)-1 else None

            if prev_window and isinstance(prev_window, list) and prev_window:
                prefix_text = "".join(prev_window[-min(3, len(prev_window)):])
            else:
                prefix_text = ""

            if next_window and isinstance(next_window, list) and next_window:
                suffix_text = "".join(next_window[:min(3, len(next_window))])
            else:
                suffix_text = ""
            
            suffix_text = suffix_text.rstrip("\n")

            before_lines = "".join(window.get("before", []))
            after_lines = "".join(window.get("after", []))

            logic_paths = [p.get("signature", "") for p in window.get("structural_path", [])]
            logic_path_str = " >>>> ".join(logic_paths)

            title = (
                f"<div style='white-space: pre; font-family: monospace; background-color: white; padding: 5px; border: 1px solid black;'>"
                f"<strong>File path:</strong> {file_path}\n"
                f"<strong>Logic path:</strong> {logic_path_str}\n"
                f"<strong>Code:</strong>\n{prefix_text}"
                f"<span style='color: #e63946;'>{before_lines}</span>"
                f"<span style='color: #2e8b57;'>{after_lines}</span>"
                f"{suffix_text}</div>"
            )

            node_id = window.get("idx")
            if "file_path" in window:
                window.pop("file_path")
            if node_id is not None:
                graph.add_node(node_id, **window, title=title, label=str(node_id), color=node_color, file_path=file_path)

    for partial_order in sample.get("partial_orders", []):
        try:
            source = int(partial_order.get("edit_hunk_pair")[0])
            target = int(partial_order.get("edit_hunk_pair")[1])
        except:
            source = partial_order.get("source")
            target = partial_order.get("target")
        try:
            reason = partial_order.get("reason")
        except:
            reason = "null"
        
        dir_str = f"{source}->{target}"
        edge_title = (
            f"<div style='background-color: white; padding: 5px; border: 1px solid black;'>"
            f"<p><strong>Direction:</strong> {dir_str}</p>"
            f"<p><strong>Reason:</strong> {reason}</p></div>"
        )

        if gold and partial_order.get("edit_order") == "bi-directional":
            graph.add_edge(source, target, reason=reason, title=edge_title)
            graph.add_edge(target, source, reason=reason, title=edge_title)
        elif source is not None and target is not None:
            graph.add_edge(source, target, reason=reason, title=edge_title)

    if remove_redundant:
        remove_redundant_edges(graph)
    
    """
    Below are code for finding the minimal acyclic graph and visualize it.
    """
    # scc = list(nx.strongly_connected_components(graph))
    # for component in scc:
    #     if len(component) > 1:
    #         for node in component:
    #             graph.nodes[node]['color'] = '#ff0000'
    # print(f"Strongly connected components: {scc}")
    
    # for component in scc:
    #     if len(component) > 1:
    #         super_node_id = f"super_{'_'.join(map(str, sorted(component)))}"
    #         super_node_title = (
    #             "<div style='max-height: 400px; overflow-y: auto; background-color: white; padding: 5px; border: 1px solid black;'>"
    #             + "<br>".join([graph.nodes[node]['title'] for node in component])
    #             + "</div>"
    #         )
    #         super_node_label = ",".join(map(str, sorted(component)))
    #         super_node_color = "#ff69b4"

    #         file_paths = set(graph.nodes[node]['file_path'] for node in component)
    #         super_node_file_paths = ", ".join(file_paths)

    #         graph.add_node(super_node_id, title=super_node_title, label=super_node_label, color=super_node_color, physics=False, shape='box', file_path=super_node_file_paths)

    #         for node in component:
    #             for pred in list(graph.predecessors(node)):
    #                 if pred not in component:
    #                     graph.add_edge(pred, super_node_id, reason=graph.edges[pred, node]['reason'], title=graph.edges[pred, node]['title'])
    #             for succ in list(graph.successors(node)):
    #                 if succ not in component:
    #                     graph.add_edge(super_node_id, succ, reason=graph.edges[node, succ]['reason'], title=graph.edges[node, succ]['title'])

    #         for node in component:
    #             graph.remove_node(node)

    # cycle_edges = []
    # graphs = []
    # graphc = graph.copy()
    # while True:
    #     try:
    #         edges = nx.find_cycle(graphc)
    #         for u, v in edges:
    #             graphc.remove_edge(u, v)
    #             cycle_edges.append((u, v))
    #     except nx.NetworkXNoCycle:
    #         break
            
    # print("Cycle: ", cycle_edges)
    
    # if not cycle_edges:
    #     return [graph]
    
    # for graph, _ in find_minimal_acyclic_graphs(graph, cycle_edges):
    #     graphs.append(graph)
    """
    Above are code for finding the minimal acyclic graph and visualize it.
    """
    
    print("Graphs: ", graph)
    nt = Network('1000px', '1000px', notebook=True, cdn_resources='remote', directed=True)
    nt.from_nx(graph)
    nt.show('graph.html')
    return graph


def is_acyclic(G):
        """Check acyclicity:
             For directed graphs, use nx.is_directed_acyclic_graph.
             For undirected graphs, try to find a cycle.
        """
        if G.is_directed():
                return nx.is_directed_acyclic_graph(G)
        else:
                try:
                        nx.find_cycle(G)
                        return False
                except nx.NetworkXNoCycle:
                        return True

def find_minimal_acyclic_graphs_rec(G, candidate_edges, index, removed, best, results):
        """
        Recursively decide, for each candidate edge, whether to remove it.
        
        Parameters:
            G              : The current graph (modified in place).
            candidate_edges: List of candidate edges (tuples). These edges are known to be part of some cycle.
            index          : The current candidate index being considered.
            removed        : List of candidate edges removed so far.
            best           : A one-element list holding the best (minimal) removal count found so far.
            results        : A list collecting tuples (graph, removed_edges) for acyclic graphs
                                             achieved with minimal removals.
        """
        # When all candidates have been considered, check if the graph is acyclic.
        if index == len(candidate_edges):
                if is_acyclic(G):
                        r = len(removed)
                        if r < best[0]:
                                best[0] = r
                                results.clear()
                                results.append((G.copy(), removed.copy()))
                        elif r == best[0]:
                                # Deduplicate: compare the frozenset of edges.
                                key = frozenset(G.edges())
                                if not any(frozenset(g.edges()) == key for g, _ in results):
                                        results.append((G.copy(), removed.copy()))
                return

        # Prune branches that already have removals >= current best.
        if len(removed) >= best[0]:
                return

        # Option 1: Do not remove candidate_edges[index]
        find_minimal_acyclic_graphs_rec(G, candidate_edges, index + 1, removed, best, results)

        # Option 2: Remove candidate_edges[index] (if it exists in G).
        edge = candidate_edges[index]
        if G.has_edge(*edge):
                G.remove_edge(*edge)
                removed.append(edge)
                find_minimal_acyclic_graphs_rec(G, candidate_edges, index + 1, removed, best, results)
                removed.pop()
                G.add_edge(*edge)

def find_minimal_acyclic_graphs(G, candidate_edges):
        """
        Given an existing graph G and a list of candidate cycle edges, remove the minimal number of
        candidate edges so that the resulting graph is acyclic. Returns a list of tuples:
            (acyclic_graph, removed_edges)
        """
        results = []
        best = [float('inf')]
        find_minimal_acyclic_graphs_rec(G, candidate_edges, 0, [], best, results)
        return results

if __name__ == "__main__":
    graphs = datasample2graph("database/glances-25b6b5c797b348318bf3f1bf110944c4f37d5e2d.json", remove_redundant=False)
    print(graphs)
    # assert isinstance(graphs, list)