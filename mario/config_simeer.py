"""Museek pipeline config: read real MeerKAT data, replace visibilities with Simeer simulation.

InPlugin reads the observation and extracts pointing coordinates.
SimeerPlugin generates beam-weighted sky TOD from those coordinates and
overwrites the visibility. All downstream plugins see simulated data.

Usage:
    ivory config_simeer    # from the mario/ directory (with mario/ on PYTHONPATH)
"""

from ivory.utils.config_section import ConfigSection

Pipeline = ConfigSection(
    plugins=[
        # 1. Read real MeerKAT data (pointing, timestamps, frequencies)
        "museek.plugin.in_plugin",
        # 2. Replace visibility with Simeer simulation
        "museek.plugin.simeer_plugin",
        # 3. Continue with the normal Museek pipeline
        "museek.plugin.noise_diode_flagger_plugin",
        "museek.plugin.known_rfi_plugin",
        "museek.plugin.scan_track_split_plugin",
        # add more downstream plugins as needed...
    ],
)

# --- InPlugin: load real observation for its pointing coordinates ---
InPlugin = ConfigSection(
    block_name="1675632179",  # observation block ID — change to your data
    data_folder="/idia/raw/meerklass/SCI-20220822-MS-01/",  # path to MVF4 data
    receiver_list=None,
    token=None,
    force_load_auto_from_correlator_data=True,
    force_load_cross_from_correlator_data=True,
    do_save_visibility_to_disc=False,
    do_store_context=False,
    context_folder=None,
)

# --- SimeerPlugin: generate simulated sky signal ---
SimeerPlugin = ConfigSection(
    beam_file=None,  # None = synthetic Gaussian; set path for real MeerKLASS beam NPZ
    sky_model="uniform",  # "uniform" or "pysm3"
    sky_temperature=10.0,  # [K] for uniform sky
    nside=128,
    fwhm_deg=1.5,  # synthetic beam FWHM [degrees]
    disc_radius_deg=8.0,
    polarization="HH",
    n_jobs=-1,  # -1 = use all cores
)

# --- Downstream plugins (same config as normal Museek pipeline) ---
NoiseDiodeFlaggerPlugin = ConfigSection()

KnownRfiPlugin = ConfigSection(
    gsm_900_uplink=None,
    gsm_900_downlink=(925, 960),
    gsm_1800_uplink=None,
    gps=None,
    extra_rfi=[(768, 778), (801, 811), (811, 821)],
)

ScanTrackSplitPlugin = ConfigSection(
    do_delete_unsplit_data=True,
    do_store_context=False,
)
