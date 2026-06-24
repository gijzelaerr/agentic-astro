"""CLI for visgit — version-controlled radio astronomy data."""

from __future__ import annotations

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="visgit",
        description="Git for visibilities — version-controlled radio astronomy data",
    )
    parser.add_argument("--store", required=True, help="Path to visgit store")
    sub = parser.add_subparsers(dest="command")

    ingest_p = sub.add_parser("ingest", help="Ingest a Measurement Set")
    ingest_p.add_argument("ms_path", help="Path to .ms table")

    sub.add_parser("log", help="Show snapshot history")

    diff_p = sub.add_parser("diff", help="Column-aware diff between snapshots")
    diff_p.add_argument("snap1", help="First snapshot (branch, tag, or hash)")
    diff_p.add_argument("snap2", help="Second snapshot")
    diff_p.add_argument("--columns", nargs="*", help="Columns to compare")

    branch_p = sub.add_parser("branch", help="Create a new branch")
    branch_p.add_argument("name", help="Branch name")

    checkout_p = sub.add_parser("checkout", help="Switch to a branch or snapshot")
    checkout_p.add_argument("ref", help="Branch name, tag, or snapshot hash")

    export_p = sub.add_parser("export", help="Export a snapshot to a Measurement Set")
    export_p.add_argument("--ref", default="main", help="Snapshot to export")
    export_p.add_argument("--output", required=True, help="Output .ms path")

    run_p = sub.add_parser("run", help="Run a command with auto-snapshot")
    run_p.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run")

    args = parser.parse_args()

    if args.command == "ingest":
        cmd_ingest(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "diff":
        cmd_diff(args)
    elif args.command == "branch":
        cmd_branch(args)
    elif args.command == "checkout":
        cmd_checkout(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "run":
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


def cmd_ingest(args):
    print(f"TODO: ingest {args.ms_path} into {args.store}")


def cmd_log(args):
    print(f"TODO: show log for {args.store}")


def cmd_diff(args):
    print(f"TODO: diff {args.snap1}..{args.snap2} in {args.store}")


def cmd_branch(args):
    print(f"TODO: create branch {args.name} in {args.store}")


def cmd_checkout(args):
    print(f"TODO: checkout {args.ref} in {args.store}")


def cmd_export(args):
    print(f"TODO: export {args.ref} from {args.store} to {args.output}")


def cmd_run(args):
    print(f"TODO: run {args.cmd} with auto-snapshot in {args.store}")


if __name__ == "__main__":
    main()
