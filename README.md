# Sparse optimization datasets

This repository tracks dataset manifests, provenance, the tools needed to
recreate the MPS files, and the generated Netlib simplex probes. The large
MPS model files are excluded from Git.
Initial-basis probe directories (`netlib-simplex-probes/*-0/`) are excluded
because they contain many redundant right-hand-side snapshots.

After cloning, run:

```sh
python3 populate.py
```

The command downloads the pinned Netlib LP, MIPLIB 2017, and Mittelmann LPopt
sources, verifies every source against its committed SHA-256 checksum, expands
them to MPS without changing integer restrictions, verifies every resulting
MPS against its committed checksum, and creates the four `nmm*` symlink views.
It is safe to run again; existing files are checked before reuse. A mismatch
stops the run instead of silently accepting new upstream content. To check a
populated clone without downloading or converting, run `python3 populate.py
--verify-only`.

Requirements: Python 3, a C compiler (`cc`), and `gfortran` for the three Netlib
instances generated from Fortran sources. Allow at least 50 GB of disk space
for the expanded corpus. The manifests record rows, columns, nonzeros, sizes,
and SHA-256 checksums. The converted MPS files retain source integer markers
and bounds; choose any LP relaxation in the reader or solver.
