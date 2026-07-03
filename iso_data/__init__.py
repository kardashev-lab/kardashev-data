"""
Supplementary data clients for kardashev-data (non-ISO sources).

ISO/RTO modules (CAISO, ERCOT, MISO, NYISO, ISONE, SPP, PJM) are now
provided by the `kardashev` package. Import them as:
    from kardashev import _caiso as caiso, _ercot as ercot, ...

This package retains only sources not yet in kardashev:
  bpa            - Bonneville Power Administration
  eia            - EIA API (generation, storage, capacity)
  eia_930        - EIA-930 balancing authority data
  eia_commodities - EIA commodity prices
  epa            - EPA emissions data
  nrc            - NRC reactor status
  nrel           - NREL solar/wind resource data
  rggi           - RGGI carbon market
  usbr           - Bureau of Reclamation hydro
  weather        - Weather observations
"""

from kardashev import (
    _caiso as caiso,
    _eia as eia,
    _ercot as ercot,
    _ercot_lmp as ercot_lmp,
    _isone as isone,
    _isone_api as isone_api,
    _miso as miso,
    _miso_lmp as miso_lmp,
    _nyiso as nyiso,
    _pjm as pjm,
    _spp as spp,
)

from . import (
    _http,
    bpa,
    eia_930,
    eia_commodities,
    epa,
    nrc,
    nrel,
    rggi,
    usbr,
    weather,
)

__all__ = [
    "caiso", "eia", "eia_930", "eia_commodities", "ercot", "ercot_lmp", "epa",
    "isone", "isone_api", "miso", "miso_lmp", "nrc", "nrel", "nyiso", "pjm",
    "rggi", "spp", "usbr", "weather", "_http",
]
