"""
Breifast multi-timescale analysis sub-recipe.

Stimela3 Python translation of breifast/recipes/tron-breifast.yml.
This is the sub-recipe called by tron() in tron-pfb-python.py.

It demonstrates the for-loop pattern: iterate over a list of timescales,
run a pipeline on each, and accumulate outputs across iterations.

YAML original: 221 lines (breifast-tron/breifast/recipes/tron-breifast.yml)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import stimela
from stimela import Info, Out

from breifast.cabs import (
    forward_difference_cube,
    process_residual_cube,
    render_cube_cutouts,
    render_detections,
    render_html,
    render_regions,
    time_convolve,
    zarr_to_fits,
)


def stripext(path) -> str:
    return str(Path(path).with_suffix(""))


@stimela.recipe
def tron_breifast(
    # inputs
    cds: Annotated[stimela.Directory, Info("raw time cadence cube dataset (CDS)")],
    baseline_image: Annotated[stimela.File | None, Info("baseline flux map")] = None,
    timescales: Annotated[list[float | str], Info(
        "timescales to process in seconds. 0 = raw cube, 'FD' = forward-difference"
    )] = None,
    ncpu: Annotated[int | None, Info("number of CPUs to use")] = None,
    max_time_gap: Annotated[float | None, Info("time gap in seconds to split convolution")] = 3600,
    candidate_threshold: Annotated[float, Info("candidate threshold in sigma")] = 6,
    detection_threshold: Annotated[float, Info("detection threshold in sigma")] = 7,
    repeater_threshold: Annotated[float, Info("detection threshold for repeaters")] = 6,
    threshold_adjustments: Annotated[
        list[tuple[float, float]], Info("adjust thresholds when timescale exceeds value")
    ] = None,
    # outputs
    dir_out: Annotated[stimela.Directory, Out, Info("output directory")] = None,
):
    """Perform breifast analysis on a series of timescales."""

    if timescales is None:
        timescales = [0, "FD"]
    if threshold_adjustments is None:
        threshold_adjustments = [[240, -0.5], [480, -1]]
    if ncpu is None:
        ncpu = stimela.config.run.ncpu_physical
    if dir_out is None:
        dir_out = str(Path(cds).parent)

    cds_stem = Path(Path(cds).stem).stem  # strip double extension (.raw.zarr)

    # Accumulated outputs across loop iterations
    candidate_catalogs = []
    detection_catalogs = []
    cds_list = []
    dp_catalogs = []

    for timescale in timescales:
        # --- Classify timescale ---
        is_raw = timescale == 0
        is_fd = timescale == "FD"
        is_convolved = isinstance(timescale, (int, float)) and timescale > 0

        # --- Derive output paths ---
        if is_raw:
            cube_id = "raw"
        elif is_convolved:
            cube_id = f"{timescale:.0f}s"
        elif is_fd:
            cube_id = "diff"
        else:
            continue

        out_cds_dir = f"{dir_out}/{cube_id}"
        out_cds_name = f"{cds_stem}.{cube_id}.zarr"
        out_cds_path = f"{out_cds_dir}/{out_cds_name}"

        # --- Step 1: Convolve (only for timescale > 0) ---
        if is_convolved:
            conv = time_convolve(
                cds=cds,
                out_cds=out_cds_path,
                timescale_sec=timescale,
                ncpu=ncpu,
                max_time_gap=max_time_gap,
                _cache="fresh",
            )
            step_cds = conv.out_cds
        elif is_fd:
            diff = forward_difference_cube(
                cds=cds,
                out_cds=out_cds_path,
                _cache="fresh",
            )
            step_cds = diff.out_cds
        else:
            step_cds = cds

        # --- Step 2: Convert to FITS (skip for raw) ---
        if not is_raw:
            zarr_to_fits(
                cds=step_cds,
                out_image=f"{stripext(step_cds)}.fits",
                drop_frequency_axis=True,
                var="cube",
                _cache="fresh",
            )

        # --- Step 3: Adjust threshold for long timescales ---
        threshold_adjust = 0
        if is_convolved:
            for ts_limit, adj in threshold_adjustments:
                if timescale >= ts_limit:
                    threshold_adjust = adj

        # --- Step 4: Process residual cube → candidate catalog ---
        procres = process_residual_cube(
            cds=step_cds,
            output_catalog=f"{out_cds_dir}/{Path(stripext(step_cds)).name}.candidates.ecsv",
            baseline_image=baseline_image,
            ncpu=ncpu,
            threshold=candidate_threshold + threshold_adjust,
            reject_flux_threshold=2,
            boxsize=400,
            _cache="fresh",
        )

        # --- Step 5: Filter candidates → detection catalog ---
        detections = render_detections(
            catalog=procres.output_catalog,
            output_catalog=f"{stripext(stripext(procres.output_catalog))}.detections.ecsv",
            threshold=detection_threshold + threshold_adjust,
            threshold_repeaters=repeater_threshold + threshold_adjust,
            _cache="fresh",
        )

        # --- Step 6: Regions file ---
        render_regions(
            catalog=detections.output_catalog,
            output_regions=f"{stripext(detections.output_catalog)}.reg",
            threshold=detections.threshold,
            _cache="fresh",
        )

        # --- Step 7: Cube cutouts ---
        cutouts = render_cube_cutouts(
            catalogs=[detections.output_catalog],
            cds=step_cds,
            output_dir=f"{out_cds_dir}/cube-cutouts",
            dp_catalog=f"{out_cds_dir}/cube-cutouts/cutout.products.ecsv",
            dp_id="did",
            _cache="fresh",
        )

        # --- Step 8: HTML ---
        render_html(
            catalogs=[detections.output_catalog],
            dp_catalogs=[cutouts.dp_catalog],
            output_html=f"{stripext(detections.output_catalog)}.html",
            _cache="fresh",
        )

        # --- Accumulate outputs ---
        cds_list.append(out_cds_path)
        candidate_catalogs.append(procres.output_catalog)
        detection_catalogs.append(detections.output_catalog)
        dp_catalogs.append(cutouts.dp_catalog)

    return stimela.ResultNamespace(
        cds_list=cds_list,
        candidate_catalogs=candidate_catalogs,
        detection_catalogs=detection_catalogs,
        dp_catalogs=dp_catalogs,
    )
