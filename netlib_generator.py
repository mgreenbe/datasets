#!/usr/bin/env python3
"""Helpers for byte-identical generation of the official Netlib LP MPS files."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import date
from pathlib import Path

BASE_URL = "https://www.netlib.org/lp/data"
QAP_URL = "https://www.netlib.org/lp/generators/qap"
DATASET_ROOT = Path(__file__).resolve().parent / "netlib"
TABLE_ROW = re.compile(
    r"^(?P<name>[A-Z0-9.-]+)\s+(?P<rows>\d+)\s+(?P<columns>\d+)\s+"
    r"(?P<nonzeros>\d+)\s+(?P<bytes>\d+|\(see NOTES\))(?P<remainder>.*)$"
)
NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[DEde][+-]?\d+)?$")
EMPTY_RHS = {"bore3d", "cycle", "greenbea", "greenbeb", "kb2", "recipe", "tuff"}
EXTRA_RHS_REMOVED = {"beaconfd", "brandy", "fffff800", "israel"}
EXTRA_BOUNDS_REMOVED = {"greenbea", "greenbeb", "grow15", "grow22", "grow7", "recipe"}
EXTRA_FREE_ROWS_REMOVED = {
    "80bau3b", "boeing1", "bore3d", "e226", "fffff800", "finnis",
    "forplan", "ganges", "greenbea", "greenbeb", "maros", "pilot",
    "pilot87", "recipe", "sctap1", "sctap2", "sctap3", "share2b",
    "ship04l", "ship04s", "ship08l", "ship08s", "ship12l", "ship12s",
}
EXPLICIT_ZEROS_REMOVED = {
    "grow15", "grow22", "grow7", "nesm", "scorpion", "scrs8", "seba",
    "sierra", "stair",
}
NEGATED_OBJECTIVE = {
    "boeing1", "boeing2", "degen2", "degen3", "etamacro", "fit1d",
    "fit2d", "ganges", "grow15", "grow22", "grow7", "lotfi", "maros",
    "pilot", "pilot.ja", "pilot.we", "pilotnov", "sc105", "sc50a",
    "sc50b", "stair",
}


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "gloprs-netlib/0.1"})
    with urllib.request.urlopen(request) as response:
        return response.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_catalog(catalog: str) -> list[dict[str, object]]:
    problems: list[dict[str, object]] = []
    in_table = False
    for line in catalog.splitlines():
        if line.strip() == "PROBLEM SUMMARY TABLE":
            in_table = True
            continue
        if in_table and line.strip() == "BOUND-TYPE TABLE":
            break
        if not in_table:
            continue
        match = TABLE_ROW.match(line.strip())
        if match is None:
            continue
        remainder = match["remainder"].strip()
        flags = ""
        if remainder.startswith("BR"):
            flags, remainder = "BR", remainder[2:].strip()
        elif remainder.startswith(("B", "R")):
            flags, remainder = remainder[0], remainder[1:].strip()
        objective_text = remainder.removesuffix("**").strip()
        objective = None if not objective_text or objective_text == "(see NOTES)" else float(objective_text)
        byte_text = match["bytes"]
        problems.append(
            {
                "name": match["name"].lower(),
                "rows": int(match["rows"]),
                "columns": int(match["columns"]),
                "nonzeros": int(match["nonzeros"]),
                "catalog_compressed_bytes": None if byte_text == "(see NOTES)" else int(byte_text),
                "has_bounds": "B" in flags,
                "has_ranges": "R" in flags,
                "objective_sense": "minimize",
                "published_status": "optimal" if objective is not None else "not_reported",
                "known_optimal_objective": objective,
            }
        )
    if not problems:
        raise RuntimeError("No Netlib problems found in the official catalog")
    return problems


def write_new_or_verify(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"refusing to replace changed dataset file: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def extract_shar(bundle: bytes, destination: Path) -> None:
    """Extract Netlib's historical shell archive without executing it."""
    lines = bundle.decode("ascii").splitlines(keepends=True)
    start = re.compile(r"^sed >([^ ]+) <<'([^']+)' 's/\^-//'$")
    position = 0
    while position < len(lines):
        match = start.match(lines[position].rstrip("\n"))
        if match is None:
            position += 1
            continue
        filename, marker = match.groups()
        if Path(filename).name != filename:
            raise RuntimeError(f"unsafe filename in Netlib bundle: {filename}")
        position += 1
        content: list[str] = []
        while position < len(lines) and lines[position].rstrip("\n") != marker:
            line = lines[position]
            content.append(line[1:] if line.startswith("-") else line)
            position += 1
        if position == len(lines):
            raise RuntimeError(f"unterminated file in Netlib bundle: {filename}")
        (destination / filename).write_text("".join(content), encoding="ascii")
        position += 1


