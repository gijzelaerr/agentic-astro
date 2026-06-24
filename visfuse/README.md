# visfuse

A dynamic filesystem that presents Casacore Measurement Sets as Zarr stores —
browse radio interferometry visibilities with any tool that reads Zarr/xarray.

## Concept

```
 ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
 │  Casacore MS │  arcae  │  xarray-ms   │  fsspec  │  Zarr view   │
 │  (on disk)   │ ──────► │  MSv4 / DAP  │ ──────► │  (virtual)   │
 └──────────────┘         └──────────────┘         └──────┬───────┘
                                                          │
                                              ┌───────────┴───────────┐
                                              │                       │
                                         Python API              FUSE mount
                                     xr.open_zarr(store)      mount ~/visfuse
```

Mount a directory of `.ms` tables and they appear as `.zarr` stores. Any tool
that speaks Zarr or xarray (Jupyter, Dask, CARTA, etc.) can read them directly.

## Architecture

Three layers, each usable independently:

| Layer | What | Depends on |
|-------|------|------------|
| `MSZarrStore` | Custom `zarr.abc.store.Store` mapping chunk reads to arcae | arcae, xarray-ms |
| `MSFileSystem` | `fsspec.AbstractFileSystem` wrapping `MSZarrStore` | fsspec |
| `visfuse` CLI | FUSE mount via `fsspec.fuse` | macFUSE or FUSE-T |

## Quick Start

```bash
# Install
pip install -e ".[fuse]"

# Python API — no FUSE needed
python -c "
from visfuse import MSZarrStore
import xarray as xr
store = MSZarrStore('observation.ms')
ds = xr.open_zarr(store)
print(ds)
"

# FUSE mount (requires macFUSE or FUSE-T on macOS, libfuse on Linux)
visfuse mount /data/observations ~/mnt/zarr
# ls ~/mnt/zarr/observation.zarr/.zattrs  ← it's Zarr now
```

## How It Works

1. **arcae** provides fast, thread-safe Arrow-based access to Casacore tables
2. **xarray-ms** presents MSv2 tables as MSv4 xarray DataTrees (lazy, Dask-backed)
3. **MSZarrStore** intercepts Zarr chunk/metadata requests and serves them from
   the xarray-ms view — no data is copied until read
4. **fsspec** makes this accessible as a filesystem, with optional FUSE mounting

## macOS Development

Fully supported:
- **arcae** bundles its own casacore — no separate install needed
- **macFUSE 5.x** uses DriverKit (kext-less on macOS 26+)
- **FUSE-T** is a kext-less alternative (uses NFS translation)
- Install one of: `brew install macfuse` or `brew install fuse-t`

## Dependencies

- `arcae` — Arrow bindings for casacore
- `xarray-ms` — MSv4 view over MSv2 tables
- `xarray` + `dask` — lazy array computation
- `zarr >= 3` — Zarr v3 store API
- `fsspec` — abstract filesystem interface
- `mfusepy` (optional) — FUSE bindings for the mount CLI

## Relationship to xarray-ms

**xarray-ms already does most of the heavy lifting.** You can do
`xr.open_datatree("test.ms", engine="xarray-ms")` today and get a lazy MSv4
xarray DataTree — no visfuse needed for Python-side access.

What visfuse adds on top:
- **FUSE mount** — non-Python tools (CARTA, shell scripts, `ls`/`cat`) can see
  Zarr directories on disk without any code
- **fsspec interface** — tools that speak fsspec but not xarray-ms get access
- **Directory of MSes** — browse multiple MS tables as a single Zarr tree

If your workflow is entirely Python/xarray, you probably don't need visfuse —
just use xarray-ms directly. visfuse is for the OS-level filesystem illusion.

See: https://github.com/ratt-ru/xarray-ms

## Status

Proof of concept / workshop demo.
