from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


DEFAULT_COMPARISON = Path(
    "data/processed/causes/observed_grace_aligned_1deg_monthly_200301_202304.nc"
)
DEFAULT_STERIC = Path(
    "data/processed/steric/steric_monthly_global_1deg.nc"
)
DEFAULT_OUTPUT = Path(
    "data/processed/causes/observed_grace_steric_aligned_1deg_monthly_200301_202304.nc"
)
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


def _require(dataset: xr.Dataset, names: set[str], label: str) -> None:
    missing = names.difference(dataset.variables)
    if missing:
        raise ValueError(f"{label} 파일에 필요한 변수가 없습니다: {sorted(missing)}")


def _validate_coordinates(comparison: xr.Dataset, steric: xr.Dataset) -> None:
    expected = pd.date_range(START, END, freq="MS")
    comparison_time = month_starts(comparison["time"].values)
    steric_time = month_starts(steric["time"].values)
    if not comparison_time.equals(expected):
        raise ValueError("SLA·GRACE 비교 파일의 월 좌표가 완전하지 않습니다.")
    if not steric_time.equals(expected):
        raise ValueError("Steric 파일의 월 좌표가 완전하지 않습니다.")
    for coordinate in ("latitude", "longitude"):
        if not np.array_equal(
            comparison[coordinate].values,
            steric[coordinate].values,
        ):
            raise ValueError(f"SLA·GRACE와 Steric의 {coordinate} 격자가 다릅니다.")


