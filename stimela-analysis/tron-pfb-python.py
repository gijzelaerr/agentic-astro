"""
TRON: Transient Radio Observations for Newbies — pfb HCI version.

Stimela3 Python translation of breifast/recipes/tron-pfb.yml.
This is the acid test from Discussion #567: does the Python API produce
something at least as readable as the YAML original?

YAML original: 568 lines (breifast-tron/breifast/recipes/tron-pfb.yml)
Python version: ~290 lines of recipe logic + ~50 lines of config dataclasses

NOT runnable code — this is an API design sketch for discussion.
The stimela.run() calls, @stimela.recipe decorator, and typed result
objects shown here are the proposed Stimela3 API.

Key API conventions used:
    stimela.run("cab", ...) — run a cab, returns typed result object
    result.output_name     — access cab outputs as typed attributes
    _cache="fresh"         — skip step if outputs exist and are newer than inputs
    _cache="exist"         — skip step if outputs exist at all
    _tags=["a", "b"]       — tag steps for selective execution (stimela exec ... --tags a)
    _backend="singularity" — override backend for this step
    None parameters        — auto-skipped (replaces =IFSET() from YAML)
"""

from dataclasses import dataclass, field
from pathlib import Path

import stimela


def stripext(path) -> str:
    """Remove file extension — equivalent to YAML's =STRIPEXT()."""
    return str(Path(path).with_suffix(""))


# --- Grouped input parameters as dataclasses ---

@dataclass
class ColumnConfig:
    data: str = "CORRECTED_DATA-MODEL_DATA"
    model: str | None = None
    sigma: str | None = None
    weight: str = "WEIGHT_SPECTRUM"
    flag: str = "FLAG"


@dataclass
class HtcConfig:
    """High time cadence imaging configuration."""
    phase_dir: str | None = None
    cadence: int = 1
    npix: int | None = None
    cell_size: float | None = None
    field_of_view: float | None = None
    super_resolution_factor: float | None = None
    robustness: float = 0.0
    freq_range: str | None = None
    fields: list[int] | None = None
    ddids: list[int] | None = None
    scans: list[int] | None = None
    l2_reweight_dof: float | None = None
    nthreads: int = 1
    psf_out: bool = False
    psf_relative_size: float = 1.0
    epsilon: float = 1e-4
    double_accum: bool = False
    precision: str = "single"
    padding: float = 2.0
    images_per_chunk: int | None = None
    max_simul_chunks: int | None = None
    wgt_mode: str = "minvar"


# --- Sub-recipe: referenced but defined elsewhere ---
# suricat_init, tron_breifast, tron_brb_spectra are separate recipe modules


# --- The main TRON recipe ---

