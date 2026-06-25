"""
Standalone demo: extract dish pointings from Museek, simulate with Simeer.

This script shows the full flow without running the Ivory pipeline machinery.
Useful for understanding each step and for the live workshop demo.

Requirements:
    pip install -e ./museek -e ./ivory -e ./Simeer
    # plus: katdal, astropy, healpy, numpy, matplotlib
"""

import numpy as np
import matplotlib.pyplot as plt
from astropy.coordinates import EarthLocation
from astropy.time import Time
import astropy.units as u
import healpy as hp

from simeer import synthetic_gaussian_beam, integrate_tod

MEERKAT_LOCATION = EarthLocation(
    lat=-30.7130 * u.deg, lon=21.4430 * u.deg, height=1054 * u.m
)


def load_museek_data(block_name, data_folder=None, token=None):
    """Load MeerKAT data via Museek's TimeOrderedData (what InPlugin does)."""
    from museek.time_ordered_data import TimeOrderedData

    data = TimeOrderedData(
        block_name=block_name,
        receivers=None,
        token=token,
        data_folder=data_folder,
        force_load_auto_from_correlator_data=True,
        force_load_cross_from_correlator_data=False,
    )
    return data


def extract_pointings(data):
    """Extract dish pointing coordinates from TimeOrderedData.

    Returns per-antenna arrays of (timestamps, lst_deg, az_deg, el_deg).
    """
    timestamps = data.timestamps.squeeze  # (n_dump,)

    times = Time(timestamps, format="unix")
    lst_deg = times.sidereal_time(
        "apparent", longitude=MEERKAT_LOCATION.lon
    ).deg

    antennas = {}
    seen = set()
    for receiver in data.receivers:
        ant_idx = data.antenna_index_of_receiver(receiver)
        if ant_idx is None or ant_idx in seen:
            continue
        seen.add(ant_idx)

        az = data.azimuth.get_array(recv=ant_idx).squeeze()
        el = data.elevation.get_array(recv=ant_idx).squeeze()
        antennas[receiver.antenna_name] = {
            "az_deg": az,
            "el_deg": el,
            "lst_deg": lst_deg,
            "ant_idx": ant_idx,
        }

    return timestamps, antennas


def simulate_sky_tod(
    pointings,
    freq_mhz,
    beam=None,
    sky_maps=None,
    nside=128,
    sky_temperature=10.0,
    fwhm_deg=1.5,
    disc_radius_deg=8.0,
    n_jobs=-1,
):
    """Run Simeer for one antenna's pointing track.

    Returns sky TOD array of shape (n_freq, n_time).
    """
    if beam is None:
        margin_deg = np.linspace(-6, 6, 121)
        beam = synthetic_gaussian_beam(
            freq_MHz=freq_mhz, margin_deg=margin_deg, fwhm_deg=fwhm_deg
        )

    if sky_maps is None:
        npix = hp.nside2npix(nside)
        sky_maps = np.full(
            (len(freq_mhz), npix), sky_temperature, dtype=np.float64
        )

    tod = integrate_tod(
        lst_deg_list=pointings["lst_deg"],
        az_deg_list=pointings["az_deg"],
        el_deg_list=pointings["el_deg"],
        lat_deg=MEERKAT_LOCATION.lat.deg,
        beam=beam,
        sky_maps=sky_maps,
        freq_MHz=freq_mhz,
        disc_radius_deg=disc_radius_deg,
        n_jobs=n_jobs,
    )
    return tod


def plot_pointings(antennas, title="Dish pointings"):
    """Plot azimuth and elevation tracks for all antennas."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    for name, p in antennas.items():
        n = len(p["az_deg"])
        t = np.arange(n)
        ax1.plot(t, p["az_deg"], label=name, alpha=0.7)
        ax2.plot(t, p["el_deg"], label=name, alpha=0.7)

    ax1.set_ylabel("Azimuth [deg]")
    ax1.legend(fontsize=6, ncol=4)
    ax2.set_ylabel("Elevation [deg]")
    ax2.set_xlabel("Time dump")
    fig.suptitle(title)
    fig.tight_layout()
    return fig


def plot_waterfall(tod, freq_mhz, title="Simulated Sky TOD"):
    """Plot frequency-time waterfall of the simulated TOD."""
    fig, ax = plt.subplots(figsize=(10, 4))
    im = ax.imshow(
        tod,
        aspect="auto",
        origin="lower",
        extent=[0, tod.shape[1], freq_mhz[0], freq_mhz[-1]],
        cmap="magma",
    )
    ax.set_xlabel("Time dump")
    ax.set_ylabel("Frequency [MHz]")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, label="Antenna T [K]")
    fig.tight_layout()
    return fig


# ──────────────────────────────────────────────────────────────────────
# Run this as a script for a quick self-contained demo (no real data needed)
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Simeer standalone demo (synthetic pointing + synthetic beam) ===\n")

    # Fake pointing track: a simple azimuth scan at fixed elevation
    n_dump = 256
    freq_mhz = np.linspace(580, 1000, 64)

    fake_pointings = {
        "lst_deg": np.linspace(100, 120, n_dump),
        "az_deg": 180.0 + 5.0 * np.sin(np.linspace(0, 4 * np.pi, n_dump)),
        "el_deg": np.full(n_dump, 45.0),
    }

    print(f"Simulating {n_dump} time dumps x {len(freq_mhz)} freq channels...")
    tod = simulate_sky_tod(
        fake_pointings,
        freq_mhz,
        sky_temperature=10.0,
        n_jobs=1,
    )
    print(f"Result shape: {tod.shape}  (n_freq, n_time)")
    print(f"Mean antenna temperature: {tod.mean():.2f} K (expect ~10 K for uniform sky)")

    plot_waterfall(tod, freq_mhz, title="Simulated Sky TOD (uniform 10 K sky)")
    plt.savefig("demo_simeer_waterfall.png", dpi=150)
    print("\nSaved waterfall plot to demo_simeer_waterfall.png")
    plt.show()
