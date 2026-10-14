# Netlib LP corpus

This shared corpus is generated from the official Netlib LP collection by `../populate.py`. It contains expanded MPS files, original generator provenance, per-source and per-MPS SHA-256 checksums, catalog metadata, and mechanically derived subsets.

All distributed models are minimization problems. Netlib states no explicit dataset license; consult `provenance/netlib-readme.txt` and each manifest entry before redistribution. Regeneration requires a C compiler and `gfortran`; the exact generator compiler is recorded in `manifest.json`.
