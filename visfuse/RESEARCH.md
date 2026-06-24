# visfuse Research Notes

Research conducted 2026-06-24 for the agentic-astro workshop.

## Core Idea

Build a dynamic filesystem that on-the-fly converts Casacore Measurement Sets
(MSv2) into Zarr stores, so any tool that reads Zarr/xarray can transparently
access radio interferometry data.

## Component Analysis

### arcae

- **PyPI**: `arcae`
- **Repo**: github.com/ratt-ru/arcae
- **What**: Arrow C++ and Python bindings for casacore tables
- **Why it matters**: Provides fast, thread-safe access to CASA tables — fixes
  python-casacore's threading/GIL limitations
- **Status**: Actively maintained (last updated May 2026)
- **macOS**: Bundles its own casacore — no separate casacore install needed
- **API**: Limited subset of python-casacore focused on Arrow/Zarr export

### xarray-ms

- **PyPI**: `xarray-ms`
- **Repo**: by RATT (ratt-ru)
- **What**: Presents an MSv4 **view** over existing MSv2 Measurement Sets
- **Key feature**: No conversion needed — lazy view via xarray's backend API
- **Usage**: `xarray.open_datatree("test.ms", engine="xarray-ms")`
- **Backend**: Uses arcae under the hood
- **Status**: Active development, not yet feature-complete vs xradio
- **Can export to Zarr** via xarray's native `.to_zarr()` I/O
- **Predecessor**: dask-ms (Dask-backed access, same team)

### MSv4 Specification

- **Developed by**: NRAO, ESO, NAOJ, SKAO via XRADIO project
- **Docs**: xradio.readthedocs.io
- **Key changes from MSv2**:
  - Replaces relational tables with labeled n-dimensional arrays (xarray)
  - Each MSv4 contains data for a single spectral window/polarization/observation
  - Uses Zarr for on-disk storage, xarray for in-memory representation
  - Backed by NumPy or lazy Dask arrays
- **Processing Set (PS)**: Collection of MSv4 datasets

### XRADIO

- **PyPI**: `xradio`
- **What**: Reference implementation of the MSv4 spec
- **Converts**: MSv2 → MSv4 (xarray DataTree) → Zarr on disk
- **Relation to xarray-ms**: xradio is the "full" converter; xarray-ms is a
  lighter lazy view. Both use arcae.

### Zarr v3

- **Required**: Zarr >= 3 for the abstract store API
- **Store API**: `zarr.abc.store.Store` with async `get()`, `set()`, `list()` etc.
- **Our approach**: Implement a custom store that maps chunk requests to
  xarray-ms reads

## FUSE on macOS

### macFUSE

- **Version**: 5.2.0+ (April 2026)
- **Supports**: macOS 12–26, Intel + Apple Silicon
- **macOS 26 (Tahoe)**: New FSKit backend — runs entirely in user space, no
  kernel extension, no Recovery Mode reboot
- **Pre-26 macOS**: Requires one-time Recovery Mode step for the kext
- **Install**: `brew install macfuse`

### FUSE-T

- **What**: Kext-less FUSE alternative using Apple's NFS mechanism
- **Advantage**: No kernel extension on any macOS version
- **Caveat**: NFS-based, so slightly different semantics (locking, mmap edge cases)
- **Install**: `brew install fuse-t`

### Python FUSE Bindings

| Library | Status | macOS | Notes |
|---------|--------|-------|-------|
| **fusepy** | Unmaintained (6+ years) | Works | ctypes-based, avoid for new code |
| **mfusepy** | Active fork of fusepy | Works | Best bet for macOS, ctypes-based |
| **llfuse** | Maintenance-only | Works | C-extension, most reliable mature option |
| **pyfuse3** | Active | **No** | Linux only (trio-based, requires libfuse3) |
| **refuse** | Abandoned | N/A | Alpha, no development in 4+ years |

**Recommendation**: mfusepy or llfuse + macFUSE or FUSE-T.

