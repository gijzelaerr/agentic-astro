"""
Create a synthetic MeerKAT-like dataset and run Simeer simulation on it.

Bypasses katdal entirely by building a lightweight mock of Museek's
TimeOrderedData with realistic MeerKAT pointing tracks. Runs Simeer
to generate simulated visibilities and saves everything to disk.

Usage:
    cd mario/
    source .venv/bin/activate
    python3 create_test_dataset.py

Outputs (in mario/test_data/):
    pointing_tracks.png     — per-antenna azimuth/elevation tracks
    waterfall_m000.png      — frequency-time waterfall for antenna m000
    sky_tod.npy             — simulated visibility array (n_dump, n_freq, n_recv)
    timestamps.npy          — Unix timestamps (n_dump,)
    frequencies_hz.npy      — frequency grid in Hz (n_freq,)
    az_deg.npy              — azimuth per antenna (n_dump, n_antenna)
    el_deg.npy              — elevation per antenna (n_dump, n_antenna)
    lst_deg.npy             — LST in degrees (n_dump,)
    mock_data.pkl           — pickled MockTimeOrderedData for pipeline use
"""

import os
import pickle

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from astropy.coordinates import EarthLocation
from astropy.time import Time
import astropy.units as u
import healpy as hp

from simeer import synthetic_gaussian_beam, integrate_tod
from museek.data_element import DataElement
from museek.flag_element import FlagElement
from museek.flag_list import FlagList
from museek.factory.data_element_factory import FlagElementFactory
from museek.receiver import Receiver, Polarisation

MEERKAT_LAT = -30.7130
MEERKAT_LON = 21.4430
MEERKAT_HEIGHT_M = 1054
MEERKAT_LOCATION = EarthLocation(
    lat=MEERKAT_LAT * u.deg,
    lon=MEERKAT_LON * u.deg,
    height=MEERKAT_HEIGHT_M * u.m,
)


class MockAntenna:
    """Minimal stand-in for katpoint.Antenna."""

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return self.name == other.name

    def __repr__(self):
        return f"MockAntenna({self.name!r})"


class MockTimeOrderedData:
    """Lightweight mock of museek.TimeOrderedData for testing without katdal.

    Has just enough attributes for SimeerPlugin and basic downstream use.
    """

    def __init__(self, timestamps, frequencies_hz, az_deg, el_deg, antenna_names):
        """
        Parameters
        ----------
        timestamps : 1-D array, Unix seconds
        frequencies_hz : 1-D array, Hz
        az_deg : 2-D array (n_dump, n_antenna), degrees
        el_deg : 2-D array (n_dump, n_antenna), degrees
        antenna_names : list[str], e.g. ['m000', 'm001', ...]
        """
        n_dump = len(timestamps)
        n_freq = len(frequencies_hz)
        n_ant = len(antenna_names)

        self.antennas = [MockAntenna(name) for name in antenna_names]
        self._antenna_name_list = antenna_names

        self.receivers = []
        for ant_num, name in enumerate(antenna_names):
            num = int(name[1:])
            self.receivers.append(Receiver(num, Polarisation.h))
            self.receivers.append(Receiver(num, Polarisation.v))

        self.timestamps = DataElement(
            array=timestamps[:, np.newaxis, np.newaxis]
        )
        self.original_timestamps = DataElement(
            array=timestamps[:, np.newaxis, np.newaxis]
        )
        self.frequencies = DataElement(
            array=frequencies_hz[np.newaxis, :, np.newaxis]
        )

        self.azimuth = DataElement(array=az_deg[:, np.newaxis, :])
        self.elevation = DataElement(array=el_deg[:, np.newaxis, :])

        ra, dec = self._az_el_to_ra_dec(timestamps, az_deg, el_deg)
        self.right_ascension = DataElement(array=ra[:, np.newaxis, :])
        self.declination = DataElement(array=dec[:, np.newaxis, :])
        self.parangle = DataElement(
            array=np.zeros((n_dump, 1, n_ant), dtype=np.float64)
        )

        self.temperature = DataElement(
            array=np.full((n_dump, 1, 1), 20.0)
        )
        self.humidity = DataElement(
            array=np.full((n_dump, 1, 1), 50.0)
        )
        self.pressure = DataElement(
            array=np.full((n_dump, 1, 1), 900.0)
        )

        n_recv = len(self.receivers)
        self.visibility = None
        self.flags = None
        self.weights = None
        self.visibility_cross = None
        self.flags_cross = None
        self.weights_cross = None
        self.gain_solution = None

        self.name = "synthetic_test"
        self.dump_period = float(timestamps[1] - timestamps[0]) if n_dump > 1 else 8.0
        self.shape = (n_dump, n_freq, n_recv)
        self.scan_state = None

    def antenna_index_of_receiver(self, receiver):
        try:
            ant = self.antennas[self._antenna_name_list.index(receiver.antenna_name)]
            return self.antennas.index(ant)
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _az_el_to_ra_dec(timestamps, az_deg, el_deg):
        from astropy.coordinates import AltAz, SkyCoord

        n_dump, n_ant = az_deg.shape
        ra = np.zeros_like(az_deg)
        dec = np.zeros_like(az_deg)
        times = Time(timestamps, format="unix")
        for j in range(n_ant):
            altaz = AltAz(
                az=az_deg[:, j] * u.deg,
                alt=el_deg[:, j] * u.deg,
                obstime=times,
                location=MEERKAT_LOCATION,
            )
            icrs = SkyCoord(altaz).icrs
            ra[:, j] = icrs.ra.deg
            dec[:, j] = icrs.dec.deg
        return ra, dec


