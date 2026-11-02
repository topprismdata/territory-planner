import argparse
from datetime import datetime, timezone
import json
from importlib.metadata import version
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from . import __version__
from .data import digest, load_dataset, read_assignment, read_config
from .evaluation import evaluate
from .report import export


def main():
    parser = argparse.ArgumentParser(description="销售辖区规划：输入校验、研究求解、独立验收与报告")
    parser.add_argument("command", choices=["validate", "evaluate", "solve"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--assignment")
    parser.add_argument("--output")
    parser.add_argument("--method", choices=["ATS2018", "ALS2018", "WTS2018", "GEN2019"], default="ATS2018")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    created_folder = False
    try:
        root, config = read_config(args.config)
        dataset = load_dataset(root, config)
        if args.command == "validate":
            print(json.dumps({"valid": True, "units": len(dataset["units"]), "totals": dataset["attrs"].sum(0).tolist()}, ensure_ascii=False))
            return 0
        assignment = Path(args.assignment).resolve() if args.assignment else root / config["assignment"]
        initial = read_assignment(assignment, len(dataset["units"]), config["hc"])
        initial_audit = evaluate(dataset, config, initial)
        folder = Path(args.output).resolve() if args.output else root / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        if folder.exists():
            raise ValueError("输出目录已存在；请使用新目录，避免覆盖历史结果")
        backend_meta = None
        if args.command == "solve":
            profile = json.loads((root / "adapters/research.json").read_text())
            if config["hc"] != 8 or config["tolerance"] != [.2, .2, .15] or config["distance_cap_km"] != 90.9:
                raise ValueError("研究后端固化8HC、20%/20%/15%、90.9km；其他配置可验收候选，但须先适配求解器")
            if digest(dataset["folder"] / "manifest.json") != profile["dataset_manifest_sha256"]:
                raise ValueError("研究后端输入与固定模型不一致，拒绝静默使用旧模型")
            if not initial_audit["accepted"]:
                raise ValueError("共同起点必须通过全部约束核验")
            seconds = config["search_seconds"]
            if not isinstance(seconds, int) or not 1 <= seconds <= 3600 or args.seed < 1:
                raise ValueError("搜索时限须为1～3600整数秒，种子须为正整数")
            engine = profile["engines"][args.method]
            binary = Path(engine["executable"])
            if not binary.is_file() or digest(binary) != engine["sha256"]:
                raise ValueError("可选研究程序缺失或版本不符；请按适配器文档重新注册")
            folder.mkdir(parents=True)
            created_folder = True
            warm = folder / "warm_start.txt"
            np.savetxt(warm, initial, fmt="%d")
            target = folder / "raw_assignment.txt"
            command = [str(binary), "--in", str(dataset["folder"] / "engine.dat"), "--out", str(target), "--time", str(seconds), "--seed", str(args.seed), *engine["options"]]
            env = os.environ.copy()
            env["CTDP_WARM_START"] = str(warm)
            process = subprocess.run(command, cwd=folder, env=env, capture_output=True, text=True, timeout=seconds+35)
            (folder / "solver.stdout.log").write_text(process.stdout)
            (folder / "solver.stderr.log").write_text(process.stderr)
            if process.returncode != 0 or not target.exists():
                (folder / "failure.json").write_text(json.dumps({"status": "failed", "reason": "求解未返回可核验分区", "returncode": process.returncode}))
                raise ValueError("求解失败；日志已保留，不能用起点冒充求解输出")
            labels = np.loadtxt(target, dtype=int)
            if labels.shape != initial.shape or set(labels) != set(range(config["hc"])):
                raise ValueError("研究程序输出的分配格式不完整")
            backend_meta = {"method": args.method, "seed": args.seed, "seconds": seconds, "binary_sha256": digest(binary), "engine_metadata": json.loads((folder / "internal_search.json").read_text())}
        else:
            folder.mkdir(parents=True)
            created_folder = True
            labels = initial
        result = evaluate(dataset, config, labels)
        result["strict_improvement_vs_start"] = bool(result["accepted"] and initial_audit["accepted"] and result["maximum_span_km"] < initial_audit["maximum_span_km"]-1e-7) if args.command == "solve" else None
        manifest = {"version": __version__, "command": args.command, "created_utc": datetime.now(timezone.utc).isoformat(), "config_sha256": digest(args.config), "assignment_sha256": digest(assignment), "dataset": dataset["manifest"], "backend": backend_meta, "python": sys.version, "dependencies": {name: version(name) for name in ["numpy", "scipy", "pandas", "networkx", "openpyxl"]}, "code_sha256": {p.name: digest(p) for p in Path(__file__).parent.glob("*.py")}}
        export(folder, dataset, config, labels, result, manifest)
        print(json.dumps({"accepted": result["accepted"], "maximum_span_km": result["maximum_span_km"], "report": str(folder / "report.html")}, ensure_ascii=False))
        return 0 if result["accepted"] else 2
    except (ValueError, KeyError, FileNotFoundError, subprocess.TimeoutExpired) as error:
        if created_folder:
            (folder / "failure.json").write_text(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False))
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
