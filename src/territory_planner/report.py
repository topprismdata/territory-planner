import html
import json
from pathlib import Path

import pandas as pd


def export(folder, dataset, config, labels, result, manifest):
    folder = Path(folder)
    (folder / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2))
    (folder / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    assignments = dataset["units"].copy()
    assignments["territory_id"] = labels + 1
    assignments.to_csv(folder / "assignments.csv", index=False, encoding="utf-8-sig")
    rows = []
    for group in result["groups"]:
        row = {key: group[key] for key in ["territory_id", "street_connected", "road_connected", "span_km"]}
        for i, field in enumerate(["market", "customers", "visits"]):
            row[field] = group["totals"][i]
            row[field + "_index"] = group["indices"][i]
        rows.append(row)
    summary = pd.DataFrame(rows)
    summary.to_csv(folder / "territories.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(folder / "results.xlsx", engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="辖区指标", index=False)
        assignments.to_excel(writer, sheet_name="单元归属", index=False)
    features = json.loads(json.dumps(dataset["geometry"]))
    for i, feature in enumerate(features["features"]):
        feature["properties"]["unit_id"] = i
        feature["properties"]["territory_id"] = int(labels[i]) + 1
    (folder / "territories.geojson").write_text(json.dumps(features, ensure_ascii=False))
    # Render the supplied real boundaries; all rings retain even-odd hole semantics.
    paths = []
    for i, feature in enumerate(features["features"]):
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        rings = []
        for polygon in polygons:
            for ring in polygon:
                rings.append([(float(x), -float(y)) for x, y, *_ in ring])
        paths.append((i, rings))
    points = [point for _, rings in paths for ring in rings for point in ring]
    minx, maxx = min(p[0] for p in points), max(p[0] for p in points)
    miny, maxy = min(p[1] for p in points), max(p[1] for p in points)
    sx, sy = 650 / max(maxx-minx, 1e-9), 850 / max(maxy-miny, 1e-9)
    shapes = []
    for i, rings in paths:
        path = " ".join("M" + " L".join(f"{(x-minx)*sx+10:.2f},{(y-miny)*sy+10:.2f}" for x, y in ring) + " Z" for ring in rings)
        color = f"hsl({int(labels[i])*137%360},40%,58%)"
        name = html.escape(str(dataset["units"].iloc[i]["name"]))
        shapes.append(f'<path d="{path}" fill="{color}" fill-rule="evenodd" stroke="white" stroke-width=".5"><title>{name} · 组{labels[i]+1}</title></path>')
    table_rows = []
    for g in result["groups"]:
        cells = [f'<th style="border-left:8px solid hsl({(g["territory_id"]-1)*137%360},40%,58%)">组{g["territory_id"]}</th>']
        for j, value in enumerate(g["indices"]):
            bad = abs(value-100) > config["tolerance"][j]*100+1e-7
            cells.append(f'<td class="{"bad" if bad else ""}">{value:.1f}%</td>')
        cells.append(f'<td>{g["span_km"]:.3f}</td>' if g["span_km"] is not None else '<td class="bad">道路不通</td>')
        table_rows.append('<tr>'+''.join(cells)+'</tr>')
    status = "全部约束通过" if result["accepted"] else "存在未通过约束，不能作为合格方案"
    span = f'{result["maximum_span_km"]:.6f} km' if result["maximum_span_km"] is not None else "无法计算"
    content = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>辖区运行报告</title>
<style>body{{font:18px/1.6 system-ui;margin:0;padding:32px;background:#f4f3ed;color:#17364a}}main{{max-width:1300px;margin:auto}}h1{{font-family:serif}}.grid{{display:grid;grid-template-columns:minmax(250px,.8fr) 1.2fr;gap:25px}}svg{{width:100%;max-height:700px;background:white}}table{{width:100%;border-collapse:collapse;background:white}}th,td{{border:1px solid #ced6d8;padding:10px;text-align:left}}.bad{{color:#b3261e;background:#fce9e6}}.links{{display:flex;gap:16px;flex-wrap:wrap}}a{{color:#28647c}}@media(max-width:850px){{.grid{{display:block}}body{{padding:16px}}table{{font-size:15px}}}}</style><main>
<h1>{html.escape(config['name'])}</h1><p><strong>{status}</strong> · {config['hc']}组 · 最大组内道路跨度 {span}</p>
<p>平均100%；市场/客户/拜访容差：{', '.join(f'{v*100:g}%' for v in config['tolerance'])}。距离上限 {config['distance_cap_km']} km。</p>
<div class="grid"><svg viewBox="0 0 670 870" role="img" aria-label="本次真实单元分区">{''.join(shapes)}</svg><div><table><thead><tr><th>组</th><th>市场指数</th><th>客户指数</th><th>拜访指数</th><th>跨度/km</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table>
<p>仅表示本次约束验收结果；保留起点不算新增优化。当前报告不估算收益或工时。</p><div class="links"><a href="results.xlsx">Excel</a><a href="assignments.csv">归属CSV</a><a href="audit.json">独立验收</a><a href="manifest.json">运行来源</a><a href="territories.geojson">分区GeoJSON</a></div></div></div></main></html>'''
    (folder / "report.html").write_text(content)