def generate_pointing_tracks(n_dump, n_antenna, dump_period=8.0, start_time=1675632179.0):
    """Generate realistic MeerKAT constant-elevation azimuth-scan tracks.

    Each antenna gets a slight random offset to mimic real dish scatter.
    """
    timestamps = start_time + np.arange(n_dump) * dump_period

    base_az = 180.0 + 10.0 * np.sin(2 * np.pi * np.arange(n_dump) / n_dump)
    base_el = 45.0 + 5.0 * np.sin(2 * np.pi * np.arange(n_dump) / (n_dump * 2))

    rng = np.random.default_rng(42)
    az_deg = np.column_stack(
        [base_az + rng.normal(0, 0.01, n_dump) for _ in range(n_antenna)]
    )
    el_deg = np.column_stack(
        [base_el + rng.normal(0, 0.005, n_dump) for _ in range(n_antenna)]
    )

    return timestamps, az_deg, el_deg


def compute_lst(timestamps):
    times = Time(timestamps, format="unix")
    lst = times.sidereal_time("apparent", longitude=MEERKAT_LOCATION.lon)
    return lst.deg


def run_simeer(lst_deg, az_deg, el_deg, freq_mhz, n_jobs=1):
    """Run Simeer integrate_tod for one antenna track."""
    margin_deg = np.linspace(-6, 6, 121)
    beam = synthetic_gaussian_beam(
        freq_MHz=freq_mhz, margin_deg=margin_deg, fwhm_deg=1.5
    )

    nside = 128
    npix = hp.nside2npix(nside)
    sky_maps = np.full((len(freq_mhz), npix), 10.0, dtype=np.float64)

    tod = integrate_tod(
        lst_deg_list=lst_deg,
        az_deg_list=az_deg,
        el_deg_list=el_deg,
        lat_deg=MEERKAT_LAT,
        beam=beam,
        sky_maps=sky_maps,
        freq_MHz=freq_mhz,
        disc_radius_deg=8.0,
        polarization="HH",
        n_jobs=n_jobs,
    )
    return tod


def plot_pointing_tracks(timestamps, az_deg, el_deg, antenna_names, out_path):
    t_minutes = (timestamps - timestamps[0]) / 60.0
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for i, name in enumerate(antenna_names):
        ax1.plot(t_minutes, az_deg[:, i], label=name, alpha=0.8)
        ax2.plot(t_minutes, el_deg[:, i], label=name, alpha=0.8)
    ax1.set_ylabel("Azimuth [deg]")
    ax1.legend(fontsize=8, ncol=4)
    ax1.set_title("Synthetic MeerKAT pointing tracks")
    ax2.set_ylabel("Elevation [deg]")
    ax2.set_xlabel("Time [minutes from start]")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved {out_path}")


def plot_waterfall(tod, freq_mhz, antenna_name, out_path):
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
    ax.set_title(f"Simulated Sky TOD — antenna {antenna_name}")
    fig.colorbar(im, ax=ax, label="Antenna T [K]")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved {out_path}")