def run(command: list[str], cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, cwd=cwd, check=True, **kwargs)  # type: ignore[arg-type]


def generate_problems(
    temporary: Path, emps: Path, provenance: Path
) -> dict[str, tuple[bytes, list[dict[str, object]], str]]:
    generated: dict[str, tuple[bytes, list[dict[str, object]], str]] = {}
    qap = temporary / "qap"
    qap.mkdir()
    qap_sources = []
    for filename in ("newlp.f", "data.8", "data.12", "data.15"):
        url = f"{QAP_URL}/{filename}"
        data = download(url)
        write_new_or_verify(provenance / "qap" / filename, data)
        (qap / filename).write_bytes(data)
        qap_sources.append({"url": url, "sha256": sha256(data), "bytes": len(data)})
    run(["gfortran", "-std=legacy", "-O2", "newlp.f", "-o", "qapgen"], qap)
    for size in (8, 12, 15):
        result = run(
            [str(qap / "qapgen")], qap,
            input=(qap / f"data.{size}").read_bytes(), capture_output=True,
        )
        generated[f"qap{size}"] = (
            result.stdout, qap_sources,
            f"Generated by official Terri Johnson newlp.f using data.{size}",
        )

    for name in ("truss", "stocfor3"):
        url = f"{BASE_URL}/{name}"
        bundle = download(url)
        write_new_or_verify(provenance / f"{name}.shar", bundle)
        source = [{"url": url, "sha256": sha256(bundle), "bytes": len(bundle)}]
        directory = temporary / name
        directory.mkdir()
        extract_shar(bundle, directory)
        if name == "truss":
            run(["gfortran", "-std=legacy", "-O2", "truss.f", "-o", "trussgen"], directory)
            run([str(directory / "trussgen")], directory, capture_output=True)
            generated[name] = (
                (directory / "mps").read_bytes(), source,
                "Generated by official Michael Ferris truss.f and bundled data",
            )
            continue

        expanded_core = run(
            [str(emps)], directory, input=(directory / "core.mpc").read_bytes(), capture_output=True,
        ).stdout
        (directory / "core.mps").write_bytes(expanded_core)
        for filename in ("std2mps.f", "input.f"):
            path = directory / filename
            source_text = path.read_text(encoding="ascii")
            path.write_text(source_text.replace("IABS(", "ABS("), encoding="ascii")
        run(
            ["gfortran", "-std=legacy", "-fallow-argument-mismatch", "-O2",
             "std2mps.f", "input.f", "-o", "stocgen"],
            directory,
        )
        shutil.copyfile(directory / "time7.frs", directory / "fort.1")
        shutil.copyfile(directory / "core.mps", directory / "fort.2")
        shutil.copyfile(directory / "stoch3.frs", directory / "fort.3")
        run([str(directory / "stocgen")], directory, capture_output=True)
        mps = b"".join((directory / f"fort.{unit}").read_bytes() for unit in range(11, 16))
        generated[name] = (
            mps, source,
            "Generated by official Gassmann sources and stoch3 data; IABS calls "
            "changed to generic ABS for modern gfortran integer-kind checking",
        )
    return generated


