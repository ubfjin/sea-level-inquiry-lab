"""Build global and regional steric sea-level products from Copernicus T/S.

The default request is roughly 134 GB. Importing this module never starts a
download; run the command with --dry-run before starting the full workflow.
"""

from __future__ import annotations

import argparse
import calendar
import shutil
from pathlib import Path

import gsw
import numpy as np
import pandas as pd
import xarray as xr


DATASET_ID = "cmems_mod_glo_phy-mnstd_my_0.25deg_P1M-m"
DATASET_VERSION = "202311"
TEMPERATURE_VARIABLE = "thetao_mean"
SALINITY_VARIABLE = "so_mean"
SOURCE_VARIABLES = (TEMPERATURE_VARIABLE, SALINITY_VARIABLE)
COMPONENTS = ("steric_total", "thermosteric", "halosteric")

START = pd.Timestamp("2003-01-01")
END = pd.Timestamp("2023-04-01")
REFERENCE_START = pd.Timestamp("2003-01-01")
REFERENCE_END = pd.Timestamp("2010-12-01")

SOURCE_MIN_LONGITUDE = -180.0
SOURCE_MAX_LONGITUDE = 179.75
SOURCE_MIN_LATITUDE = -80.0
SOURCE_MAX_LATITUDE = 90.0
SOURCE_MIN_DEPTH = 0.5057600140571594
SOURCE_MAX_DEPTH = 5902.0576171875

GLOBAL_LATITUDE = np.arange(-89.5, 90.0, 1.0)
GLOBAL_LONGITUDE = np.arange(-179.5, 180.0, 1.0)
DETAIL_BOUNDS = (120.0, 160.0, 25.0, 45.0)
MIN_FREE_SPACE_GB = 180.0

DEFAULT_RAW_DIRECTORY = Path("data/source/steric/copernicus_ensemble")
DEFAULT_CHUNK_DIRECTORY = Path("data/processed/steric/chunks")
DEFAULT_REFERENCE = Path("data/processed/steric/reference_200301_201012_025deg.nc")
DEFAULT_GLOBAL_OUTPUT = Path("data/processed/steric/steric_monthly_global_1deg.nc")
DEFAULT_DETAIL_OUTPUT = Path("data/processed/steric/steric_monthly_kuroshio_025deg.nc")


def expected_months(year: int) -> pd.DatetimeIndex:
    first = max(START, pd.Timestamp(year=year, month=1, day=1))
    last = min(END, pd.Timestamp(year=year, month=12, day=1))
    if first > last:
        return pd.DatetimeIndex([])
    return pd.date_range(first, last, freq="MS")


def all_expected_months() -> pd.DatetimeIndex:
    return pd.date_range(START, END, freq="MS")


def source_year_path(raw_directory: Path, year: int) -> Path:
    return raw_directory / f"steric_ts_{year}.nc"


def global_year_path(chunk_directory: Path, year: int) -> Path:
    return chunk_directory / f"steric_global_1deg_{year}.nc"


def detail_year_path(chunk_directory: Path, year: int) -> Path:
    return chunk_directory / f"steric_kuroshio_025deg_{year}.nc"


