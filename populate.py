#!/usr/bin/env python3
"""Populate all MPS corpora from immutable, checksum-pinned manifests."""

import argparse
import bz2
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

import build_nmm
import netlib_generator as netlib
from prepare_lp_corpora import expand_mpc

ROOT = Path(__file__).resolve().parent
CHUNK = 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")


def manifest(relative):
    return json.loads((ROOT / relative).read_text())


def validate_record(record, checksum="sha256", size="bytes"):
    if not SHA.fullmatch(record[checksum]) or not isinstance(record[size], int) or record[size] < 0:
        raise ValueError(f"Invalid checksum or size in manifest entry: {record}")


def digest(path):
    sha = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            sha.update(block)
            size += len(block)
    return size, sha.hexdigest()


def check(path, size, sha):
    actual_size, actual_sha = digest(path) if path.is_file() else (None, None)
    if actual_sha != sha or (size is not None and actual_size != size):
        raise ValueError(f"Missing or checksum-mismatched file: {path}")


def ensure(path, size, sha, producer, verify_only):
    if path.exists():
        check(path, size, sha)
        return
    if verify_only:
        raise FileNotFoundError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.unlink(missing_ok=True)
    try:
        producer(part)
        check(part, size, sha)
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)


def download(url, target):
    request = urllib.request.Request(url, headers={"User-Agent": "highsrs-datasets/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output, CHUNK)


def copy_decompressed(source, target, opener):
    with opener(source, "rb") as compressed, target.open("wb") as output:
        shutil.copyfileobj(compressed, output, CHUNK)


def netlib_corpus(verify_only):
    root = ROOT / "netlib"
    data = manifest("netlib/manifest.json")
    catalog = root / "provenance/netlib-readme.txt"
    emps_source = root / "provenance/emps.c"
    ensure(catalog, catalog.stat().st_size if catalog.exists() else None,
           data["catalog_sha256"], lambda p: download("https://www.netlib.org/lp/data/readme", p), verify_only)
    ensure(emps_source, emps_source.stat().st_size if emps_source.exists() else None,
           data["decompressor_sha256"], lambda p: download("https://www.netlib.org/lp/data/emps.c", p), verify_only)
    entries = data["problems"]
    for item in entries:
        validate_record(item, "mps_sha256", "mps_bytes")
        if not SHA.fullmatch(item["source_sha256"]):
            raise ValueError(f"Invalid Netlib source checksum: {item['name']}")
        for source in item.get("generator_sources") or []:
            validate_record(source)
    if verify_only:
        for item in entries:
            check(root / item["path"], item["mps_bytes"], item["mps_sha256"])
        return
    with tempfile.TemporaryDirectory(prefix="netlib-build-") as temp_name:
        temp = Path(temp_name)
        emps = temp / "emps"
        subprocess.run(["cc", "-O2", str(emps_source), "-o", str(emps)], check=True)
        generated = None
        for index, item in enumerate(entries, 1):
            path = root / item["path"]
            if path.exists():
                check(path, item["mps_bytes"], item["mps_sha256"])
                continue
            if item["generation"] is not None:
                if generated is None:
                    generated = netlib.generate_problems(temp, emps, root / "provenance")
                content, sources, _ = generated[item["name"]]
                if [(s["sha256"], s["bytes"]) for s in sources] != [
                    (s["sha256"], s["bytes"]) for s in item["generator_sources"]
                ]:
                    raise ValueError(f"Generator sources changed: {item['name']}")
                composite = hashlib.sha256(b"".join(bytes.fromhex(s["sha256"]) for s in sources)).hexdigest()
                if composite != item["source_sha256"] or sum(s["bytes"] for s in sources) != item["source_bytes"]:
                    raise ValueError(f"Generator source digest changed: {item['name']}")
            else:
                source = netlib.download(item["source_url"])
                if (len(source), netlib.sha256(source)) != (item["source_bytes"], item["source_sha256"]):
                    raise ValueError(f"Netlib source changed: {item['name']}")
                content = netlib.run([str(emps)], temp, input=source, capture_output=True).stdout
            if (len(content), netlib.sha256(content)) != (item["mps_bytes"], item["mps_sha256"]):
                raise ValueError(f"Netlib MPS mismatch: {item['name']}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"Netlib {index}/{len(entries)} {item['name']}", flush=True)


def miplib_corpus(verify_only):
    root = ROOT / "miplib2017"
    source = manifest("miplib2017/manifest.json")
    output = manifest("miplib2017/mps_manifest.json")
    archive = root / "benchmark.zip"
    for item in source["files"] + output["files"]:
        validate_record(item)
    source_by_path = {"miplib2017/" + x["path"]: x for x in source["files"]}
    if set(source_by_path) != {x["source_path"] for x in output["files"]}:
        raise ValueError("MIPLIB source/output manifest inventories differ")
    ensure(archive, source["archive_bytes"], source["archive_sha256"],
           lambda p: download(source["archive_url"], p), verify_only)
    with zipfile.ZipFile(archive) as zipped:
        expected = {Path(x["path"]).name for x in source["files"]}
        if set(zipped.namelist()) != expected:
            raise ValueError("MIPLIB archive inventory differs from manifest")
        for index, item in enumerate(source["files"], 1):
            path = root / item["path"]
            ensure(path, item["bytes"], item["sha256"],
                   lambda p, name=path.name: extract_member(zipped, name, p), verify_only)
            print(f"MIPLIB source {index}/{len(source['files'])} {path.name}", flush=True)
    for index, item in enumerate(output["files"], 1):
        path = ROOT / item["path"]
        compressed = ROOT / item["source_path"]
        ensure(path, item["bytes"], item["sha256"],
               lambda p, s=compressed: copy_decompressed(s, p, gzip.open), verify_only)
        print(f"MIPLIB MPS {index}/{len(output['files'])} {path.name}", flush=True)


def extract_member(zipped, name, target):
    with zipped.open(name) as member, target.open("wb") as output:
        shutil.copyfileobj(member, output, CHUNK)


def mittelmann_corpus(verify_only):
    root = ROOT / "mittelmann-lpopt"
    source = manifest("mittelmann-lpopt/manifest.json")
    output = manifest("mittelmann-lpopt/mps_manifest.json")
    for item in source["files"] + output["files"]:
        validate_record(item)
    expected = {"mittelmann-lpopt/" + x["path"] for x in source["files"] if x["path"].endswith(".bz2")}
    if expected != {x["source_path"] for x in output["files"]}:
        raise ValueError("Mittelmann source/output manifest inventories differ")
    for index, item in enumerate(source["files"], 1):
        path = root / item["path"]
        ensure(path, item["bytes"], item["sha256"],
               lambda p, url=item["source_url"]: download(url, p), verify_only)
        print(f"Mittelmann source {index}/{len(source['files'])} {path.name}", flush=True)
    needs_emps = any(not (ROOT / x["path"]).exists() and x["conversion"] == "EMPS after bzip2" for x in output["files"])
    with tempfile.TemporaryDirectory(prefix="emps-") as temp_name:
        emps = Path(temp_name) / "emps"
        if needs_emps and not verify_only:
            subprocess.run(["cc", "-O2", str(ROOT / "netlib/provenance/emps.c"), "-o", str(emps)], check=True)
        for index, item in enumerate(output["files"], 1):
            path = ROOT / item["path"]
            compressed = ROOT / item["source_path"]
            producer = (lambda p, s=compressed: expand_mpc(s, p, emps)) if item["conversion"] == "EMPS after bzip2" else (lambda p, s=compressed: copy_decompressed(s, p, bz2.open))
            ensure(path, item["bytes"], item["sha256"], producer, verify_only)
            print(f"Mittelmann MPS {index}/{len(output['files'])} {path.name}", flush=True)


def validate_views():
    canonical = {}
    net = manifest("netlib/manifest.json")
    for x in net["problems"]:
        canonical["netlib/" + x["path"]] = (x["mps_bytes"], x["mps_sha256"])
    for corpus in ("miplib2017", "mittelmann-lpopt"):
        for x in manifest(corpus + "/mps_manifest.json")["files"]:
            canonical[x["path"]] = (x["bytes"], x["sha256"])
    for view in ("nmm0-50k", "nmm50k-100k", "nmm100k-150k", "nmm150k-200k"):
        data = manifest(view + "/manifest.json")
        if len(data["instances"]) != data["instance_count"]:
            raise ValueError(f"Wrong instance count: {view}")
        for item in data["instances"]:
            validate_record(item, "sha256", "mps_bytes")
            if canonical[item["source_path"]] != (item["mps_bytes"], item["sha256"]):
                raise ValueError(f"View checksum differs from source: {item['path']}")
            for alternate in item["also_in"]:
                validate_record(alternate, "sha256", "mps_bytes")
                if canonical[alternate["source_path"]] != (alternate["mps_bytes"], alternate["sha256"]):
                    raise ValueError(f"Alternate checksum differs from source: {item['path']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Check existing files without downloading or converting")
    args = parser.parse_args()
    validate_views()
    netlib_corpus(args.verify_only)
    miplib_corpus(args.verify_only)
    mittelmann_corpus(args.verify_only)
    if args.verify_only:
        for view in ("nmm0-50k", "nmm50k-100k", "nmm100k-150k", "nmm150k-200k"):
            for item in manifest(view + "/manifest.json")["instances"]:
                check(ROOT / item["path"], item["mps_bytes"], item["sha256"])
    else:
        build_nmm.build()
    print("All dataset checksums verified.")


if __name__ == "__main__":
    main()
