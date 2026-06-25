"""
TRON: Transient Radio Observations for Newbies — pfb HCI version.

Stimela3 Python translation of breifast/recipes/tron-pfb.yml.
This is the acid test from Discussion #567: does the Python API produce
something at least as readable as the YAML original?

YAML original: 568 lines (breifast-tron/breifast/recipes/tron-pfb.yml)
Python version: ~300 lines of recipe logic + ~50 lines of config dataclasses

NOT runnable code — this is an API design sketch for discussion.

Key API conventions used:
    @stimela.recipe              — marks a function as a recipe
    Annotated[type, Out, Info()] — annotate parameters as inputs (default) or outputs
    cab(params, ...)             — cab objects imported from packages, called with ()
    result.output_name           — access cab outputs as typed attributes
    _cache="fresh"               — skip step if outputs exist and are newer than inputs
    _tags=["a", "b"]             — tag steps for selective execution
    _backend="singularity"       — override backend for this step
    None parameters              — auto-skipped (replaces =IFSET() from YAML)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import stimela
from stimela import Info, Out

# Cab imports — each package exposes its cabs as importable objects.
# The cab object knows its command, parameter schema, and flavour.
# Calling it validates params, constructs the command, and dispatches to the backend.
from cultcargo.cabs import bdsf_catalog
from breifast.cabs import (
    consolidate_detections,
    extract_lightcurves,
    flag_cube,
    make_baseline_image,
    make_region_cutouts,
    match_catalogs,
    merge_catalogs,
    plot_lightcurves,
    render_deep_cutouts,
    render_detection_maps,
    render_eta_v_plots,
    render_html,
    render_regions,
    validate_tron_outputs,
    zarr_to_fits,
)
from breifast.recipes import tron_breifast, tron_brb_spectra
from breifast.cabs import copy as utils_copy, build_breifast_database
from pfb_imaging.cabs import hci
from suricat.recipes import suricat_init


def stripext(path) -> str:
    """Remove file extension — equivalent to YAML's =STRIPEXT()."""
    return str(Path(path).with_suffix(""))


# --- Grouped input parameters as dataclasses ---

@dataclass
class ColumnConfig:
    """Visibility column configuration."""
    data: Annotated[str, Info("corrected visibilities column")] = "CORRECTED_DATA-MODEL_DATA"
    model: Annotated[str | None, Info("model visibilities column")] = None
    sigma: Annotated[str | None, Info("sigma column")] = None
    weight: Annotated[str, Info("weight column")] = "WEIGHT_SPECTRUM"
    flag: Annotated[str, Info("flag column")] = "FLAG"


@dataclass
class HtcConfig:
    """High time cadence imaging configuration."""
    phase_dir: Annotated[str | None, Info("rephase visibilities to this phase center")] = None
    cadence: Annotated[int, Info("raw cube imaging time cadence, in integrations")] = 1
    npix: Annotated[int | None, Info("size of cube, in pixels")] = None
    cell_size: Annotated[float | None, Info("pixel size in arcseconds")] = None
    field_of_view: Annotated[float | None, Info("field of view to image in degrees")] = None
    super_resolution_factor: Annotated[float | None, Info("how much to oversample Nyquist by")] = None
    robustness: Annotated[float, Info("robustness value for Briggs weighting")] = 0.0
    freq_range: Annotated[str | None, Info("frequency range to image in Hz")] = None
    fields: Annotated[list[int] | None, Info("list of FIELD_IDs to image")] = None
    ddids: Annotated[list[int] | None, Info("list of DATA_DESC_IDs to image")] = None
    scans: Annotated[list[int] | None, Info("list of SCAN_NUMBERs to image")] = None
    l2_reweight_dof: Annotated[float | None, Info("robust reweighting degrees of freedom")] = None
    nthreads: Annotated[int, Info("number of threads per worker")] = 1
    psf_out: Annotated[bool, Info("output PSF image")] = False
    psf_relative_size: Annotated[float, Info("PSF size relative to image")] = 1.0
    epsilon: Annotated[float, Info("gridding precision")] = 1e-4
    double_accum: Annotated[bool, Info("use double precision accumulation")] = False
    precision: Annotated[str, Info("gridding precision")] = "single"
    padding: Annotated[float, Info("padding factor during imaging")] = 2.0
    images_per_chunk: Annotated[int | None, Info("images per chunk (performance tuning)")] = None
    max_simul_chunks: Annotated[int | None, Info("max simultaneous chunks (performance tuning)")] = None
    wgt_mode: Annotated[str, Info("Stokes weight computation mode")] = "minvar"


