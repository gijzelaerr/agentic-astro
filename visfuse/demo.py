"""Demo: open a Measurement Set as xarray via visfuse.

Usage:
    python demo.py /path/to/observation.ms

This demonstrates all three access patterns:
1. Direct xarray-ms (the underlying engine)
2. Via MSZarrStore (our custom Zarr store)
3. Via MSFileSystem (fsspec, FUSE-mountable)
"""

import sys
from pathlib import Path


def demo_direct(ms_path: str):
    """Pattern 1: Direct xarray-ms access (no visfuse needed)."""
    import xarray as xr

    print("=== Direct xarray-ms ===")
    tree = xr.open_datatree(ms_path, engine="xarray-ms")
    print(tree)
    print()


def demo_zarr_store(ms_path: str):
    """Pattern 2: Via MSZarrStore — MS appears as a Zarr store."""
    import xarray as xr
    from visfuse import MSZarrStore

    print("=== MSZarrStore ===")
    store = MSZarrStore(ms_path)
    print(f"Store: {store}")
    print(f"DataTree structure:")
    print(store.tree)
    print()


def demo_fsspec(ms_dir: str):
    """Pattern 3: Via fsspec — browse a directory of MS tables as Zarr."""
    from visfuse import MSFileSystem

    print("=== MSFileSystem (fsspec) ===")
    fs = MSFileSystem(ms_dir)
    print(f"Available Zarr stores: {fs.ls('/')}")
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    ms_path = sys.argv[1]
    p = Path(ms_path)

    if p.suffix == ".ms" and p.is_dir():
        demo_direct(ms_path)
        demo_zarr_store(ms_path)
        demo_fsspec(str(p.parent))
    elif p.is_dir():
        demo_fsspec(ms_path)
    else:
        print(f"Not found or not a .ms directory: {ms_path}")
        sys.exit(1)
