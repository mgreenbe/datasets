# MIPLIB 2017 benchmark set

Downloaded from https://miplib.zib.de/download.html on 2026-10-13. `benchmark.zip` is the official version 2 benchmark archive; `instances/` contains its 240 original gzip-compressed MPS members. `mps/` contains their decompressed MPS files. `manifest.json` records archive and source-file checksums; `mps_manifest.json` records output checksums. Run `python3 populate.py --verify-only` from the datasets repository root to verify all files.

These are mixed-integer models. Their MPS integer markers and bounds are preserved unchanged. Any LP relaxation must be performed by the reader or solver at runtime. The MIP solution values published by MIPLIB are not LP-relaxation reference objectives. Consult the MIPLIB website and each instance's provenance before redistribution.

Both manifests list `rows`, `columns`, and `nonzeros` for each model. Counts follow the existing Netlib manifest convention: rows include the MPS `N` objective row, and nonzeros include objective coefficients but exclude RHS and bounds. Regenerate them with `python3 datasets/add_mps_dimensions.py` from the repository root.