def _atomic_write(dataset: xr.Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part.nc")
    if temporary.exists():
        temporary.unlink()
    encoding = {
        name: {"zlib": True, "complevel": 4, "shuffle": True}
        for name in dataset.data_vars
    }
    dataset.to_netcdf(temporary, engine="h5netcdf", encoding=encoding)
    temporary.replace(path)


def validate_source_year(path: Path, year: int) -> xr.Dataset:
    if not path.exists():
        raise FileNotFoundError(path)
    dataset = xr.open_dataset(path, engine="h5netcdf")
    missing = [name for name in SOURCE_VARIABLES if name not in dataset]
    if missing:
        dataset.close()
        raise ValueError(f"{path}: missing variables {missing}")
    required_dimensions = {"time", "depth", "latitude", "longitude"}
    absent_dimensions = required_dimensions.difference(dataset.sizes)
    if absent_dimensions:
        dataset.close()
        raise ValueError(f"{path}: missing dimensions {sorted(absent_dimensions)}")
    actual = pd.DatetimeIndex(dataset.time.values).to_period("M")
    wanted = expected_months(year).to_period("M")
    if not actual.equals(wanted):
        dataset.close()
        raise ValueError(f"{path}: expected {list(wanted)}, received {list(actual)}")
    return dataset


def download_year(path: Path, year: int, overwrite: bool = False) -> None:
    """Download one calendar-year source file through copernicusmarine."""
    if path.exists() and not overwrite:
        dataset = validate_source_year(path, year)
        dataset.close()
        print(f"[reuse] {path}")
        return
    import copernicusmarine

    months = expected_months(year)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".part.nc")
    if temporary.exists():
        temporary.unlink()
    last_month = months[-1]
    last_day = calendar.monthrange(last_month.year, last_month.month)[1]
    copernicusmarine.subset(
        dataset_id=DATASET_ID,
        dataset_version=DATASET_VERSION,
        variables=list(SOURCE_VARIABLES),
        minimum_longitude=SOURCE_MIN_LONGITUDE,
        maximum_longitude=SOURCE_MAX_LONGITUDE,
        minimum_latitude=SOURCE_MIN_LATITUDE,
        maximum_latitude=SOURCE_MAX_LATITUDE,
        minimum_depth=SOURCE_MIN_DEPTH,
        maximum_depth=SOURCE_MAX_DEPTH,
        start_datetime=f"{months[0]:%Y-%m-01}T00:00:00",
        end_datetime=f"{last_month:%Y-%m}-{last_day:02d}T23:59:59",
        output_filename=temporary.name,
        output_directory=str(temporary.parent),
        overwrite=True,
        disable_progress_bar=True,
    )
    temporary.replace(path)
    dataset = validate_source_year(path, year)
    dataset.close()
    print(f"[downloaded] {path}")


def depth_edges(depth: np.ndarray) -> np.ndarray:
    depth = np.asarray(depth, dtype=np.float64)
    if depth.ndim != 1 or depth.size < 2 or np.any(np.diff(depth) <= 0):
        raise ValueError("depth must be strictly increasing and one-dimensional")
    edges = np.empty(depth.size + 1, dtype=np.float64)
    edges[1:-1] = (depth[:-1] + depth[1:]) / 2.0
    edges[0] = max(0.0, depth[0] - (edges[1] - depth[0]))
    edges[-1] = depth[-1] + (depth[-1] - edges[-2])
    return edges