## Architecture Options (Ranked)

### Option 1: fsspec Custom Filesystem (Recommended)

Implement `fsspec.AbstractFileSystem` wrapping our MSZarrStore.

**Pros**:
- One implementation gets both Python API and optional FUSE mount
- fsspec has built-in FUSE mounting via `fsspec.fuse.run()`
- Works with Zarr via `zarr.storage.FsspecStore`
- Works with xarray natively
- No native code, works everywhere Python runs
- No FUSE setup needed for programmatic access

**Cons**:
- FUSE mount is optional add-on, not the primary interface

### Option 2: Custom Zarr Store

Implement `zarr.abc.store.Store` mapping chunk reads to arcae.

**Pros**:
- Cleanest API: `xr.open_zarr(store=MSZarrStore("path/to/ms"))`
- No filesystem layer needed
- Minimal dependencies

**Cons**:
- Only useful for xarray/Zarr consumers — no `ls`, no `cat`

### Option 3: Direct FUSE via mfusepy

Implement FUSE operations directly, serving Zarr directory structure.

**Pros**:
- Full filesystem semantics (ls, cat, mount in Finder)
- Tools that need real file paths work

**Cons**:
- Most complex implementation
- Requires macFUSE or FUSE-T installed
- FUSE adds per-syscall overhead
- Synchronous reads vs arcae's lazy model needs careful buffering

### Chosen: Layered Approach (Options 1 + 2)

We implement all three as layers:
1. `MSZarrStore` (Zarr store) — core, pure Python
2. `MSFileSystem` (fsspec) — wraps store, adds filesystem semantics
3. `visfuse` CLI (FUSE) — uses fsspec.fuse, optional

## Technical Challenges

### Zarr Directory Protocol

FUSE must emulate Zarr's directory/chunk-file structure:
- `/.zgroup` or `/zarr.json` — group metadata
- `/VARIABLE/.zarray` — array metadata (dtype, shape, chunks, codecs)
- `/VARIABLE/.zattrs` — xarray-compatible attributes
- `/VARIABLE/0.0.0` — chunk data files

### Performance Considerations

- FUSE adds overhead per syscall — problematic for large visibility datasets
- arcae/xarray-ms is lazy (Dask-backed), which is good
- But FUSE reads are synchronous — need buffering/caching strategy
- Single-chunk-per-variable simplification works for demo but not for
  large datasets (need proper chunk mapping)

### Chunking Strategy

For production use, would need to:
- Map MS row structure to sensible Zarr chunks (time × baseline × channel × pol)
- Handle variable-shaped columns (e.g., FLAG with different shapes per SPW)
- Cache materialized chunks to avoid re-reading

## Dependencies

```
arcae              # Arrow bindings for casacore
xarray-ms          # MSv4 view over MSv2
xarray>=2024.1     # Core array framework
dask[array]        # Lazy computation backend
zarr>=3            # Zarr v3 store API
fsspec             # Abstract filesystem
numpy              # Numerical arrays
mfusepy            # (optional) FUSE bindings
```

## Related Projects

- **python-casacore**: Original Python bindings for casacore (threading issues)
- **dask-ms**: Dask-backed MS access (predecessor to xarray-ms, same team)
- **xradio**: Reference MSv4 implementation (heavier than xarray-ms)
- **CARTA**: Visualization tool that could benefit from Zarr-based MS access
- **h5fuse**: Prior art — HDF5 as FUSE directory tree
- **fsspec**: Already has `fsspec.fuse.run()` for mounting any filesystem

## Open Questions

1. Should we support write-back (Zarr writes → MS updates)?
   Probably not for v1 — read-only is simpler and safer.
2. How to handle multi-SPW MSes? xarray-ms maps each to a DataTree node.
3. Should the FUSE layer cache materialized chunks on disk?
4. Integration with CASA tasks that expect real MS paths?
5. Performance with large datasets (e.g., MeerKAT L-band, ~TB)?
