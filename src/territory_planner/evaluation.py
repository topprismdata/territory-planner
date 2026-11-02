import networkx as nx
import numpy as np
from scipy.sparse.csgraph import connected_components, dijkstra


def evaluate(dataset, config, labels):
    attrs, hc = dataset["attrs"], config["hc"]
    means = attrs.sum(0) / hc
    totals = np.array([attrs[labels == k].sum(0) for k in range(hc)])
    ratios = totals / means
    balance = bool(np.all(np.abs(ratios - 1) <= np.array(config["tolerance"]) + 1e-9))
    info, roads = dataset["info"], dataset["roads"]
    groups = []
    for k in range(hc):
        ids = np.flatnonzero(labels == k)
        mask = np.flatnonzero(labels[info["street"]] == k)
        sub = roads[mask][:, mask]
        reps = np.searchsorted(mask, info["rep_indices"][ids])
        _, components = connected_components(sub, directed=True, connection="strong")
        connected = len(np.unique(components[reps])) == 1
        span = None
        if connected:
            distances = dijkstra(sub, directed=True, indices=reps)[:, reps]
            span = float(distances.max())
        groups.append({"territory_id": k + 1, "units": ids.tolist(),
                       "street_connected": nx.is_connected(dataset["graph"].subgraph(ids)),
                       "road_connected": bool(connected), "span_km": span,
                       "totals": totals[k].tolist(), "indices": (ratios[k] * 100).tolist()})
    road_ok = all(g["road_connected"] for g in groups)
    graph_ok = all(g["street_connected"] for g in groups)
    span = max(g["span_km"] for g in groups) if road_ok else None
    cap_ok = bool(road_ok and span <= config["distance_cap_km"] + 1e-9)
    return {"accepted": balance and graph_ok and cap_ok, "balance_pass": balance,
            "street_connectivity_pass": graph_ok, "road_connectivity_pass": road_ok,
            "distance_pass": cap_ok, "maximum_span_km": span, "groups": groups,
            "totals": attrs.sum(0).tolist(), "means": means.tolist(),
            "interpretation": "可行不代表新增优化成果；计划拜访不等于工时；未关联不等于未开发。"}