# --- The main TRON recipe ---

@stimela.recipe
def tron(
    # required inputs
    obs: Annotated[str, Info(
        "Observation label. Used to label output products. "
        "Short, informative strings e.g. 3C147-L are recommended."
    )],
    ms: Annotated[list[stimela.URI], Info("input measurement set(s)")],
    primary_beam_band: Annotated[
        stimela.Choices["U", "L", "S0", "S1", "S2", "S3", "S4"],
        Info("primary beam band for suricat beam models"),
    ],
    deep_image: Annotated[stimela.File, Info(
        "deep image of field, required to make a baseline detection image"
    )],
    # required outputs
    dir_out: Annotated[stimela.Directory, Out, Info(
        "output directory where products will be generated"
    )],
    # grouped configs
    column: ColumnConfig = field(default_factory=ColumnConfig),
    htc: HtcConfig = field(default_factory=HtcConfig),
    # optional inputs
    stokes: Annotated[str, Info("Stokes parameters to process, e.g. I, IV, IQUV")] = "I",
    gain_table: Annotated[stimela.URI | None, Info("optional QuartiCal gain table")] = None,
    max_time_gap: Annotated[float, Info("time gap in seconds to split convolution")] = 3600,
    interesting_regions: Annotated[stimela.File | None, Info(
        "regions file with interesting sources for unconditional lightcurve extraction"
    )] = None,
    nlc: Annotated[int | None, Info("number of lightcurves to extract, -1 for all")] = 100,
    lightcurves_within: Annotated[str, Info("only extract lightcurves within this distance of centre")] = "1deg",
    publish_plots: Annotated[bool, Info("make publication-quality lightcurve plots")] = False,
    spectrum_sources: Annotated[list[str], Info("sources for single-interval spectra")] = field(default_factory=list),
    ncpu: Annotated[int | None, Info("number of CPUs/processes to use")] = None,
    enable_fits_cubes: Annotated[bool, Info("enable output of FITS cubes")] = True,
    enable_pimenton_cutouts: Annotated[bool, Info("enable Pimenton/ESASky cutouts")] = False,
    flag_excess_rms: Annotated[float, Info("flag slices with rms > N * median(rms)")] = 1.5,
    beam_model: Annotated[stimela.URI | None, Info("beam model for image-htc step")] = None,
    inject_transients: Annotated[stimela.File | None, Info("transient injection file (.yaml)")] = None,
    # optional outputs
    dir_tmp: Annotated[stimela.Directory, Out, Info("temporary directory")] = "/tmp",
):
    """TRON: Transient Radio Observations for Newbies — pfb HCI version."""

    # Derived paths
    dir_scales = f"{dir_out}/scales"
    dir_logs = f"{dir_out}/logs/log-{stimela.config.run.datetime}"
    dir_deep_image = f"{dir_out}/deep-image"
    base_cube_name = "cube"

    if ncpu is None:
        ncpu = stimela.config.run.ncpu_physical

    # --- Step 1: Image at high time cadence ---
    htc_result = hci(
        ms=ms,
        obs_label=obs,
        data_column=column.data,
        weight_column=column.weight,
        model_column=column.model,
        flag_column=column.flag,
        gain_table=gain_table,
        output_dataset=f"{dir_scales}/raw/{base_cube_name}.raw.zarr",
        images_per_chunk=htc.images_per_chunk,
        max_simul_chunks=htc.max_simul_chunks,
        integrations_per_image=htc.cadence,
        channels_per_image=-1,
        freq_range=htc.freq_range,
        robustness=htc.robustness,
        field_of_view=htc.field_of_view,
        super_resolution_factor=htc.super_resolution_factor,
        cell_size=htc.cell_size,
        nx=htc.npix,
        ny=htc.npix,
        product=stokes,
        fields=htc.fields,
        ddids=htc.ddids,
        scans=htc.scans,
        l2_reweight_dof=htc.l2_reweight_dof,
        nthreads=htc.nthreads,
        nworkers=ncpu,
        overwrite=True,
        psf_out=htc.psf_out,
        psf_relative_size=htc.psf_relative_size,
        epsilon=htc.epsilon,
        double_accum=htc.double_accum,
        precision=htc.precision,
        phase_dir=htc.phase_dir,
        beam_model=beam_model,
        inject_transients=inject_transients,
        eta=1e-1,
        min_padding=htc.padding,
        temp_dir=dir_tmp,
        wgt_mode=htc.wgt_mode,
        flag_excess_rms=flag_excess_rms,
        log_directory=f"{dir_logs}/pfb-logs",
        _tags=["lightcurves", "cubes"],
        _cache="exist",
    )

    # --- Step 2: Flag excess RMS planes ---
    flag_cube(
        cds=htc_result.output_dataset,
        flag_excess_rms=flag_excess_rms,
        _cache="fresh",
    )

    # --- Step 3-4: Convert cubes to FITS ---
    if enable_fits_cubes:
        zarr_to_fits(
            cds=htc_result.output_dataset,
            out_image=f"{stripext(htc_result.output_dataset)}.mean.fits",
            drop_frequency_axis=True,
            var="cube_mean",
            _tags=["lightcurves", "cubes_to_fits", "cubes"],
            _cache="fresh",
        )
        zarr_to_fits(
            cds=htc_result.output_dataset,
            out_image=f"{stripext(htc_result.output_dataset)}.fits",
            drop_frequency_axis=True,
            var="cube",
            flag_var="flag",
            _tags=["lightcurves", "cubes_to_fits", "cubes"],
            _cache="fresh",
        )

    # --- Step 5: Primary beams ---
    beams = None
    if primary_beam_band:
        beams = suricat_init(
            dir_out="beam",
            band=primary_beam_band,
            mdv_beams=f"beam/mdv-beams-{primary_beam_band}.npz",
            bds=f"beam/beam-{primary_beam_band}.bds.zarr",
            _tags=["lightcurves", "spectra"],
            _cache="exist",
        )

    # --- Step 6: Copy deep image ---
    deep_copy = utils_copy(
        input_path=deep_image,
        output_path=f"{dir_deep_image}/deep-image.fits",
        _backend="native",
        _cache="fresh",
    )

    # --- Step 7: Make baseline image ---
    baseline = make_baseline_image(
        flux_image=deep_copy.output_path,
        target=htc_result.output_dataset,
        max_filter_size=15,
        baseline_image=f"{stripext(deep_copy.output_path)}.baseline.fits",
        _cache="fresh",
    )

    # --- Step 8: Breifast multi-timescale search ---
    breifast_result = tron_breifast(
        dir_out=dir_scales,
        baseline_image=baseline.baseline_image,
        cds=htc_result.output_dataset,
        timescales=[0, "FD", 15, 30, 60, 120, 240, 480, 960],
        ncpu=ncpu,
        max_time_gap=max_time_gap,
        _tags=["breifast"],
    )

    # --- Step 9: Consolidate detections ---
    consolidated = consolidate_detections(
        catalogs=breifast_result.detection_catalogs,
        output_catalog=f"{dir_out}/unified-detections.ecsv",
        _cache="fresh",
        _tags=["breifast"],
    )

    # --- Step 10: Render detection regions ---
    render_regions(
        catalog=consolidated.output_catalog,
        output_regions=f"{stripext(consolidated.output_catalog)}.reg",
        _cache="fresh",
        _tags=["breifast"],
    )

    # --- Step 11: Source finder (runs in Singularity) ---
    source_finder = bdsf_catalog(
        image=deep_copy.output_path,
        thresh_pix=4,
        thresh_isl=3,
        rms_box=[100, 20],
        rms_map=False,
        catalog_format="ascii",
        outfile_gaul=f"{stripext(deep_copy.output_path)}.gaul",
        outfile_srl=f"{stripext(deep_copy.output_path)}.srl",
        _backend="singularity",
        _cache="fresh",
        _tags=["lightcurves"],
    )

    # --- Step 12: Master catalog ---
    master_cat = match_catalogs(
        image=deep_copy.output_path,
        detection_catalog=consolidated.output_catalog,
        interesting_regions=interesting_regions,
        output_catalog=f"{stripext(deep_copy.output_path)}.mastercat.ecsv",
        max_radius="1.5deg",
        catalogs={"bdsf": [source_finder.outfile_gaul, 0, "main"]},
        _cache="fresh",
        _tags=["lightcurves"],
    )

    # --- Step 13: Extract lightcurves ---
    lc_extract = extract_lightcurves(
        cds=htc_result.output_dataset,
        catalog=master_cat.output_catalog,
        output_dir=f"{dir_out}/lightcurves",
        plot_beamgains=primary_beam_band is not None,
        bds=beams.bds if beams else None,
        regfile=f"{stripext(deep_copy.output_path)}.extracted-lightcurves.reg",
        srctype="P",
        fluxcols=["flux_bdsf"],
        ncpu=ncpu,
        nsrc=nlc,
        within=lightcurves_within,
        dp_catalog=f"{stripext(master_cat.output_catalog)}.lightcurve-raw.products.ecsv",
        _cache="fresh",
        _tags=["lightcurves"],
    )

    # --- Step 14: Plot lightcurves ---
    lc_plot = plot_lightcurves(
        lc_xds_paths=lc_extract.lc_xds_paths,
        catalog=master_cat.output_catalog,
        output_dir=lc_extract.output_dir,
        stats_catalog_base=f"{lc_extract.output_dir}/lightcurves.stats",
        scales=breifast_result.timescales,
        make_power_spectra=True,
        ncpu=ncpu,
        dp_catalog=f"{stripext(master_cat.output_catalog)}.lightcurve-plot.products.ecsv",
        _cache="fresh",
        _tags=["lightcurves"],
    )

    # --- Step 15: Extract spectra (optional) ---
    if spectrum_sources:
        tron_brb_spectra(
            dir_out=dir_out,
            sources=spectrum_sources,
            nbands=[2, 3, 4, 5],
            bds=beams.bds if beams else None,
            cds=htc_result.stacked_ds,
            catalog=consolidated.output_catalog,
            ms=ms,
            column=column.data,
            stokes=stokes,
            temp_dir=dir_tmp,
            _tags=["spectra"],
        )

    # --- Step 16: Pimenton cutouts (optional) ---
    pimenton = None
    if enable_pimenton_cutouts:
        pimenton = make_region_cutouts(
            catalog=consolidated.output_catalog,
            output_dir=f"{dir_out}/esasky-cutouts",
            output_summary=f"{dir_out}/esasky-cutouts/summary.txt",
            dp_catalog=f"{dir_out}/esasky-cutouts/pimenton.products.ecsv",
            cache_dir=dir_tmp,
            _cache="fresh",
            _tags=["cutouts"],
        )

    # --- Step 17: Deep cutouts ---
    deep_cutouts = render_deep_cutouts(
        catalogs=[consolidated.output_catalog],
        deep_image=deep_copy.output_path,
        output_dir=f"{dir_out}/cutouts",
        dp_catalog=f"{dir_out}/cutouts/deep-cutouts.products.ecsv",
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 18: Detection maps ---
    det_maps = render_detection_maps(
        catalogs=[consolidated.output_catalog],
        deep_image=deep_copy.output_path,
        output_dir=f"{dir_out}/cutouts",
        dp_catalog=f"{dir_out}/cutouts/detection-maps.products.ecsv",
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 19: Eta-V plots ---
    eta_v = render_eta_v_plots(
        catalog=consolidated.output_catalog,
        lc_stats=lc_plot.stats_catalogs,
        output_dir=f"{lc_extract.output_dir}/eta-v-plots",
        dp_catalog=f"{lc_extract.output_dir}/eta-v-plots/eta-v.products.ecsv",
        regenerate=True,
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 20: Consolidate all data product catalogs ---
    dp_catalogs = breifast_result.dp_catalogs.copy()
    if pimenton:
        dp_catalogs.append(pimenton.dp_catalog)
    dp_catalogs.extend([
        deep_cutouts.dp_catalog,
        det_maps.dp_catalog,
        eta_v.dp_catalog,
        lc_plot.dp_catalog,
    ])

    merged = merge_catalogs(
        catalogs=dp_catalogs,
        output_catalog=f"{dir_out}/unified-products.ecsv",
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 21: Render HTML summary ---
    render_html(
        catalogs=[consolidated.output_catalog],
        dp_catalogs=[merged.output_catalog],
        output_html=f"{stripext(consolidated.output_catalog)}.html",
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 22: Build SQLite database ---
    build_breifast_database(
        candidates_catalogs=breifast_result.candidate_catalogs,
        detections_catalogs=breifast_result.detection_catalogs,
        unified_detections_catalog=consolidated.output_catalog,
        cube_cutouts_catalogs=breifast_result.dp_catalogs,
        cutouts_catalogs=[deep_cutouts.dp_catalog, det_maps.dp_catalog],
        deep_image=deep_copy.output_path,
        master_catalog=master_cat.output_catalog,
        esasky_cutouts_catalog=pimenton.dp_catalog if enable_pimenton_cutouts else None,
        lightcurve_catalogs=[lc_extract.dp_catalog, lc_plot.dp_catalog],
        lightcurve_stats_catalogs=lc_plot.stats_catalogs,
        detection_products_catalogs=[eta_v.dp_catalog],
        output_db=f"{dir_out}/breifast.sqlite",
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 23: Validate outputs ---
    validate_tron_outputs(
        directory=dir_out,
        require_fits=enable_fits_cubes,
    )
