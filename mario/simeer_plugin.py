import numpy as np
from astropy.coordinates import EarthLocation
from astropy.time import Time
import astropy.units as u
import healpy as hp

from ivory.plugin.abstract_plugin import AbstractPlugin
from ivory.utils.requirement import Requirement
from ivory.utils.result import Result

from museek.data_element import DataElement
from museek.enums.result_enum import ResultEnum
from museek.flag_list import FlagList
from museek.factory.data_element_factory import FlagElementFactory

from simeer import integrate_tod, synthetic_gaussian_beam

MEERKAT_LOCATION = EarthLocation(
    lat=-30.7130 * u.deg, lon=21.4430 * u.deg, height=1054 * u.m
)


class SimeerPlugin(AbstractPlugin):
    """Replace real visibility data with Simeer-simulated sky TOD.

    Sits after InPlugin in the pipeline. Extracts dish pointing
    coordinates from the TimeOrderedData, runs Simeer's beam-weighted
    sky integration per antenna, and overwrites the visibility with
    the simulated signal. The rest of the pipeline sees clean
    simulated data.
    """

    def __init__(
        self,
        beam_file: str | None = None,
        sky_model: str = "uniform",
        sky_temperature: float = 10.0,
        nside: int = 128,
        fwhm_deg: float = 1.5,
        disc_radius_deg: float = 8.0,
        polarization: str = "HH",
        n_jobs: int = 1,
    ):
        """
        :param beam_file: path to MeerKLASS beam NPZ, or None for a synthetic Gaussian
        :param sky_model: "uniform" for constant-temperature sky, "pysm3" for synchrotron model
        :param sky_temperature: brightness temperature for the uniform sky model [K]
        :param nside: HEALPix resolution for the sky model
        :param fwhm_deg: FWHM of the synthetic Gaussian beam [degrees]
        :param disc_radius_deg: sky disc radius for integration [degrees]
        :param polarization: beam polarization to use ("HH" or "VV")
        :param n_jobs: number of parallel workers for Simeer (-1 = all cores)
        """
        super().__init__()
        self.beam_file = beam_file
        self.sky_model = sky_model
        self.sky_temperature = sky_temperature
        self.nside = nside
        self.fwhm_deg = fwhm_deg
        self.disc_radius_deg = disc_radius_deg
        self.polarization = polarization
        self.n_jobs = n_jobs

    def set_requirements(self):
        self.requirements = [
            Requirement(location=ResultEnum.DATA, variable="data"),
        ]

    def run(self, data):
        timestamps = data.timestamps.squeeze
        freq_hz = data.frequencies.squeeze
        freq_mhz = freq_hz / 1e6

        lst_deg = self._compute_lst(timestamps)
        beam = self._create_beam(freq_mhz)
        sky_maps = self._create_sky(freq_mhz)

        n_dump = len(timestamps)
        n_freq = len(freq_mhz)
        n_recv = len(data.receivers)

        simulated = np.zeros((n_dump, n_freq, n_recv), dtype=np.float64)

        antenna_cache = {}
        for recv_idx, receiver in enumerate(data.receivers):
            ant_idx = data.antenna_index_of_receiver(receiver)
            if ant_idx is None:
                continue

            if ant_idx not in antenna_cache:
                az = data.azimuth.get_array(recv=ant_idx).squeeze()
                el = data.elevation.get_array(recv=ant_idx).squeeze()

                print(
                    f"  SimeerPlugin: simulating antenna {receiver.antenna_name} "
                    f"({n_dump} dumps x {n_freq} channels)"
                )
                tod = integrate_tod(
                    lst_deg_list=lst_deg,
                    az_deg_list=az,
                    el_deg_list=el,
                    lat_deg=MEERKAT_LOCATION.lat.deg,
                    beam=beam,
                    sky_maps=sky_maps,
                    freq_MHz=freq_mhz,
                    disc_radius_deg=self.disc_radius_deg,
                    polarization=self.polarization,
                    n_jobs=self.n_jobs,
                )
                antenna_cache[ant_idx] = tod  # (n_freq, n_dump)

            simulated[:, :, recv_idx] = antenna_cache[ant_idx].T

        data.visibility = DataElement(array=simulated)
        flag_array = np.zeros((1, n_dump, n_freq, n_recv), dtype=bool)
        data.flags = FlagList.from_array(
            array=flag_array, element_factory=FlagElementFactory()
        )
        data.weights = DataElement(
            array=np.ones((n_dump, n_freq, n_recv), dtype=np.float64)
        )

        print(
            f"  SimeerPlugin: replaced visibility with simulated data, "
            f"shape {simulated.shape}"
        )

        self.set_result(
            Result(location=ResultEnum.DATA, result=data, allow_overwrite=True)
        )

    @staticmethod
    def _compute_lst(timestamps):
        times = Time(timestamps, format="unix")
        lst = times.sidereal_time("apparent", longitude=MEERKAT_LOCATION.lon)
        return lst.deg

    def _create_beam(self, freq_mhz):
        if self.beam_file:
            from simeer import MeerKLASSBeam

            return MeerKLASSBeam(self.beam_file)

        margin_deg = np.linspace(-6, 6, 121)
        return synthetic_gaussian_beam(
            freq_MHz=freq_mhz, margin_deg=margin_deg, fwhm_deg=self.fwhm_deg
        )

    def _create_sky(self, freq_mhz):
        npix = hp.nside2npix(self.nside)
        if self.sky_model == "uniform":
            return np.full(
                (len(freq_mhz), npix), self.sky_temperature, dtype=np.float64
            )
        if self.sky_model == "pysm3":
            import pysm3

            sky = pysm3.Sky(nside=self.nside, preset_strings=["s1"])
            return np.array(
                [sky.get_emission(f * u.MHz)[0].value for f in freq_mhz]
            )
        raise ValueError(f"Unknown sky_model: {self.sky_model!r}")
