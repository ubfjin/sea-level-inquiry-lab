from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


DEFAULT_SLA = Path("data/processed/observed/copernicus_sla_global_1deg_monthly_199301_202512.nc")
DEFAULT_GRACE = Path("data/processed/barystatic/grace_ocean_mass_fingerprint_1deg_monthly_200301_202304.nc")
DEFAULT_OUTPUT = Path("data/processed/causes/observed_grace_aligned_1deg_monthly_200301_202304.nc")
START = "2003-01-01"
END = "2023-04-01"
REFERENCE_START = "2003-01-01"
REFERENCE_END = "2010-12-01"


def month_starts(values: np.ndarray) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(values)).to_period("M").to_timestamp()


def area_weighted_mean(
    data: xr.DataArray,
    mask: xr.DataArray,
) -> xr.DataArray:
    weights = np.cos(np.deg2rad(data["latitude"]))
    spatial_weights = weights.broadcast_like(mask).where(mask)
    denominator = spatial_weights.sum(("latitude", "longitude"))
    return (data * spatial_weights).sum(
        ("latitude", "longitude"),
        skipna=True,
    ) / denominator


def build(sla_path: Path, grace_path: Path, output_path: Path) -> dict[str, object]:
    if not sla_path.exists():
        raise FileNotFoundError(f"Copernicus SLA 파일이 없습니다: {sla_path}")
    if not grace_path.exists():
        raise FileNotFoundError(f"GRACE 파일이 없습니다: {grace_path}")

    with xr.open_dataset(sla_path, engine="h5netcdf") as source:
        required = {"sla", "cause_reference_mean", "sla_complete_mask"}
        missing = required.difference(source.variables)
        if missing:
            raise ValueError(f"SLA 파일에 필요한 변수가 없습니다: {sorted(missing)}")
        sla = source[["sla", "cause_reference_mean", "sla_complete_mask"]].sel(
            time=slice(START, END)
        ).load()

    sla = sla.assign_coords(time=month_starts(sla["time"].values))
    expected = pd.date_range(START, END, freq="MS")
    if not month_starts(sla["time"].values).equals(expected):
        raise ValueError("SLA 비교 기간의 월 좌표가 완전하지 않습니다.")

    observed = ((sla["sla"] - sla["cause_reference_mean"]) * 1000.0).astype("float32")
    observed.name = "observed_sla"
    sla_mask = sla["sla_complete_mask"].astype(bool)

    with xr.open_dataset(grace_path, engine="h5netcdf") as source:
        required = {"grace_fingerprint", "land_mask", "source_available"}
        missing = required.difference(source.variables)
        if missing:
            raise ValueError(f"GRACE 파일에 필요한 변수가 없습니다: {sorted(missing)}")
        grace = source[["grace_fingerprint", "land_mask", "source_available"]].load()

    grace = grace.rename({"lat": "latitude", "lon": "longitude"})
    grace = grace.assign_coords(time=month_starts(grace["time"].values))
    if not month_starts(grace["time"].values).equals(expected):
        raise ValueError("GRACE 비교 기간의 월 좌표가 완전하지 않습니다.")

    source_available = grace["source_available"].astype("uint8")
    ocean = (grace["land_mask"] == 0).astype("float32")
    source_values = np.asarray(
        grace["grace_fingerprint"].where(ocean == 1, 0.0).fillna(0.0).values,
        dtype=np.float32,
    )
    source_ocean = np.asarray(ocean.values, dtype=np.float32)

    southwest = source_values[:, :-1, :]
    northwest = source_values[:, 1:, :]
    southeast = np.roll(southwest, -1, axis=2)
    northeast = np.roll(northwest, -1, axis=2)
    numerator = southwest + northwest + southeast + northeast

    ocean_southwest = source_ocean[:-1, :]
    ocean_northwest = source_ocean[1:, :]
    ocean_southeast = np.roll(ocean_southwest, -1, axis=1)
    ocean_northeast = np.roll(ocean_northwest, -1, axis=1)
    denominator = (
        ocean_southwest
        + ocean_northwest
        + ocean_southeast
        + ocean_northeast
    )
    aligned_values = np.full(numerator.shape, np.nan, dtype=np.float32)
    np.divide(
        numerator,
        denominator[None, :, :],
        out=aligned_values,
        where=denominator[None, :, :] > 0,
    )
    aligned_grace = xr.DataArray(
        aligned_values,
        dims=("time", "latitude", "longitude"),
        coords={
            "time": grace["time"],
            "latitude": observed["latitude"],
            "longitude": observed["longitude"],
        },
    ).where(source_available == 1).astype("float32")

    target_ocean = xr.DataArray(
        denominator >= 2,
        dims=("latitude", "longitude"),
        coords={
            "latitude": observed["latitude"],
            "longitude": observed["longitude"],
        },
    )
    available_grace = aligned_grace.where(source_available == 1, drop=True)
    grace_complete = available_grace.notnull().all("time")
    common_mask = (sla_mask & target_ocean & grace_complete).astype("uint8")
    common_boolean = common_mask.astype(bool)

    observed = observed.where(common_boolean)
    aligned_grace = aligned_grace.where(common_boolean)
    observed_mean = area_weighted_mean(observed, common_boolean).astype("float32")
    grace_mean = area_weighted_mean(aligned_grace, common_boolean).where(
        source_available == 1
    ).astype("float32")

    observed.attrs = {
        "long_name": "Observed sea-level anomaly on the fixed comparison ocean mask",
        "units": "mm",
        "reference_period": "2003-01 through 2010-12 monthly mean removed per grid cell",
        "source": "Copernicus Marine SEALEVEL_GLO_PHY_L4_MY_008_047",
    }
    aligned_grace.name = "grace_fingerprint"
    aligned_grace.attrs = {
        "long_name": "GRACE ocean-mass relative sea-level fingerprint aligned to SLA cell centres",
        "units": "mm",
        "reference_period": "2003-01 through 2010-12 monthly mean removed per grid cell",
        "spatial_alignment": "normalized four-node interpolation using ocean source nodes only; periodic longitude",
    }
    common_mask.name = "common_ocean_mask"
    common_mask.attrs = {
        "long_name": "Fixed ocean mask valid for both observed SLA and aligned GRACE",
        "flag_values": np.array([0, 1], dtype="uint8"),
        "flag_meanings": "excluded included",
        "period": "2003-01 through 2023-04",
    }
    observed_mean.name = "observed_ocean_mean"
    observed_mean.attrs = {
        "long_name": "Area-weighted observed SLA mean on the fixed comparison mask",
        "units": "mm",
    }
    grace_mean.name = "grace_ocean_mean"
    grace_mean.attrs = {
        "long_name": "Area-weighted GRACE fingerprint mean on the fixed comparison mask",
        "units": "mm",
    }
    source_available.name = "grace_source_available"
    source_available.attrs = {
        "long_name": "GRACE or GRACE-FO source availability",
        "flag_values": np.array([0, 1], dtype="uint8"),
        "flag_meanings": "mission_gap source_available",
    }

    output = xr.Dataset(
        {
            "observed_sla": observed,
            "grace_fingerprint": aligned_grace,
            "common_ocean_mask": common_mask,
            "observed_ocean_mean": observed_mean,
            "grace_ocean_mean": grace_mean,
            "grace_source_available": source_available,
        }
    )
    output.attrs = {
        "title": "Aligned observed SLA and GRACE ocean-mass comparison",
        "summary": "Copernicus observed SLA and the completed GRACE fingerprint on one fixed 1-degree ocean mask.",
        "comparison_period": "2003-01 through 2023-04",
        "reference_period": "2003-01 through 2010-12",
        "grid": "1-degree cell centres: latitude -89.5 to 89.5; longitude -179.5 to 179.5",
        "grace_alignment": "periodic normalized four-node interpolation; at least two of four source nodes must be ocean",
        "mask_policy": "intersection of complete SLA cells and regridded GRACE ocean cells; fixed for all months",
        "mission_gap": "2017-06 through 2018-05 retained as missing; no temporal interpolation",
        "processing_status": "complete",
        "created_utc": datetime.now(UTC).isoformat(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".part.nc")
    output.to_netcdf(
        temporary,
        engine="h5netcdf",
        encoding={
            "observed_sla": {"zlib": True, "complevel": 5, "shuffle": True, "dtype": "float32", "chunksizes": (12, 45, 90)},
            "grace_fingerprint": {"zlib": True, "complevel": 5, "shuffle": True, "dtype": "float32", "chunksizes": (12, 45, 90)},
            "common_ocean_mask": {"zlib": True, "complevel": 5, "shuffle": True, "dtype": "uint8"},
            "observed_ocean_mean": {"zlib": True, "complevel": 5, "shuffle": True, "dtype": "float32"},
            "grace_ocean_mean": {"zlib": True, "complevel": 5, "shuffle": True, "dtype": "float32"},
            "grace_source_available": {"zlib": True, "complevel": 5, "shuffle": True, "dtype": "uint8"},
        },
    )
    temporary.replace(output_path)

    with xr.open_dataset(output_path, engine="h5netcdf") as check:
        reference = check.sel(time=slice(REFERENCE_START, REFERENCE_END))
        observed_reference_abs = float(np.nanmax(np.abs(reference["observed_sla"].mean("time").values)))
        grace_reference_abs = float(np.nanmax(np.abs(reference["grace_fingerprint"].mean("time").values)))
        weights = np.cos(np.deg2rad(check["latitude"]))
        sla_area = float(weights.broadcast_like(sla_mask).where(sla_mask).sum().values)
        common = check["common_ocean_mask"].astype(bool)
        common_area = float(weights.broadcast_like(common).where(common).sum().values)
        return {
            "path": str(output_path.resolve()),
            "size_mb": round(output_path.stat().st_size / 1024**2, 2),
            "months": int(check.sizes["time"]),
            "available_grace_months": int(check["grace_source_available"].sum().values),
            "mission_gap_months": int((check["grace_source_available"] == 0).sum().values),
            "common_ocean_cells": int(common.sum().values),
            "common_area_fraction_of_complete_sla": round(common_area / sla_area, 6),
            "maximum_observed_reference_mean_abs_mm": observed_reference_abs,
            "maximum_grace_reference_mean_abs_mm": grace_reference_abs,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copernicus SLA와 GRACE를 하나의 고정 1도 해양 격자로 정렬합니다."
    )
    parser.add_argument("--sla", type=Path, default=DEFAULT_SLA)
    parser.add_argument("--grace", type=Path, default=DEFAULT_GRACE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = build(args.sla, args.grace, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
