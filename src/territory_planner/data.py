from pathlib import Path
import hashlib
import json

import networkx as nx
import numpy as np
import pandas as pd
from scipy.sparse import load_npz

METRICS = ["market", "customers", "visits"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_config(path):
    path = Path(path).resolve()
    config = json.loads(path.read_text())
    root = path.parent.parent
    if type(config.get("hc")) is not int or config["hc"] < 1:
        raise ValueError("hc必须为正整数")
    if len(config.get("tolerance", [])) != 3 or any(not 0 <= v < 1 for v in config["tolerance"]):
        raise ValueError("三项容差必须分别位于[0,1)")
    if not np.isfinite(config.get("distance_cap_km", np.nan)) or config["distance_cap_km"] <= 0:
        raise ValueError("distance_cap_km必须为正数")
    if config.get("distance_mode") != "induced_directed_road":
        raise ValueError("本版仅实现组内诱导有向道路距离")
    if config.get("objective") != "minimize_maximum_internal_road_span":
        raise ValueError("本版尚未实现其他优化目标，不能只改参数名称")
    return root, config


def load_dataset(root, config):
    folder = root / config["dataset"]
    manifest = json.loads((folder / "manifest.json").read_text())
    for name, expected in manifest["sha256"].items():
        if digest(folder / name) != expected:
            raise ValueError(f"输入文件校验不一致：{name}")
    units = pd.read_csv(folder / "units.csv")
    if units["unit_id"].tolist() != list(range(len(units))):
        raise ValueError("unit_id必须按0到N-1连续排列，并与道路索引一致")
    attrs = units[METRICS].to_numpy(float)
    if not np.isfinite(attrs).all() or (attrs < 0).any() or (attrs.sum(0) <= 0).any():
        raise ValueError("三项指标必须有限、非负，且各项全市总量大于0")
    if config["hc"] > len(units):
        raise ValueError("hc不能超过基本单元数量")
    edges = pd.read_csv(folder / "adjacency.csv")
    if not set(edges[["u", "v"]].to_numpy().ravel()).issubset(set(units.unit_id)):
        raise ValueError("邻接引用不存在的单元")
    graph = nx.Graph()
    graph.add_nodes_from(units.unit_id)
    graph.add_edges_from(edges[["u", "v"]].itertuples(index=False, name=None))
    roads = load_npz(folder / "roads.npz")
    with np.load(folder / "road_nodes.npz") as archive:
        info = {key: archive[key] for key in archive.files}
    owners, reps = info["street"], info["rep_indices"]
    if roads.shape != (len(owners), len(owners)) or len(reps) != len(units):
        raise ValueError("道路图、道路节点及代表点数量不一致")
    if not np.isfinite(roads.data).all() or (roads.data < 0).any():
        raise ValueError("道路长度必须有限且非负")
    if (owners < 0).any() or (owners >= len(units)).any() or (reps < 0).any() or (reps >= len(owners)).any():
        raise ValueError("道路节点或代表点索引越界")
    if not np.array_equal(owners[reps], np.arange(len(units))):
        raise ValueError("代表点不属于对应单元")
    geometry = json.loads((folder / "boundaries.geojson").read_text())
    if len(geometry["features"]) != len(units):
        raise ValueError("边界与单元数量不一致")
    return {"folder": folder, "units": units, "attrs": attrs, "graph": graph,
            "roads": roads, "info": info, "geometry": geometry, "manifest": manifest}


def read_assignment(path, count, hc):
    frame = pd.read_csv(path)
    if list(frame.columns) != ["unit_id", "territory_id"]:
        raise ValueError("分配文件字段必须为unit_id,territory_id")
    frame = frame.sort_values("unit_id")
    if frame.unit_id.tolist() != list(range(count)):
        raise ValueError("分配必须完整且唯一，不能漏单元或重复")
    values = frame.territory_id.to_numpy(float)
    if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
        raise ValueError("territory_id必须为整数")
    if set(values) != set(range(1, hc + 1)):
        raise ValueError("辖区必须从1到hc编号，且各组非空")
    return values.astype(int) - 1
