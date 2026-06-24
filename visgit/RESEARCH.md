# visgit Research Notes

Research conducted 2026-06-24 for the agentic-astro workshop.

## The Data Explosion Problem

### Typical CASA Pipeline Data Flow

A standard radio interferometry calibration pipeline:

1. **Import** — raw correlator data → MS (DATA column)
2. **Flag** — RFI excision → modifies FLAG, FLAG_ROW
3. **Initial cal** — bandpass + gain → writes CORRECTED_DATA
4. **Self-cal round 1** — image + solve → updates MODEL_DATA, CORRECTED_DATA
5. **Self-cal round 2** — repeat with shorter solution interval
6. **Final split** — extract calibrated data for imaging

At each step, tools typically copy the entire MS. For a MeerKAT L-band
observation (~1 TB), this creates 3–6 TB of near-identical copies.

### What Actually Changes

| Step | Columns modified | Columns unchanged |
|------|-----------------|-------------------|
| Flag | FLAG, FLAG_ROW | DATA, UVW, TIME, ANTENNA1/2, all metadata |
| Calibrate | CORRECTED_DATA, WEIGHT_SPECTRUM | DATA, UVW, TIME, FLAG, all metadata |
| Self-cal | MODEL_DATA, CORRECTED_DATA | DATA, UVW, TIME, ANTENNA1/2 |
| Image | (produces FITS, not MS changes) | Everything |

Typically **<20% of the data changes** at each step, yet **100% is duplicated**.

## Tool Landscape

### Icechunk (Earthmover) — Best Fit

- **PyPI**: `icechunk`
- **What**: Zarr-native transactional version control
- **Model**: Git-like — branches, tags, snapshots, commits at the Zarr level
- **Dedup**: Chunk-level content-addressed storage. Unchanged chunks shared
  across snapshots.
