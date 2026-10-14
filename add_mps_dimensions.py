#!/usr/bin/env python3
"""Add structural MPS dimensions to source and expanded-file manifests."""

import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent


def update(corpus, counter):
    root = ROOT / corpus
    source_path = root / "manifest.json"
    output_path = root / "mps_manifest.json"
    source = json.loads(source_path.read_text())
    output = json.loads(output_path.read_text())
    source_by_path = {str(Path(corpus) / item["path"]): item for item in source["files"]}
    for index, item in enumerate(output["files"], 1):
        result = subprocess.run([str(counter), str(ROOT / item["path"])],
                                check=True, capture_output=True, text=True)
        rows, columns, nonzeros = map(int, result.stdout.split())
        dimensions = {"rows": rows, "columns": columns, "nonzeros": nonzeros}
        for key, value in dimensions.items():
            if key in item and item[key] != value:
                raise ValueError(f"Changed {key} for {item['path']}")
        item.update(dimensions)
        source_item = source_by_path[item["source_path"]]
        for key, value in dimensions.items():
            if key in source_item and source_item[key] != value:
                raise ValueError(f"Changed source {key} for {item['source_path']}")
        source_item.update(dimensions)
        print(f"{corpus} {index}/{len(output['files'])} {Path(item['path']).name}: "
              f"{rows} x {columns}, {nonzeros} nonzeros", flush=True)
    source["matrix_dimensions"] = "MPS ROWS-section rows include N (objective/free) rows; columns are COLUMNS-section variables; nonzeros count nonzero COLUMNS-section coefficient entries, including objective rows but excluding RHS and bounds. This matches the existing Netlib manifest convention."
    output["matrix_dimensions"] = source["matrix_dimensions"]
    source_path.write_text(json.dumps(source, indent=2) + "\n")
    output_path.write_text(json.dumps(output, indent=2) + "\n")


def main():
    with tempfile.TemporaryDirectory(prefix="mps-count-") as directory:
        counter = Path(directory) / "count_mps_matrix"
        subprocess.run(["c++", "-O2", "-std=c++20", str(ROOT / "count_mps_matrix.cpp"),
                        "-o", str(counter)], check=True)
        for corpus in ("miplib2017", "mittelmann-lpopt"):
            update(corpus, counter)


if __name__ == "__main__":
    main()
