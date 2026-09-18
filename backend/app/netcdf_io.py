from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator

import xarray as xr


# The Windows netCDF4/HDF5 build used by the local server can fail when
# multiple FastAPI worker threads open files at the same time. Keep reads
# process-wide and serialized; calculations continue after the file is closed.
_NETCDF_READ_LOCK = RLock()


@contextmanager
def open_netcdf(path: str | Path) -> Iterator[xr.Dataset]:
    with _NETCDF_READ_LOCK:
        # h5netcdf/h5py accepts Unicode Windows paths, while the netCDF4 C
        # backend can reject the same valid path. All production grids are
        # NetCDF-4/HDF5 files.
        with xr.open_dataset(path, engine="h5netcdf") as dataset:
            yield dataset
