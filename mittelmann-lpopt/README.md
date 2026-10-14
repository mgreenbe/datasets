# Mittelmann LPopt source files

`plato/` contains the pinned compressed files from https://plato.asu.edu/ftp/lptestset/; `manifest.json` records each file's URL, size, and SHA-256 checksum. `mps/` contains 116 expanded MPS models, with hashes in `mps_manifest.json`. Run `python3 populate.py` from the datasets repository root to download and verify them, or add `--verify-only` to check existing files.

LPopt is a benchmark list, not a single packaged corpus. Its cases come from several hosts. The 16 undisclosed cases in the table cannot be downloaded. The Plato source directory includes additional instances and overlaps with MIPLIB; deduplicate before aggregating benchmark results. Files ending in `.mps.bz2` were directly decompressed. As the upstream `00README` explains, files without `mps` in the name use MPC compression; these were converted with Netlib's `emps.c` from `datasets/netlib/provenance/`. The source index and README do not state an explicit dataset license.

Both manifests list `rows`, `columns`, and `nonzeros` for each model. Counts follow the existing Netlib manifest convention: rows include the MPS `N` objective row, and nonzeros include objective coefficients but exclude RHS and bounds. The seven `00README` source files have no dimensions. Regenerate counts with `python3 datasets/add_mps_dimensions.py` from the repository root.