def pressure_geometry(
    depth: np.ndarray, latitude: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    depth = np.asarray(depth, dtype=np.float64)
    latitude = np.asarray(latitude, dtype=np.float64)
    centres = gsw.p_from_z(-depth[:, None], latitude[None, :])
    edges = depth_edges(depth)
    edge_pressure = gsw.p_from_z(-edges[:, None], latitude[None, :])
    pressure_thickness = np.diff(edge_pressure, axis=0) * 1.0e4
    gravity = gsw.grav(latitude[None, :], centres)
    return centres[:, :, None], pressure_thickness[:, :, None], gravity[:, :, None]


def practical_to_teos(
    practical_salinity: np.ndarray,
    potential_temperature: np.ndarray,
    pressure: np.ndarray,
    longitude: np.ndarray,
    latitude: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert practical salinity and potential temperature to TEOS-10."""
    longitude_3d = np.asarray(longitude, dtype=np.float64)[None, None, :]
    latitude_3d = np.asarray(latitude, dtype=np.float64)[None, :, None]
    absolute_salinity = gsw.SA_from_SP(
        practical_salinity, pressure, longitude_3d, latitude_3d
    )
    conservative_temperature = gsw.CT_from_pt(
        absolute_salinity, potential_temperature
    )
    return absolute_salinity, conservative_temperature


def compute_steric_chunk(
    salinity: np.ndarray,
    temperature: np.ndarray,
    reference_absolute_salinity: np.ndarray,
    reference_conservative_temperature: np.ndarray,
    pressure: np.ndarray,
    pressure_thickness: np.ndarray,
    gravity: np.ndarray,
    longitude: np.ndarray,
    latitude: np.ndarray,
) -> dict[str, np.ndarray]:
    """Compute components for one depth x latitude x longitude chunk."""
    arrays = [
        np.asarray(salinity),
        np.asarray(temperature),
        np.asarray(reference_absolute_salinity),
        np.asarray(reference_conservative_temperature),
    ]
    if any(item.shape != arrays[0].shape for item in arrays[1:]):
        raise ValueError("current and reference arrays must have identical shapes")

    wet = np.logical_and.reduce([np.isfinite(item) for item in arrays])
    reappears_below_gap = np.any(
        wet & np.maximum.accumulate(~wet, axis=0), axis=0
    )
    column_valid = wet.any(axis=0) & ~reappears_below_gap

    sa, ct = practical_to_teos(
        arrays[0].astype(np.float64),
        arrays[1].astype(np.float64),
        pressure,
        longitude,
        latitude,
    )
    sa_ref = arrays[2].astype(np.float64)
    ct_ref = arrays[3].astype(np.float64)
    reference_volume = gsw.specvol(sa_ref, ct_ref, pressure)
    integrals = {
        "steric_total": gsw.specvol(sa, ct, pressure) - reference_volume,
        "thermosteric": gsw.specvol(sa_ref, ct, pressure) - reference_volume,
        "halosteric": gsw.specvol(sa, ct_ref, pressure) - reference_volume,
    }
    result: dict[str, np.ndarray] = {}
    for name, anomaly in integrals.items():
        values = np.sum(
            np.where(wet, anomaly * pressure_thickness / gravity, 0.0),
            axis=0,
        )
        values[~column_valid] = np.nan
        result[name] = values
    return result


def aggregate_to_one_degree(
    values: np.ndarray, latitude: np.ndarray, longitude: np.ndarray
) -> np.ndarray:
    """Area-weight a native 0.25 degree field into the agreed 1 degree grid."""
    values = np.asarray(values, dtype=np.float64)
    latitude = np.asarray(latitude, dtype=np.float64)
    longitude = np.asarray(longitude, dtype=np.float64)
    if values.shape != (latitude.size, longitude.size):
        raise ValueError("values shape must match latitude and longitude")

    latitude_bin = np.floor(latitude).astype(int) + 90
    longitude_bin = np.floor(longitude).astype(int) + 180
    weights = np.cos(np.deg2rad(latitude))[:, None] * np.ones(
        (1, longitude.size), dtype=np.float64
    )
    bin_index = latitude_bin[:, None] * 360 + longitude_bin[None, :]
    valid = (
        np.isfinite(values)
        & (latitude_bin[:, None] >= 0)
        & (latitude_bin[:, None] < 180)
        & (longitude_bin[None, :] >= 0)
        & (longitude_bin[None, :] < 360)
    )
    numerator = np.bincount(
        bin_index[valid],
        weights=(values * weights)[valid],
        minlength=180 * 360,
    )
    denominator = np.bincount(
        bin_index[valid],
        weights=weights[valid],
        minlength=180 * 360,
    )
    output = np.full(180 * 360, np.nan, dtype=np.float64)
    np.divide(numerator, denominator, out=output, where=denominator > 0)
    return output.reshape(180, 360)


def detail_indices(
    latitude: np.ndarray, longitude: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    west, east, south, north = DETAIL_BOUNDS
    latitude_index = np.flatnonzero((latitude >= south) & (latitude <= north))
    longitude_index = np.flatnonzero((longitude >= west) & (longitude <= east))
    if latitude_index.size == 0 or longitude_index.size == 0:
        raise ValueError("source grid does not cover the detailed region")
    return latitude_index, longitude_index


def _component_attributes() -> dict[str, dict[str, str]]:
    common = {
        "units": "m",
        "reference_period": "2003-01 to 2010-12",
        "vertical_extent": "full available water column",
    }
    return {
        "steric_total": {
            **common,
            "long_name": "Total steric sea-level anomaly",
        },
        "thermosteric": {
            **common,
            "long_name": "Thermosteric sea-level anomaly",
        },
        "halosteric": {
            **common,
            "long_name": "Halosteric sea-level anomaly",
        },
        "nonlinear_residual": {
            **common,
            "long_name": "Nonlinear closure residual",
            "description": "total - thermosteric - halosteric",
        },
    }


def validate_reference(path: Path) -> xr.Dataset:
    if not path.exists():
        raise FileNotFoundError(path)
    dataset = xr.open_dataset(path, engine="h5netcdf")
    required = {"absolute_salinity", "conservative_temperature"}
    missing = required.difference(dataset.data_vars)
    if missing:
        dataset.close()
        raise ValueError(f"{path}: missing reference variables {sorted(missing)}")
    expected_dimensions = ("depth", "latitude", "longitude")
    for name in required:
        if dataset[name].dims != expected_dimensions:
            dataset.close()
            raise ValueError(f"{path}: unexpected dimensions for {name}")
    return dataset


def build_reference(
    raw_directory: Path,
    output: Path,
    overwrite: bool = False,
    latitude_chunk_size: int = 16,
) -> None:
    """Build mean TEOS-10 SA/CT reference fields for 2003-2010."""
    if output.exists() and not overwrite:
        dataset = validate_reference(output)
        dataset.close()
        print(f"[reuse] {output}")
        return

    years = range(REFERENCE_START.year, REFERENCE_END.year + 1)
    sources = [
        validate_source_year(source_year_path(raw_directory, year), year)
        for year in years
    ]
    try:
        first = sources[0]
        depth = np.asarray(first.depth.values, dtype=np.float64)
        latitude = np.asarray(first.latitude.values, dtype=np.float64)
        longitude = np.asarray(first.longitude.values, dtype=np.float64)
        reference_shape = (depth.size, latitude.size, longitude.size)
        salinity_reference = np.full(reference_shape, np.nan, dtype=np.float32)
        temperature_reference = np.full(reference_shape, np.nan, dtype=np.float32)
        expected_count = sum(dataset.sizes["time"] for dataset in sources)

        for dataset in sources[1:]:
            for coordinate, expected in (
                ("depth", depth),
                ("latitude", latitude),
                ("longitude", longitude),
            ):
                if not np.array_equal(dataset[coordinate].values, expected):
                    raise ValueError(f"reference source {coordinate} grids differ")

        for start in range(0, latitude.size, latitude_chunk_size):
            stop = min(start + latitude_chunk_size, latitude.size)
            chunk_latitude = latitude[start:stop]
            pressure, _, _ = pressure_geometry(depth, chunk_latitude)
            shape = (depth.size, stop - start, longitude.size)
            salinity_sum = np.zeros(shape, dtype=np.float64)
            temperature_sum = np.zeros(shape, dtype=np.float64)
            count = np.zeros(shape, dtype=np.uint16)

            for dataset in sources:
                for time_index in range(dataset.sizes["time"]):
                    selection = {"time": time_index, "latitude": slice(start, stop)}
                    practical_salinity = dataset[SALINITY_VARIABLE].isel(**selection).values
                    potential_temperature = dataset[TEMPERATURE_VARIABLE].isel(**selection).values
                    absolute_salinity, conservative_temperature = practical_to_teos(
                        practical_salinity,
                        potential_temperature,
                        pressure,
                        longitude,
                        chunk_latitude,
                    )
                    valid = np.isfinite(absolute_salinity) & np.isfinite(
                        conservative_temperature
                    )
                    salinity_sum += np.where(valid, absolute_salinity, 0.0)
                    temperature_sum += np.where(valid, conservative_temperature, 0.0)
                    count += valid

            complete = count == expected_count
            chunk_salinity = np.full(shape, np.nan, dtype=np.float32)
            chunk_temperature = np.full(shape, np.nan, dtype=np.float32)
            np.divide(
                salinity_sum,
                expected_count,
                out=chunk_salinity,
                where=complete,
            )
            np.divide(
                temperature_sum,
                expected_count,
                out=chunk_temperature,
                where=complete,
            )
            salinity_reference[:, start:stop, :] = chunk_salinity
            temperature_reference[:, start:stop, :] = chunk_temperature
            print(f"[reference] latitude {start}:{stop} / {latitude.size}")

        reference = xr.Dataset(
            data_vars={
                "absolute_salinity": (
                    ("depth", "latitude", "longitude"),
                    salinity_reference,
                    {"units": "g kg-1", "standard_name": "sea_water_absolute_salinity"},
                ),
                "conservative_temperature": (
                    ("depth", "latitude", "longitude"),
                    temperature_reference,
                    {"units": "degree_Celsius"},
                ),
            },
            coords={
                "depth": first.depth,
                "latitude": first.latitude,
                "longitude": first.longitude,
            },
            attrs={
                "title": "Copernicus full-depth steric reference hydrography",
                "source_dataset": DATASET_ID,
                "source_dataset_version": DATASET_VERSION,
                "reference_period": "2003-01 to 2010-12",
                "reference_month_count": expected_count,
                "method": "TEOS-10 mean SA and CT; only cells valid in all reference months",
            },
        )
        _atomic_write(reference, output)
        print(f"[created] {output}")
    finally:
        for dataset in sources:
            dataset.close()


def validate_year_chunk(
    path: Path,
    year: int,
    expected_latitude: np.ndarray,
    expected_longitude: np.ndarray,
) -> xr.Dataset:
    if not path.exists():
        raise FileNotFoundError(path)
    dataset = xr.open_dataset(path, engine="h5netcdf")
    required = set(COMPONENTS) | {"nonlinear_residual"}
    missing = required.difference(dataset.data_vars)
    if missing:
        dataset.close()
        raise ValueError(f"{path}: missing components {sorted(missing)}")
    actual_months = pd.DatetimeIndex(dataset.time.values).to_period("M")
    if not actual_months.equals(expected_months(year).to_period("M")):
        dataset.close()
        raise ValueError(f"{path}: unexpected time coordinate")
    if not np.array_equal(dataset.latitude.values, expected_latitude):
        dataset.close()
        raise ValueError(f"{path}: unexpected latitude grid")
    if not np.array_equal(dataset.longitude.values, expected_longitude):
        dataset.close()
        raise ValueError(f"{path}: unexpected longitude grid")
    return dataset


def _year_dataset(
    values: dict[str, np.ndarray],
    time: pd.DatetimeIndex,
    latitude: np.ndarray,
    longitude: np.ndarray,
    resolution: str,
) -> xr.Dataset:
    attributes = _component_attributes()
    data_vars = {
        name: (
            ("time", "latitude", "longitude"),
            data.astype(np.float32),
            attributes[name],
        )
        for name, data in values.items()
    }
    return xr.Dataset(
        data_vars=data_vars,
        coords={
            "time": time,
            "latitude": latitude,
            "longitude": longitude,
        },
        attrs={
            "title": "Copernicus full-depth steric sea-level components",
            "source_dataset": DATASET_ID,
            "source_dataset_version": DATASET_VERSION,
            "spatial_resolution": resolution,
            "method": "TEOS-10 specific-volume anomaly integrated over pressure",
            "reference_hydrography": "mean SA and CT for 2003-01 to 2010-12",
        },
    )


def process_year(
    raw_directory: Path,
    reference_path: Path,
    chunk_directory: Path,
    year: int,
    overwrite: bool = False,
    latitude_chunk_size: int = 16,
) -> None:
    """Calculate one year's global 1 degree and regional 0.25 degree fields."""
    global_path = global_year_path(chunk_directory, year)
    detail_path = detail_year_path(chunk_directory, year)
    source = validate_source_year(source_year_path(raw_directory, year), year)
    source_latitude = np.asarray(source.latitude.values, dtype=np.float64)
    source_longitude = np.asarray(source.longitude.values, dtype=np.float64)
    detail_latitude_index, detail_longitude_index = detail_indices(
        source_latitude, source_longitude
    )
    expected_detail_latitude = source_latitude[detail_latitude_index]
    expected_detail_longitude = source_longitude[detail_longitude_index]
    if global_path.exists() and detail_path.exists() and not overwrite:
        global_chunk: xr.Dataset | None = None
        detail_chunk: xr.Dataset | None = None
        try:
            global_chunk = validate_year_chunk(
                global_path, year, GLOBAL_LATITUDE, GLOBAL_LONGITUDE
            )
            detail_chunk = validate_year_chunk(
                detail_path,
                year,
                expected_detail_latitude,
                expected_detail_longitude,
            )
            print(f"[reuse] {global_path}")
            print(f"[reuse] {detail_path}")
        finally:
            if global_chunk is not None:
                global_chunk.close()
            if detail_chunk is not None:
                detail_chunk.close()
            source.close()
        return

    reference: xr.Dataset | None = None
    try:
        reference = validate_reference(reference_path)
        depth = np.asarray(source.depth.values, dtype=np.float64)
        latitude = np.asarray(source.latitude.values, dtype=np.float64)
        longitude = np.asarray(source.longitude.values, dtype=np.float64)
        for coordinate, expected in (
            ("depth", depth),
            ("latitude", latitude),
            ("longitude", longitude),
        ):
            if not np.array_equal(reference[coordinate].values, expected):
                raise ValueError(f"reference and source {coordinate} grids differ")
        reference_salinity = reference["absolute_salinity"].values
        reference_temperature = reference["conservative_temperature"].values

        detail_latitude = latitude[detail_latitude_index]
        detail_longitude = longitude[detail_longitude_index]
        month_count = source.sizes["time"]
        global_values = {
            name: np.full((month_count, 180, 360), np.nan, dtype=np.float32)
            for name in COMPONENTS
        }
        detail_values = {
            name: np.full(
                (
                    month_count,
                    detail_latitude.size,
                    detail_longitude.size,
                ),
                np.nan,
                dtype=np.float32,
            )
            for name in COMPONENTS
        }

        for time_index in range(month_count):
            native = {
                name: np.full(
                    (latitude.size, longitude.size), np.nan, dtype=np.float32
                )
                for name in COMPONENTS
            }
            for start in range(0, latitude.size, latitude_chunk_size):
                stop = min(start + latitude_chunk_size, latitude.size)
                chunk_latitude = latitude[start:stop]
                pressure, pressure_thickness, gravity = pressure_geometry(
                    depth, chunk_latitude
                )
                selection = {"time": time_index, "latitude": slice(start, stop)}
                calculated = compute_steric_chunk(
                    source[SALINITY_VARIABLE].isel(**selection).values,
                    source[TEMPERATURE_VARIABLE].isel(**selection).values,
                    reference_salinity[:, start:stop, :],
                    reference_temperature[:, start:stop, :],
                    pressure,
                    pressure_thickness,
                    gravity,
                    longitude,
                    chunk_latitude,
                )
                for name in COMPONENTS:
                    native[name][start:stop, :] = calculated[name]

            for name in COMPONENTS:
                global_values[name][time_index] = aggregate_to_one_degree(
                    native[name], latitude, longitude
                )
                detail_values[name][time_index] = native[name][
                    np.ix_(detail_latitude_index, detail_longitude_index)
                ]
            print(
                f"[steric] {year} month {time_index + 1}/{month_count} calculated"
            )

        for values in (global_values, detail_values):
            values["nonlinear_residual"] = (
                values["steric_total"]
                - values["thermosteric"]
                - values["halosteric"]
            )
        time = expected_months(year)
        global_dataset = _year_dataset(
            global_values, time, GLOBAL_LATITUDE, GLOBAL_LONGITUDE, "1 degree"
        )
        detail_dataset = _year_dataset(
            detail_values,
            time,
            detail_latitude,
            detail_longitude,
            "0.25 degree",
        )
        _atomic_write(global_dataset, global_path)
        _atomic_write(detail_dataset, detail_path)
        print(f"[created] {global_path}")
        print(f"[created] {detail_path}")
    finally:
        source.close()
        if reference is not None:
            reference.close()


def rebase_components(dataset: xr.Dataset) -> xr.Dataset:
    """Rebase components to 2003-2010 and enforce one fixed valid mask."""
    reference_period = dataset.sel(
        time=slice(REFERENCE_START, REFERENCE_END + pd.offsets.MonthEnd(1))
    )
    rebased = dataset.copy(deep=True)
    for name in COMPONENTS:
        rebased[name] = dataset[name] - reference_period[name].mean(
            "time", skipna=False
        )

    common_valid = np.ones(
        (dataset.sizes["latitude"], dataset.sizes["longitude"]), dtype=bool
    )
    for name in COMPONENTS:
        common_valid &= np.isfinite(rebased[name].values).all(axis=0)
    for name in COMPONENTS:
        rebased[name] = rebased[name].where(common_valid)
    rebased["nonlinear_residual"] = (
        rebased["steric_total"]
        - rebased["thermosteric"]
        - rebased["halosteric"]
    )
    rebased["valid_ocean_mask"] = (
        ("latitude", "longitude"),
        common_valid,
        {
            "long_name": "Fixed ocean mask valid for every output month",
            "flag_values": np.array([0, 1], dtype=np.int8),
        },
    )
    return rebased


def area_weighted_mean(
    values: np.ndarray, latitude: np.ndarray
) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    weights = np.cos(np.deg2rad(np.asarray(latitude, dtype=np.float64)))[
        None, :, None
    ]
    valid = np.isfinite(values)
    numerator = np.sum(np.where(valid, values * weights, 0.0), axis=(1, 2))
    denominator = np.sum(
        np.where(valid, np.broadcast_to(weights, values.shape), 0.0),
        axis=(1, 2),
    )
    output = np.full(values.shape[0], np.nan, dtype=np.float64)
    np.divide(numerator, denominator, out=output, where=denominator > 0)
    return output


def combine_year_chunks(
    chunk_directory: Path,
    output: Path,
    kind: str,
    overwrite: bool = False,
) -> None:
    if output.exists() and not overwrite:
        print(f"[reuse] {output}")
        return
    if kind not in {"global", "detail"}:
        raise ValueError("kind must be global or detail")

    opened: list[xr.Dataset] = []
    detail_latitude: np.ndarray | None = None
    detail_longitude: np.ndarray | None = None
    try:
        for year in range(START.year, END.year + 1):
            path = (
                global_year_path(chunk_directory, year)
                if kind == "global"
                else detail_year_path(chunk_directory, year)
            )
            if kind == "global":
                expected_latitude = GLOBAL_LATITUDE
                expected_longitude = GLOBAL_LONGITUDE
            else:
                if detail_latitude is None or detail_longitude is None:
                    probe = xr.open_dataset(path, engine="h5netcdf")
                    detail_latitude = np.asarray(probe.latitude.values)
                    detail_longitude = np.asarray(probe.longitude.values)
                    probe.close()
                expected_latitude = detail_latitude
                expected_longitude = detail_longitude
            opened.append(
                validate_year_chunk(
                    path, year, expected_latitude, expected_longitude
                )
            )
        combined = xr.concat(opened, dim="time").load()
        actual = pd.DatetimeIndex(combined.time.values).to_period("M")
        wanted = all_expected_months().to_period("M")
        if not actual.equals(wanted):
            raise ValueError("combined chunks do not cover the expected 244 months")

        final = rebase_components(combined)
        for name in COMPONENTS:
            mean_name = f"{name}_ocean_mean"
            final[mean_name] = (
                "time",
                area_weighted_mean(final[name].values, final.latitude.values),
                {
                    "units": "m",
                    "long_name": f"Area-weighted mean of {name}",
                },
            )
        final["nonlinear_residual_ocean_mean"] = (
            final["steric_total_ocean_mean"]
            - final["thermosteric_ocean_mean"]
            - final["halosteric_ocean_mean"]
        )
        final.attrs.update(
            {
                "reference_period": "2003-01 to 2010-12",
                "time_coverage_start": "2003-01",
                "time_coverage_end": "2023-04",
                "fixed_mask": "cells valid for all 244 months and all components",
                "closure": (
                    "steric_total = thermosteric + halosteric + "
                    "nonlinear_residual"
                ),
            }
        )
        _atomic_write(final, output)
        print(f"[created] {output}")
    finally:
        for dataset in opened:
            dataset.close()


def _existing_parent(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def dry_run(raw_directory: Path, reference_only: bool = False) -> None:
    months = (
        pd.date_range(REFERENCE_START, REFERENCE_END, freq="MS")
        if reference_only
        else all_expected_months()
    )
    full_month_count = len(all_expected_months())
    requested_gib = 133.78 * len(months) / full_month_count
    transfer_gib = 139.39 * len(months) / full_month_count
    requested_gb = requested_gib * (2**30) / 1.0e9
    transfer_gb = transfer_gib * (2**30) / 1.0e9
    free_gb = shutil.disk_usage(_existing_parent(raw_directory)).free / 1.0e9
    print("Copernicus full-depth steric build plan")
    print(f"  dataset: {DATASET_ID}, version {DATASET_VERSION}")
    print(f"  period: {months[0]:%Y-%m} to {months[-1]:%Y-%m} ({len(months)} months)")
    print("  native grid: 0.25 degree, 75 depth levels")
    print(
        f"  requested file volume: about {requested_gib:.2f} GiB "
        f"({requested_gb:.2f} GB)"
    )
    print(
        f"  expected transfer: about {transfer_gib:.2f} GiB "
        f"({transfer_gb:.2f} GB)"
    )
    print(f"  free space near raw directory: {free_gb:.1f} GB")
    print("  raw yearly files are retained unless the user removes them later")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build full-depth Copernicus steric sea-level products."
    )
    parser.add_argument("--raw-directory", type=Path, default=DEFAULT_RAW_DIRECTORY)
    parser.add_argument(
        "--chunk-directory", type=Path, default=DEFAULT_CHUNK_DIRECTORY
    )
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument(
        "--global-output", type=Path, default=DEFAULT_GLOBAL_OUTPUT
    )
    parser.add_argument(
        "--detail-output", type=Path, default=DEFAULT_DETAIL_OUTPUT
    )
    parser.add_argument(
        "--latitude-chunk-size",
        type=int,
        default=16,
        help="Native latitude rows processed at once.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing downloads and derived files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print volume and disk information without downloading.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--download-only",
        action="store_true",
        help="Download and validate yearly source files, then stop.",
    )
    mode.add_argument(
        "--skip-download",
        action="store_true",
        help="Use already downloaded and validated yearly source files.",
    )
    parser.add_argument(
        "--reference-only",
        action="store_true",
        help=(
            "Download 2003-2010, build the reference hydrography, and stop "
            "before monthly steric processing."
        ),
    )
    parser.add_argument(
        "--process-year",
        type=int,
        help=(
            "Process one already downloaded year with the existing reference "
            "and stop before combining final files."
        ),
    )
    parser.add_argument(
        "--remove-year-chunks",
        action="store_true",
        help="Remove derived yearly chunks after both final files are written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    if args.latitude_chunk_size < 1:
        raise ValueError("--latitude-chunk-size must be positive")
    if args.reference_only and args.download_only:
        raise ValueError("--reference-only and --download-only cannot be combined")
    if args.process_year is not None and (
        args.reference_only or args.download_only
    ):
        raise ValueError(
            "--process-year cannot be combined with --reference-only "
            "or --download-only"
        )
    if args.dry_run:
        dry_run(args.raw_directory, reference_only=args.reference_only)
        return

    if args.process_year is not None:
        if not START.year <= args.process_year <= END.year:
            raise ValueError(
                f"--process-year must be between {START.year} and {END.year}"
            )
        source = validate_source_year(
            source_year_path(args.raw_directory, args.process_year),
            args.process_year,
        )
        source.close()
        reference = validate_reference(args.reference)
        reference.close()
        process_year(
            args.raw_directory,
            args.reference,
            args.chunk_directory,
            args.process_year,
            overwrite=args.overwrite,
            latitude_chunk_size=args.latitude_chunk_size,
        )
        print(
            f"{args.process_year} steric pilot created; final files were not combined."
        )
        return

    years = (
        range(REFERENCE_START.year, REFERENCE_END.year + 1)
        if args.reference_only
        else range(START.year, END.year + 1)
    )
    if not args.skip_download:
        free_gb = (
            shutil.disk_usage(_existing_parent(args.raw_directory)).free / 1.0e9
        )
        if free_gb < MIN_FREE_SPACE_GB:
            raise RuntimeError(
                f"At least {MIN_FREE_SPACE_GB:.0f} GB free space is required; "
                f"{free_gb:.1f} GB is available."
            )
        for year in years:
            download_year(
                source_year_path(args.raw_directory, year),
                year,
                overwrite=args.overwrite,
            )
    else:
        for year in years:
            dataset = validate_source_year(
                source_year_path(args.raw_directory, year), year
            )
            dataset.close()

    if args.download_only:
        print("All source years downloaded and validated; processing not started.")
        return

    build_reference(
        args.raw_directory,
        args.reference,
        overwrite=args.overwrite,
        latitude_chunk_size=args.latitude_chunk_size,
    )
    if args.reference_only:
        print("Reference hydrography created; monthly steric processing not started.")
        return
    for year in years:
        process_year(
            args.raw_directory,
            args.reference,
            args.chunk_directory,
            year,
            overwrite=args.overwrite,
            latitude_chunk_size=args.latitude_chunk_size,
        )
    combine_year_chunks(
        args.chunk_directory,
        args.global_output,
        "global",
        overwrite=args.overwrite,
    )
    combine_year_chunks(
        args.chunk_directory,
        args.detail_output,
        "detail",
        overwrite=args.overwrite,
    )

    if args.remove_year_chunks:
        for year in years:
            for path in (
                global_year_path(args.chunk_directory, year),
                detail_year_path(args.chunk_directory, year),
            ):
                if path.exists():
                    path.unlink()
        print("[removed] derived yearly chunks; raw Copernicus files were retained")


if __name__ == "__main__":
    main()
