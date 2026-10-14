#!/usr/bin/env python3
"""Verify downloaded LP corpora and expand them to unchanged MPS models."""

import argparse
import bz2
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
CHUNK = 1024 * 1024


def digest_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def assert_record(path, record):
    size, digest = digest_file(path)
    if size != record["bytes"] or digest != record["sha256"]:
        raise ValueError(f"checksum or size mismatch: {path}")


def verify_sources():
    mip_root = ROOT / "miplib2017"
    mip = json.loads((mip_root / "manifest.json").read_text())
    archive = mip_root / "benchmark.zip"
    if digest_file(archive) != (mip["archive_bytes"], mip["archive_sha256"]):
        raise ValueError("MIPLIB archive checksum or size mismatch")
    expected = {item["path"].removeprefix("instances/") for item in mip["files"]}
    with zipfile.ZipFile(archive) as zipped:
        if set(zipped.namelist()) != expected:
            raise ValueError("MIPLIB ZIP inventory does not match manifest")
        for item in mip["files"]:
            path = mip_root / item["path"]
            assert_record(path, item)
            digest = hashlib.sha256()
            size = 0
            with zipped.open(path.name) as member:
                while chunk := member.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
            if (size, digest.hexdigest()) != (item["bytes"], item["sha256"]):
                raise ValueError(f"MIPLIB ZIP member differs from extracted file: {path.name}")
    print(f"Verified MIPLIB archive and {len(mip['files'])} members", flush=True)

    plato_root = ROOT / "mittelmann-lpopt"
    plato = json.loads((plato_root / "manifest.json").read_text())
    for item in plato["files"]:
        assert_record(plato_root / item["path"], item)
    print(f"Verified {len(plato['files'])} Plato source files", flush=True)
    return mip, plato


def copy_stream(source, target):
    with target.open("wb") as output:
        shutil.copyfileobj(source, output, CHUNK)


def expand_mpc(source, target, emps):
    with bz2.open(source, "rb") as compressed, target.open("wb") as output:
        process = subprocess.Popen([str(emps)], stdin=subprocess.PIPE, stdout=output)
        try:
            while chunk := compressed.read(CHUNK):
                process.stdin.write(chunk)
            process.stdin.close()
            if process.wait() != 0:
                raise ValueError(f"EMPS failed for {source}")
        except BaseException:
            process.kill()
            process.wait()
            raise


def expand_one(source, target, kind, emps, previous):
    if target.exists():
        if previous is None:
            raise FileExistsError(f"Untracked output exists: {target}")
        assert_record(target, previous)
        return previous
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".part")
    if temp.exists():
        temp.unlink()
    try:
        if kind == "gzip":
            with gzip.open(source, "rb") as stream:
                copy_stream(stream, temp)
        elif kind == "bzip2":
            with bz2.open(source, "rb") as stream:
                copy_stream(stream, temp)
        else:
            expand_mpc(source, temp, emps)
        with temp.open("rb") as stream:
            opening = stream.read(4096).splitlines()
            first_model_line = next((line.lstrip() for line in opening
                                     if line.strip() and not line.startswith(b"*")), b"")
            if not first_model_line.startswith(b"NAME"):
                raise ValueError(f"Expanded output is not MPS: {source}")
        size, digest = digest_file(temp)
        temp.replace(target)
        return {"path": str(target.relative_to(ROOT)), "bytes": size, "sha256": digest,
                "format": "MPS", "source_path": str(source.relative_to(ROOT)),
                "conversion": "EMPS after bzip2" if kind == "mpc" else kind + " decompression"}
    finally:
        temp.unlink(missing_ok=True)


def convert(corpus, sources, emps):
    root = ROOT / corpus
    manifest_path = root / "mps_manifest.json"
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": []}
    old_files = {item["path"]: item for item in old["files"]}
    results = dict(old_files)
    for index, item in enumerate(sources, 1):
        source = root / item["path"]
        if source.suffix not in (".gz", ".bz2"):
            continue
        if corpus == "miplib2017":
            rel = Path(source.name.removesuffix(".gz"))
            kind = "gzip"
        else:
            rel = Path(item["path"]).relative_to("plato")
            kind = "bzip2" if rel.name.endswith(".mps.bz2") else "mpc"
            rel = Path(str(rel).removesuffix(".bz2"))
            if kind == "mpc":
                rel = Path(str(rel) + ".mps")
        target = root / "mps" / rel
        key = str(target.relative_to(ROOT))
        result = expand_one(source, target, kind, emps, old_files.get(key))
        results[key] = result
        manifest_path.write_text(json.dumps({
            "dataset": corpus, "source_manifest": "manifest.json",
            "integer_restrictions": "Preserved as represented in source MPS; no LP relaxation",
            "files": [results[name] for name in sorted(results)],
        }, indent=2) + "\n")
        print(f"{corpus} {index}/{len(sources)} {rel}", flush=True)


def verify_outputs():
    for corpus in ("miplib2017", "mittelmann-lpopt"):
        root = ROOT / corpus
        manifest = json.loads((root / "mps_manifest.json").read_text())
        expected = 240 if corpus == "miplib2017" else 116
        if len(manifest["files"]) != expected:
            raise ValueError(f"Incomplete {corpus} output manifest")
        for item in manifest["files"]:
            target = ROOT / item["path"]
            assert_record(target, item)
            if item["conversion"] in ("gzip decompression", "bzip2 decompression"):
                source = ROOT / item["source_path"]
                opener = gzip.open if item["conversion"].startswith("gzip") else bz2.open
                digest = hashlib.sha256()
                size = 0
                with opener(source, "rb") as stream:
                    while chunk := stream.read(CHUNK):
                        digest.update(chunk)
                        size += len(chunk)
                if (size, digest.hexdigest()) != (item["bytes"], item["sha256"]):
                    raise ValueError(f"Expanded output differs from compressed source: {target}")
        print(f"Verified {expected} {corpus} MPS outputs", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--verify-outputs", action="store_true")
    args = parser.parse_args()
    mip, plato = verify_sources()
    if args.verify_only:
        return
    if args.verify_outputs:
        verify_outputs()
        return
    with tempfile.TemporaryDirectory(prefix="emps-") as directory:
        emps = Path(directory) / "emps"
        subprocess.run(["cc", "-O2", str(ROOT / "netlib/provenance/emps.c"),
                        "-o", str(emps)], check=True)
        convert("miplib2017", mip["files"], emps)
        convert("mittelmann-lpopt", plato["files"], emps)


if __name__ == "__main__":
    main()