def main():
    N_DUMP = 128
    N_FREQ = 32
    N_ANTENNA = 4
    DUMP_PERIOD = 8.0
    ANTENNA_NAMES = [f"m{i:03d}" for i in range(N_ANTENNA)]

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_data")
    os.makedirs(out_dir, exist_ok=True)

    print(f"=== Creating synthetic MeerKAT test dataset ===")
    print(f"  {N_DUMP} dumps x {N_FREQ} channels x {N_ANTENNA} antennas ({2*N_ANTENNA} receivers)")
    print()

    # 1. Generate pointing tracks
    print("1. Generating pointing tracks...")
    timestamps, az_deg, el_deg = generate_pointing_tracks(
        N_DUMP, N_ANTENNA, dump_period=DUMP_PERIOD
    )
    freq_hz = np.linspace(580e6, 1000e6, N_FREQ)
    freq_mhz = freq_hz / 1e6
    print(f"  Timestamps: {timestamps[0]:.0f} to {timestamps[-1]:.0f} ({DUMP_PERIOD}s cadence)")
    print(f"  Frequencies: {freq_mhz[0]:.0f} to {freq_mhz[-1]:.0f} MHz ({N_FREQ} channels)")
    print(f"  Elevation range: {el_deg.min():.1f} to {el_deg.max():.1f} deg")
    print()

    plot_pointing_tracks(
        timestamps, az_deg, el_deg, ANTENNA_NAMES,
        os.path.join(out_dir, "pointing_tracks.png"),
    )

    # 2. Compute LST
    print("2. Computing LST from timestamps...")
    lst_deg = compute_lst(timestamps)
    print(f"  LST range: {lst_deg[0]:.2f} to {lst_deg[-1]:.2f} deg")
    print()

    # 3. Run Simeer per antenna
    print("3. Running Simeer simulation per antenna...")
    antenna_tods = {}
    for i, name in enumerate(ANTENNA_NAMES):
        print(f"  Antenna {name}...", end=" ", flush=True)
        tod = run_simeer(lst_deg, az_deg[:, i], el_deg[:, i], freq_mhz, n_jobs=1)
        antenna_tods[name] = tod
        print(f"shape={tod.shape}, mean={tod.mean():.3f} K")

    plot_waterfall(
        antenna_tods[ANTENNA_NAMES[0]], freq_mhz, ANTENNA_NAMES[0],
        os.path.join(out_dir, f"waterfall_{ANTENNA_NAMES[0]}.png"),
    )
    print()

    # 4. Assemble into visibility array (n_dump, n_freq, n_recv)
    print("4. Assembling visibility array...")
    n_recv = 2 * N_ANTENNA
    visibility = np.zeros((N_DUMP, N_FREQ, n_recv), dtype=np.float64)
    for ant_i, name in enumerate(ANTENNA_NAMES):
        tod = antenna_tods[name]  # (n_freq, n_dump)
        visibility[:, :, 2 * ant_i] = tod.T      # H pol
        visibility[:, :, 2 * ant_i + 1] = tod.T  # V pol (same beam for now)
    print(f"  visibility shape: {visibility.shape}")
    print()

    # 5. Build MockTimeOrderedData
    print("5. Building MockTimeOrderedData...")
    mock_data = MockTimeOrderedData(
        timestamps=timestamps,
        frequencies_hz=freq_hz,
        az_deg=az_deg,
        el_deg=el_deg,
        antenna_names=ANTENNA_NAMES,
    )
    mock_data.visibility = DataElement(array=visibility)
    flag_array = np.zeros((1, N_DUMP, N_FREQ, n_recv), dtype=bool)
    mock_data.flags = FlagList.from_array(
        array=flag_array, element_factory=FlagElementFactory()
    )
    mock_data.weights = DataElement(
        array=np.ones((N_DUMP, N_FREQ, n_recv), dtype=np.float64)
    )
    print(f"  receivers: {[r.name for r in mock_data.receivers]}")
    print()

    # 6. Save everything
    print("6. Saving to", out_dir)
    np.save(os.path.join(out_dir, "sky_tod.npy"), visibility)
    np.save(os.path.join(out_dir, "timestamps.npy"), timestamps)
    np.save(os.path.join(out_dir, "frequencies_hz.npy"), freq_hz)
    np.save(os.path.join(out_dir, "az_deg.npy"), az_deg)
    np.save(os.path.join(out_dir, "el_deg.npy"), el_deg)
    np.save(os.path.join(out_dir, "lst_deg.npy"), lst_deg)

    pkl_path = os.path.join(out_dir, "mock_data.pkl")
    with open(pkl_path, "wb") as f:
        pickle.dump(mock_data, f)
    print(f"  Saved pickle: {pkl_path}")
    print()

    # 7. Verification
    print("7. Verification:")
    print(f"  Visibility mean:  {visibility.mean():.3f} K (expect ~10 for uniform sky)")
    print(f"  Visibility range: [{visibility.min():.3f}, {visibility.max():.3f}] K")
    print(f"  Flags all clear:  {not mock_data.flags.combine(threshold=1).array.any()}")
    for recv in mock_data.receivers[:2]:
        ant_idx = mock_data.antenna_index_of_receiver(recv)
        az = mock_data.azimuth.get_array(recv=ant_idx).squeeze()
        print(f"  {recv.name} antenna_index={ant_idx}, az[0]={az[0]:.3f} deg")
    print()
    print("Done! Test dataset ready in", out_dir)


if __name__ == "__main__":
    main()
