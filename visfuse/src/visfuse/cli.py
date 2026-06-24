"""CLI for visfuse — mount Measurement Sets as Zarr stores."""

from __future__ import annotations

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="visfuse",
        description="Mount a directory of Casacore Measurement Sets as Zarr stores",
    )
    sub = parser.add_subparsers(dest="command")

    mount_p = sub.add_parser("mount", help="FUSE-mount MS directory as Zarr")
    mount_p.add_argument("ms_root", help="Directory containing .ms tables")
    mount_p.add_argument("mount_point", help="Where to mount the Zarr view")
    mount_p.add_argument("--foreground", "-f", action="store_true")

    info_p = sub.add_parser("info", help="Show MS tables and their MSv4 structure")
    info_p.add_argument("ms_path", help="Path to a .ms table")

    args = parser.parse_args()

    if args.command == "mount":
        cmd_mount(args)
    elif args.command == "info":
        cmd_info(args)
    else:
        parser.print_help()
        sys.exit(1)


def cmd_mount(args):
    try:
        from fsspec.fuse import run
    except ImportError:
        print("FUSE mount requires: pip install 'visfuse[fuse]'", file=sys.stderr)
        sys.exit(1)

    from visfuse.filesystem import MSFileSystem

    fs = MSFileSystem(args.ms_root)
    print(f"Mounting {args.ms_root} → {args.mount_point}")
    print(f"Found {len(fs._stores)} Measurement Set(s)")
    for name in sorted(fs._stores):
        print(f"  {name}")
    print("Press Ctrl+C to unmount")

    run(fs, "", args.mount_point, foreground=args.foreground)


def cmd_info(args):
    from visfuse.store import MSZarrStore
    import xarray as xr

    store = MSZarrStore(args.ms_path)
    tree = store.tree
    print(f"Measurement Set: {args.ms_path}")
    print(f"MSv4 DataTree structure:\n")
    print(tree)


if __name__ == "__main__":
    main()
