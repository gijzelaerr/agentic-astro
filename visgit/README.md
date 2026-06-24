# visgit

Git for visibilities — version-controlled radio astronomy data pipelines.

## The Problem

A typical CASA calibration pipeline creates 3–6 full copies of a Measurement
Set. A 1 TB MeerKAT L-band observation spawns ~5 TB of near-identical data:

```
raw.ms  →  flagged.ms  →  cal_round1.ms  →  cal_round2.ms  →  selfcal.ms  →  final.ms
  1 TB        1 TB            1 TB              1 TB             1 TB           1 TB
```

Each copy duplicates ALL columns — even UVW, ANTENNA1, TIME, etc. that never
change. Only FLAG, CORRECTED_DATA, MODEL_DATA, and WEIGHT_SPECTRUM are modified.

## The Solution

Use **Icechunk** (Zarr-native version control) to store only what changed:

```
Snapshot 0 (raw)        Snapshot 1 (flagged)     Snapshot 2 (calibrated)
┌─────────────┐         ┌─────────────┐          ┌─────────────┐
DATA   [A B C] ─shared─▶ [A B C] ────shared────▶ [A B C]
UVW    [D E F] ─shared─▶ [D E F] ────shared────▶ [D E F]
FLAG   [G H I]           [G' H' I'] ──shared───▶ [G' H' I']
CORR   (none)            (none)                   [J K L]  ← new
└─────────────┘         └─────────────┘          └─────────────┘
Total: ~1 TB             + ~50 GB                 + ~200 GB
```

5 calibration steps: **~1.5 TB instead of ~5 TB**. Branch, diff, time-travel,
and merge — just like git, but for terabyte-scale visibility data.

## Architecture

```
Casacore MS  →  xarray-ms/arcae  →  MSv4 xarray  →  Zarr  →  Icechunk
  (on disk)       (lazy read)        (DataTree)     (chunks)   (versioned)
```

1. **Ingest**: Read MS via xarray-ms, write to Icechunk-backed Zarr store
2. **Snapshot**: Each pipeline step (flag, calibrate, image) creates a commit
3. **Branch**: Try different calibration strategies on branches
4. **Diff**: Compare FLAG columns between snapshots
5. **Merge**: Cherry-pick the best flags from different branches

## Quick Start

```bash
pip install -e .

# Ingest an MS into a versioned store
visgit ingest observation.ms --store ./observation.visgit

# Run a calibration step, auto-snapshot
visgit run --store ./observation.visgit -- casa -c cal_script.py

# Browse history
visgit log --store ./observation.visgit

# Compare flags between two snapshots
visgit diff --store ./observation.visgit main~1 main --columns FLAG

# Branch for experimental calibration
visgit branch --store ./observation.visgit experimental
visgit checkout --store ./observation.visgit experimental
```

## Key Concepts

### Snapshots = Commits

Every pipeline step that modifies data creates an Icechunk snapshot (commit).
Only the modified Zarr chunks are written — unchanged data is shared with the
parent snapshot via content-addressed storage.

### Branches = Calibration Strategies

Try self-cal with different solution intervals on separate branches. Compare
results. Merge the winner.

### Diff = Column-Aware Comparison

`visgit diff` knows about MSv4 structure — it can show which columns changed,
how many chunks differ, and (for FLAG columns) how many visibilities were
affected.

## Components

| Module | What |
|--------|------|
| `visgit.ingest` | MS → Icechunk-backed Zarr via xarray-ms |
| `visgit.store` | Icechunk store management (init, open, snapshot) |
| `visgit.diff` | Column-aware diffing between snapshots |
| `visgit.cli` | Command-line interface |

## Dependencies

- `icechunk` — Zarr-native version control (the core)
- `arcae` — fast casacore table access
- `xarray-ms` — MSv4 view over MSv2 tables
- `xarray` + `dask` — lazy array computation
- `zarr >= 3` — Zarr v3 store API

## Prior Art

- **arXiv:1809.01945** — "Minimal Re-computation for Exploratory Data Analysis
  in Astronomy": memoization for calibration pipelines. Related problem
  (wasteful duplication), different angle (computation vs storage).
- **Icechunk** (Earthmover) — Zarr-native transactional version control with
  chunk-level dedup. The engine under visgit.
- **MSv4 / XRADIO** — next-gen MS spec mapping visibility data to xarray/Zarr.
  Gives us the Zarr-compatible structure to version.

## Status

Concept / workshop prototype.
