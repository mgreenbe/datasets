#!/usr/bin/env python3
"""Build deduplicated, size-binned views of the three local MPS corpora."""

import hashlib
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CORPORA = ("netlib", "miplib2017", "mittelmann-lpopt")
BINS = ((0, 50_000), (50_000, 100_000), (100_000, 150_000), (150_000, 200_000))


def sources():
    netlib = json.loads((ROOT / "netlib/manifest.json").read_text())
    for item in netlib["problems"]:
        yield {
            "name": item["name"], "corpus": "netlib",
            "source_path": "netlib/" + item["path"],
            "source_manifest": "netlib/manifest.json",
            "rows": item["rows"], "columns": item["columns"],
            "nonzeros": item["nonzeros"], "mps_bytes": item["mps_bytes"],
            "sha256": item["mps_sha256"], "source_url": item["source_url"],
            "published_status": item.get("published_status"),
            "known_optimal_objective": item.get("known_optimal_objective"),
        }
    for corpus in CORPORA[1:]:
        manifest = json.loads((ROOT / corpus / "mps_manifest.json").read_text())
        for item in manifest["files"]:
            yield {
                "name": Path(item["path"]).stem, "corpus": corpus,
                "source_path": item["path"],
                "source_manifest": f"{corpus}/mps_manifest.json",
                "rows": item["rows"], "columns": item["columns"],
                "nonzeros": item["nonzeros"], "mps_bytes": item["bytes"],
                "sha256": item["sha256"], "source_path_original": item["source_path"],
                "conversion": item["conversion"],
            }


def checked_file(item):
    path = ROOT / item["source_path"]
    if not path.is_file() or path.stat().st_size != item["mps_bytes"]:
        raise ValueError(f"Missing or changed MPS file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != item["sha256"]:
        raise ValueError(f"SHA-256 mismatch: {path}")


def build():
    selected = [item for item in sources() if 0 <= item["nonzeros"] < 200_000]
    # Prefer Netlib, then MIPLIB, then Mittelmann. Exact-content duplicates
    # also collapse when they have different names; named cross-corpus overlaps
    # collapse only when their recorded structural dimensions all agree.
    by_hash = {}
    by_name_shape = {}
    unique = []
    for item in selected:
        checked_file(item)
        name_shape = (item["name"].casefold(), item["rows"], item["columns"], item["nonzeros"])
        original = by_hash.get(item["sha256"]) or by_name_shape.get(name_shape)
        if original is None:
            original = dict(item)
            original["also_in"] = []
            unique.append(original)
        else:
            original["also_in"].append(item)
        by_hash[item["sha256"]] = original
        by_name_shape[name_shape] = original

    for lower, upper in BINS:
        label = f"nmm{lower // 1000}k-{upper // 1000}k" if lower else "nmm0-50k"
        directory = ROOT / label
        directory.mkdir(exist_ok=True)
        entries = []
        for item in sorted(unique, key=lambda value: (value["nonzeros"], value["name"].casefold())):
            if not lower <= item["nonzeros"] < upper:
                continue
            link = directory / "mps" / item["corpus"] / (item["name"] + ".mps")
            link.parent.mkdir(parents=True, exist_ok=True)
            target = os.path.relpath(ROOT / item["source_path"], link.parent)
            if link.is_symlink():
                if os.readlink(link) != target:
                    raise ValueError(f"Unexpected symlink target: {link}")
            elif link.exists():
                raise FileExistsError(link)
            else:
                link.symlink_to(target)
            entry = dict(item)
            entry["path"] = str(link.relative_to(ROOT))
            entries.append(entry)
        manifest = {
            "dataset": label,
            "description": "Deduplicated Netlib LP, MIPLIB 2017, and Mittelmann LPopt MPS instances",
            "nonzeros_range": {"min_inclusive": lower, "max_exclusive": upper},
            "matrix_dimensions": "Source-manifest convention: ROWS-section rows include objective/free rows; nonzeros count nonzero COLUMNS-section coefficients, including objective rows, excluding RHS and bounds.",
            "deduplication": "Prefer Netlib, then MIPLIB, then Mittelmann. Collapse identical SHA-256 MPS files, or case-insensitive equal names with equal recorded rows, columns, and nonzeros. The latter is a structural/name heuristic, not a proof of identical coefficients or bounds; alternate source metadata is in also_in.",
            "storage": "MPS paths are relative symlinks to existing source-corpus files; no MPS bytes are copied.",
            "instance_count": len(entries),
            "instances": entries,
        }
        manifest_path = directory / "manifest.json"
        serialized = json.dumps(manifest, indent=2) + "\n"
        if manifest_path.exists():
            if manifest_path.read_text() != serialized:
                raise ValueError(f"Committed view manifest differs from source manifests: {manifest_path}")
        else:
            manifest_path.write_text(serialized)
        print(f"{label}: {len(entries)} unique instances")


if __name__ == "__main__":
    build()