- **Integration**: Drop-in `zarr.abc.store.Store` — works with xarray directly
- **Transactions**: ACID — safe for concurrent writers
- **Time travel**: Read any past snapshot
- **Virtual ingest**: Existing Zarr data can be versioned without rewriting
- **Status**: v2.0 released April 2026, production use at NWS
- **Managed option**: Arraylake (Earthmover's platform) adds web UI, auth

### Lore (Epic Games)

- **Open-sourced**: 2026-06-17, MIT, Rust
- **What**: Centralized VCS for large binary assets (game textures, meshes)
- **Chunking**: Content-defined chunking (FastCDC, ~64KB, BLAKE3 hashes)
- **Dedup**: Yes, at byte-chunk level
- **Python SDK**: Available
- **Fit for radio astro**: Poor — no awareness of array dimensions, columns, or
  Zarr. Chunks raw bytes, not semantic data. Designed for game asset pipelines.
- **Could work as**: A low-level storage backend, but Icechunk is purpose-built
  for the array/Zarr use case.

### LakeFS

- **What**: Git-like branching for object stores (S3, GCS, Azure)
- **Granularity**: Object/file level
- **Zarr**: Since Zarr stores each chunk as a separate object, LakeFS gets
  implicit chunk-level dedup when branching — unchanged chunk objects are shared.
- **Column awareness**: None — it just versions object keys
- **Fit**: Decent but requires object store infrastructure. More ops overhead
  than Icechunk for single-machine use.

### TileDB

- **What**: Versioned array storage engine
- **Time travel**: Yes — every write creates a timestamped fragment
- **Column awareness**: Yes — can read/write specific attributes
- **Fit**: Good on paper, but it's its own storage format. Not Zarr-compatible,
  so doesn't integrate with the xarray-ms / MSv4 / Zarr ecosystem without
  conversion.

### DVC (Data Version Control)

- **What**: Git extension for ML data pipelines
- **Granularity**: Whole file only
- **Fit**: Poor for radio astronomy — a 50GB MS where you change one column
  still stores a full new copy.

### Comparison

| Tool | Granularity | Zarr-native | Column-aware | Radio astro fit |
|------|------------|-------------|--------------|-----------------|
| Icechunk | Zarr chunk | Yes | Yes | Perfect |
| Lore | 64KB byte chunks | No | No | Poor |
| LakeFS | Object/file | Implicit | No | Decent |
| TileDB | Fragment/cell | No (own format) | Yes | Good but non-Zarr |
| DVC | Whole file | No | No | Poor |

## Prior Art in Radio Astronomy

### Minimal Re-computation (2018)

"Minimal Re-computation for Exploratory Data Analysis in Astronomy"
([arXiv:1809.01945](https://arxiv.org/abs/1809.01945), Astronomy and Computing)

- Memoization to avoid redundant pipeline reruns when tweaking calibration
  parameters — tackles wasteful duplication from the computation side
- Related but different angle: that paper minimizes re-computation, visgit
  minimizes re-storage

### dask-ms (RATT)

- Experimental Zarr and Parquet backends for MS data
- Supports writing selected columns back (`xds_to_table` with column selection)
- Avoids full-MS copies at the I/O level
- But no snapshot/history/versioning mechanism

### xarray-ms (RATT)

- Presents lazy MSv4 view over MSv2 tables
- No versioning story
- But provides the xarray DataTree structure we need for Icechunk

### MSv4 / XRADIO

- MSv4 spec stores data as Zarr — each array/column is independently addressable
- This is structurally ideal for column-level versioning
- XRADIO is the reference implementation
- The missing piece was versioning — Icechunk fills that gap

## Proposed Architecture

### Layer 1: Ingest

```python
import xarray as xr
from icechunk import IcechunkStore, StorageConfig

# Open MS as MSv4 DataTree
tree = xr.open_datatree("observation.ms", engine="xarray-ms")

# Create versioned Zarr store
storage = StorageConfig.filesystem("./observation.visgit")
store = IcechunkStore.create(storage)

# Write to Icechunk
tree.to_zarr(store)
store.commit("Initial ingest from observation.ms")
```

### Layer 2: Pipeline Steps

```python
# Open existing versioned store
store = IcechunkStore.open_existing(storage)

# Read, modify flags
ds = xr.open_zarr(store, group="/spw0")
new_flags = run_aoflagger(ds)
ds["FLAG"] = new_flags
ds.to_zarr(store, group="/spw0", mode="a")

# Commit only the changed chunks
store.commit("Apply AOFlagger RFI flags")
```

### Layer 3: Branching

```python
# Try experimental calibration
store.new_branch("experimental-selfcal")
store.checkout("experimental-selfcal")

# ... run calibration ...
store.commit("Self-cal with 30s solution interval")

# Compare with main
store.checkout("main")
# ... run different calibration ...
store.commit("Self-cal with 60s solution interval")

# Diff the two branches
# (custom code to compare FLAG/CORRECTED_DATA chunks)
```

## Key Design Decisions

1. **Icechunk as the engine** — it's purpose-built for versioned Zarr, handles
   chunk-level dedup, and drops into the xarray ecosystem.

2. **MSv4 as the data model** — xarray-ms gives us MSv4 DataTrees from MSv2
   tables, and MSv4's Zarr structure is naturally versionable.

3. **Column-level awareness** — visgit's diff/log commands understand which
   MSv4 variables (DATA, FLAG, CORRECTED_DATA, etc.) changed between snapshots.

4. **CLI wraps pipeline tools** — `visgit run` snapshots before/after running
   CASA or other tools, like `git stash` but for calibration steps.

## Open Questions

1. **Chunk sizing** — MSv4 chunks by time×baseline×channel×pol. What chunk
   shape optimizes dedup across calibration steps? (Flagging is sparse;
   calibration changes everything within a solution interval.)

2. **Write-back to MS** — should visgit be able to export a snapshot back to
   a Casacore MS? Needed for tools that only speak MSv2.

3. **Integration with CASA** — CASA writes to MS directly. Can we intercept
   writes (via visfuse?) or do we need a wrapper that copies before/after?

4. **Object store backend** — Icechunk supports S3/GCS. For HPC clusters,
   is local filesystem or object store better?

5. **Merge semantics** — what does it mean to merge FLAG columns from two
   branches? Union of flags? Intersection? User-defined?

6. **Relation to visfuse** — visfuse presents MS as Zarr (read-only). visgit
   stores versioned Zarr. Could visfuse be the "ingest" layer for visgit?