def build(
    comparison_path: Path,
    steric_path: Path,
    output_path: Path,
) -> dict[str, object]:
    if not comparison_path.exists():
        raise FileNotFoundError(f"SLA·GRACE 비교 파일이 없습니다: {comparison_path}")
    if not steric_path.exists():
        raise FileNotFoundError(f"Steric 파일이 없습니다: {steric_path}")

    with xr.open_dataset(comparison_path, engine="h5netcdf") as source:
        _require(
            source,
            {
                "observed_sla",
                "grace_fingerprint",
                "common_ocean_mask",
                "grace_source_available",
            },
            "SLA·GRACE 비교",
        )
        comparison = source[
            [
                "observed_sla",
                "grace_fingerprint",
                "common_ocean_mask",
                "grace_source_available",
            ]
        ].load()

    with xr.open_dataset(steric_path, engine="h5netcdf") as source:
        _require(source, {"steric_total", "valid_ocean_mask"}, "Steric")
        steric = source[["steric_total", "valid_ocean_mask"]].load()

    comparison = comparison.assign_coords(
        time=month_starts(comparison["time"].values)
    )
    steric = steric.assign_coords(time=month_starts(steric["time"].values))
    _validate_coordinates(comparison, steric)

    grace_available = comparison["grace_source_available"].astype("uint8")
    comparison_mask = comparison["common_ocean_mask"].astype(bool)
    steric_mask = (
        steric["valid_ocean_mask"].astype(bool)
        & steric["steric_total"].notnull().all("time")
    )
    common_mask = (comparison_mask & steric_mask).astype("uint8")
    common_boolean = common_mask.astype(bool)

    observed = comparison["observed_sla"].where(common_boolean).astype("float32")
    grace = comparison["grace_fingerprint"].where(common_boolean).astype("float32")
    steric_total = (
        steric["steric_total"].where(common_boolean) * 1000.0
    ).astype("float32")
    component_sum = (steric_total + grace).where(grace_available == 1).astype("float32")
    residual = (observed - component_sum).where(grace_available == 1).astype("float32")

    observed_mean = area_weighted_mean(observed, common_boolean).astype("float32")
    steric_mean = area_weighted_mean(steric_total, common_boolean).astype("float32")
    grace_mean = area_weighted_mean(grace, common_boolean).where(
        grace_available == 1
    ).astype("float32")
    component_sum_mean = (steric_mean + grace_mean).where(
        grace_available == 1
    ).astype("float32")
    residual_mean = (observed_mean - component_sum_mean).where(
        grace_available == 1
    ).astype("float32")

    observed.name = "observed_sla"
    observed.attrs = {
        "long_name": "Observed sea-level anomaly on the fixed three-way comparison mask",
        "units": "mm",
        "reference_period": "2003-01 through 2010-12 monthly mean removed per grid cell",
        "source": "Copernicus Marine SEALEVEL_GLO_PHY_L4_MY_008_047",
    }
    steric_total.name = "steric_total"
    steric_total.attrs = {
        "long_name": "Full-depth total steric sea-level anomaly",
        "units": "mm",
        "reference_period": "2003-01 through 2010-12 monthly mean removed per grid cell",
        "source": "Copernicus Marine GLOBAL_MULTIYEAR_PHY_ENS_001_031",
        "method": "TEOS-10 full-depth specific-volume anomaly integral",
    }
    grace.name = "grace_fingerprint"
    grace.attrs = {
        "long_name": "GRACE ocean-mass relative sea-level fingerprint aligned to SLA cell centres",
        "units": "mm",
        "reference_period": "2003-01 through 2010-12 monthly mean removed per grid cell",
    }
    component_sum.name = "component_sum"
    component_sum.attrs = {
        "long_name": "Total steric plus GRACE ocean-mass sea-level anomaly",
        "units": "mm",
        "formula": "steric_total + grace_fingerprint",
    }
    residual.name = "residual"
    residual.attrs = {
        "long_name": "Observed sea-level anomaly minus total steric and GRACE components",
        "units": "mm",
        "formula": "observed_sla - steric_total - grace_fingerprint",
    }
    common_mask.name = "common_ocean_mask"
    common_mask.attrs = {
        "long_name": "Fixed ocean mask valid for SLA, total steric, and available GRACE months",
        "flag_values": np.array([0, 1], dtype="uint8"),
        "flag_meanings": "excluded included",
        "period": "2003-01 through 2023-04",
    }

    for data, name, long_name in (
        (observed_mean, "observed_ocean_mean", "Area-weighted observed SLA mean"),
        (steric_mean, "steric_ocean_mean", "Area-weighted total steric mean"),
        (grace_mean, "grace_ocean_mean", "Area-weighted GRACE fingerprint mean"),
        (
            component_sum_mean,
            "component_sum_ocean_mean",
            "Area-weighted total steric plus GRACE mean",
        ),
        (residual_mean, "residual_ocean_mean", "Area-weighted unexplained residual mean"),
    ):
        data.name = name
        data.attrs = {"long_name": long_name, "units": "mm"}

    grace_available.name = "grace_source_available"
    grace_available.attrs = comparison["grace_source_available"].attrs

    output = xr.Dataset(
        {
            "observed_sla": observed,
            "steric_total": steric_total,
            "grace_fingerprint": grace,
            "component_sum": component_sum,
            "residual": residual,
            "common_ocean_mask": common_mask,
            "observed_ocean_mean": observed_mean,
            "steric_ocean_mean": steric_mean,
            "grace_ocean_mean": grace_mean,
            "component_sum_ocean_mean": component_sum_mean,
            "residual_ocean_mean": residual_mean,
            "grace_source_available": grace_available,
        }
    )
    output.attrs = {
        "title": "Aligned observed SLA, total steric, and GRACE comparison",
        "summary": "Copernicus observed SLA, full-depth total steric sea level, and GRACE ocean-mass fingerprint on one fixed 1-degree ocean mask.",
        "comparison_period": "2003-01 through 2023-04",
        "reference_period": "2003-01 through 2010-12",
        "grid": "1-degree cell centres: latitude -89.5 to 89.5; longitude -179.5 to 179.5",
        "mask_policy": "intersection of fixed SLA-GRACE comparison mask and fixed total-steric ocean mask",
        "mission_gap": "2017-06 through 2018-05 retained as missing for GRACE-dependent variables",
        "processing_status": "complete",
        "created_utc": datetime.now(UTC).isoformat(),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".part.nc")
    if temporary.exists():
        temporary.unlink()
    grid_encoding = {
        "zlib": True,
        "complevel": 5,
        "shuffle": True,
        "dtype": "float32",
        "chunksizes": (12, 45, 90),
    }
    output.to_netcdf(
        temporary,
        engine="h5netcdf",
        encoding={
            "observed_sla": grid_encoding,
            "steric_total": grid_encoding,
            "grace_fingerprint": grid_encoding,
            "component_sum": grid_encoding,
            "residual": grid_encoding,
            "common_ocean_mask": {
                "zlib": True,
                "complevel": 5,
                "shuffle": True,
                "dtype": "uint8",
            },
            "observed_ocean_mean": {"zlib": True, "complevel": 5, "dtype": "float32"},
            "steric_ocean_mean": {"zlib": True, "complevel": 5, "dtype": "float32"},
            "grace_ocean_mean": {"zlib": True, "complevel": 5, "dtype": "float32"},
            "component_sum_ocean_mean": {"zlib": True, "complevel": 5, "dtype": "float32"},
            "residual_ocean_mean": {"zlib": True, "complevel": 5, "dtype": "float32"},
            "grace_source_available": {"zlib": True, "complevel": 5, "dtype": "uint8"},
        },
    )
    temporary.replace(output_path)

    with xr.open_dataset(output_path, engine="h5netcdf") as check:
        reference = check.sel(time=slice(REFERENCE_START, REFERENCE_END))
        reference_errors = {
            name: float(np.nanmax(np.abs(reference[name].mean("time").values)))
            for name in ("observed_sla", "steric_total", "grace_fingerprint")
        }
        closure = (
            check["observed_sla"]
            - check["steric_total"]
            - check["grace_fingerprint"]
            - check["residual"]
        )
        return {
            "path": str(output_path.resolve()),
            "size_mb": round(output_path.stat().st_size / 1024**2, 2),
            "months": int(check.sizes["time"]),
            "common_ocean_cells": int(check["common_ocean_mask"].sum().values),
            "available_grace_months": int(check["grace_source_available"].sum().values),
            "mission_gap_months": int((check["grace_source_available"] == 0).sum().values),
            "maximum_reference_mean_abs_mm": reference_errors,
            "maximum_closure_error_mm": float(np.nanmax(np.abs(closure.values))),
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SLA·GRACE 공통 비교 자료에 전 수심 Total steric을 결합합니다."
    )
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON)
    parser.add_argument("--steric", type=Path, default=DEFAULT_STERIC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = build(args.comparison, args.steric, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
