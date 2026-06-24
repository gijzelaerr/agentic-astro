# visgit — TODO

## Phase 1: Proof of concept
- [ ] `pip install icechunk arcae xarray-ms`
- [ ] Ingest a small test MS into an Icechunk store
- [ ] Verify round-trip: MS → Icechunk → xarray read
- [ ] Modify FLAG column, commit, verify only FLAG chunks are new
- [ ] Measure storage savings vs full copy

## Phase 2: CLI
- [ ] `visgit ingest <ms_path> --store <path>` — MS to Icechunk
- [ ] `visgit log --store <path>` — show snapshot history
- [ ] `visgit diff <snap1> <snap2> --store <path>` — column-aware diff
- [ ] `visgit branch / checkout` — branching support
- [ ] `visgit export <snapshot> --output <ms_path>` — snapshot to MS

## Phase 3: Pipeline integration
- [ ] `visgit run --store <path> -- <command>` — auto-snapshot before/after
- [ ] CASA integration (intercept or wrap MS writes)
- [ ] Hook into common tools: AOFlagger, wsclean, quartical

## Phase 4: Stretch goals
- [ ] Merge semantics for FLAG columns (union/intersection/custom)
- [ ] Web UI for browsing snapshots (via Arraylake?)
- [ ] S3/GCS backend for HPC clusters
- [ ] Connect to visfuse — read-only FUSE view of any snapshot
- [ ] Benchmark with real MeerKAT / LOFAR scale data