@stimela.recipe
def tron(
    obs: str,
    ms: list[stimela.URI],
    primary_beam_band: stimela.Choices["U", "L", "S0", "S1", "S2", "S3", "S4"],
    deep_image: stimela.File,
    dir_out: stimela.Directory,
    # grouped configs
    column: ColumnConfig = field(default_factory=ColumnConfig),
    htc: HtcConfig = field(default_factory=HtcConfig),
    # optional inputs
    stokes: str = "I",
    gain_table: stimela.URI | None = None,
    max_time_gap: float = 3600,
    interesting_regions: stimela.File | None = None,
    nlc: int | None = 100,
    lightcurves_within: str = "1deg",
    publish_plots: bool = False,
    publish_plot_title: str = "Observation {obs}: peak $ {peak_ujy:.0f}\\pm{peak_std_ujy:.0f} $ uJy",
    spectrum_sources: list[str] = field(default_factory=list),
    ncpu: int | None = None,
    enable_fits_cubes: bool = True,
    enable_pimenton_cutouts: bool = False,
    flag_excess_rms: float = 1.5,
    beam_model: stimela.URI | None = None,
    inject_transients: stimela.File | None = None,
    # outputs
    dir_tmp: stimela.Directory = "/tmp",
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
    htc_result = stimela.run("hci",
        ms=ms,
        obs_label=obs,
        data_column=column.data,
        weight_column=column.weight,       # None params are auto-skipped
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
    stimela.run("breifast.flag-cube",
        cds=htc_result.output_dataset,
        flag_excess_rms=flag_excess_rms,
        _cache="fresh",
    )

    # --- Step 3: Convert time-mean to FITS ---
    if enable_fits_cubes:
        stimela.run("breifast.zarr-to-fits",
            cds=htc_result.output_dataset,
            out_image=f"{stripext(htc_result.output_dataset)}.mean.fits",
            drop_frequency_axis=True,
            var="cube_mean",
            _tags=["lightcurves", "cubes_to_fits", "cubes"],
            _cache="fresh",
        )

    # --- Step 4: Convert full cube to FITS ---
    if enable_fits_cubes:
        stimela.run("breifast.zarr-to-fits",
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
        beams = stimela.run("suricat-init",
            dir_out="beam",
            band=primary_beam_band,
            mdv_beams=f"beam/mdv-beams-{primary_beam_band}.npz",
            bds=f"beam/beam-{primary_beam_band}.bds.zarr",
            _tags=["lightcurves", "spectra"],
            _cache="exist",
        )

    # --- Step 6: Copy deep image ---
    deep_copy = stimela.run("utils.copy",
        input_path=deep_image,
        output_path=f"{dir_deep_image}/deep-image.fits",
        _backend="native",
        _cache="fresh",
    )

    # --- Step 7: Make baseline image ---
    baseline = stimela.run("breifast.make-baseline-image",
        flux_image=deep_copy.output_path,
        target=htc_result.output_dataset,
        max_filter_size=15,
        baseline_image=f"{stripext(deep_copy.output_path)}.baseline.fits",
        _cache="fresh",
    )

    # --- Step 8: Breifast multi-timescale search ---
    breifast_result = stimela.run("tron-breifast",
        dir_out=dir_scales,
        baseline_image=baseline.baseline_image,
        cds=htc_result.output_dataset,
        timescales=[0, "FD", 15, 30, 60, 120, 240, 480, 960],
        ncpu=ncpu,
        max_time_gap=max_time_gap,
        _tags=["breifast"],
    )

    # --- Step 9: Consolidate detections ---
    consolidated = stimela.run("breifast.consolidate-detections",
        catalogs=breifast_result.detection_catalogs,
        output_catalog=f"{dir_out}/unified-detections.ecsv",
        _cache="fresh",
        _tags=["breifast"],
    )

    # --- Step 10: Render detection regions ---
    stimela.run("breifast.render-regions",
        catalog=consolidated.output_catalog,
        output_regions=f"{stripext(consolidated.output_catalog)}.reg",
        _cache="fresh",
        _tags=["breifast"],
    )

    # --- Step 11: Source finder (runs in Singularity) ---
    source_finder = stimela.run("bdsf.catalog",
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
    master_cat = stimela.run("breifast.match-catalogs",
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
    lc_extract = stimela.run("breifast.extract-lightcurves",
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
    lc_plot = stimela.run("breifast.plot-lightcurves",
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
        stimela.run("tron-brb-spectra",
            dir_out=dir_out,
            sources=spectrum_sources,
            nbands=[2, 3, 4, 5],
            bds=beams.bds if beams else None,
            cds=htc_result.stacked_ds,
            catalog=consolidated.output_catalog,
            ms=ms,
            column=column.residual if hasattr(column, "residual") else column.data,
            subtract_model=not hasattr(column, "residual"),
            weight=htc.weight,
            size=htc.size,
            scale=htc.scale,
            stokes=stokes,
            temp_dir=dir_tmp,
            _tags=["spectra"],
        )

    # --- Step 16: Pimenton cutouts (optional) ---
    pimenton = None
    if enable_pimenton_cutouts:
        pimenton = stimela.run("breifast.make-region-cutouts",
            catalog=consolidated.output_catalog,
            output_dir=f"{dir_out}/esasky-cutouts",
            output_summary=f"{dir_out}/esasky-cutouts/summary.txt",
            dp_catalog=f"{dir_out}/esasky-cutouts/pimenton.products.ecsv",
            cache_dir=dir_tmp,
            _cache="fresh",
            _tags=["cutouts"],
        )

    # --- Step 17: Deep cutouts ---
    deep_cutouts = stimela.run("breifast.render-deep-cutouts",
        catalogs=[consolidated.output_catalog],
        deep_image=deep_copy.output_path,
        output_dir=f"{dir_out}/cutouts",
        dp_catalog=f"{dir_out}/cutouts/deep-cutouts.products.ecsv",
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 18: Detection maps ---
    det_maps = stimela.run("breifast.render-detection-maps",
        catalogs=[consolidated.output_catalog],
        deep_image=deep_copy.output_path,
        output_dir=f"{dir_out}/cutouts",
        dp_catalog=f"{dir_out}/cutouts/detection-maps.products.ecsv",
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 19: Eta-V plots ---
    eta_v = stimela.run("breifast.render-eta-v-plots",
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

    merged = stimela.run("breifast.merge-catalogs",
        catalogs=dp_catalogs,
        output_catalog=f"{dir_out}/unified-products.ecsv",
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 21: Render HTML summary ---
    stimela.run("breifast.render-html",
        catalogs=[consolidated.output_catalog],
        dp_catalogs=[merged.output_catalog],
        output_html=f"{stripext(consolidated.output_catalog)}.html",
        _cache="fresh",
        _tags=["breifast", "consolidate"],
    )

    # --- Step 22: Build SQLite database ---
    stimela.run("utils.build-breifast-database",
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
    stimela.run("breifast.validate-tron-outputs",
        directory=dir_out,
        require_fits=enable_fits_cubes,
    )
