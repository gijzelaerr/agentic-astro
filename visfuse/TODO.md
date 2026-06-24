# visfuse — TODO

## Next Steps

### Phase 1: Get it running
- [ ] Install deps: `pip install -e ".[dev]"`
- [ ] Find or create a small test MS (e.g., from CASA simobserve or xarray-ms test fixtures)
- [ ] Verify `xarray.open_datatree("test.ms", engine="xarray-ms")` works
- [ ] Test `MSZarrStore` with a real MS
- [ ] Test `MSFileSystem.ls()` and `MSFileSystem.open()`

### Phase 2: FUSE mount
- [ ] Install macFUSE (`brew install macfuse`) or FUSE-T (`brew install fuse-t`)
- [ ] Install mfusepy (`pip install mfusepy`)
- [ ] Test `visfuse mount /path/to/ms/dir ~/mnt/zarr`
- [ ] Verify `ls ~/mnt/zarr/` shows .zarr directories
- [ ] Try `xr.open_zarr("~/mnt/zarr/observation.zarr")`

### Phase 3: Polish
- [ ] Proper chunk mapping (not single-chunk-per-variable)
- [ ] Chunk caching for repeated reads
- [ ] Handle multi-SPW Measurement Sets
- [ ] File size reporting in fsspec `info()` / FUSE `getattr()`
- [ ] Error handling for corrupt or locked MS tables

### Phase 4: Stretch goals
- [ ] Benchmark: direct xarray-ms vs MSZarrStore vs FUSE mount
- [ ] Write support (Zarr writes back to MS)
- [ ] Integration with CARTA for visualization
- [ ] Publish to PyPI
