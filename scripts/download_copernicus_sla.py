from __future__ import annotations

import argparse
import json
from pathlib import Path

import copernicusmarine
import numpy as np
import pandas as pd
import xarray as xr


DATASET_ID = "cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1M-m"
DATASET_VERSION = "202411"
FILENAME = "copernicus_sla_korea_0125_monthly_199301_202512.nc"
BOUNDS = {
    "minimum_longitude": 115.0,
    "maximum_longitude": 135.0,
    "minimum_latitude": 25.0,
    "maximum_latitude": 45.0,
}


def validate(path: Path) -> dict[str, object]:
    with xr.open_dataset(path, engine="h5netcdf") as dataset:
        if "sla" not in dataset:
            raise ValueError("다운로드 파일에 sla 변수가 없습니다.")
        if dataset["sla"].attrs.get("units") != "m":
            raise ValueError("sla 단위가 m가 아닙니다.")
        times = pd.DatetimeIndex(pd.to_datetime(dataset["time"].values))
        expected = pd.date_range(times.min(), times.max(), freq="MS")
        if len(times) != len(expected) or not np.array_equal(times.values, expected.values):
            raise ValueError("월자료에 빠진 시점이 있습니다.")
        return {
            "dataset_id": DATASET_ID,
            "dataset_version": DATASET_VERSION,
            "variable": "sla",
            "unit": "m",
            "time_start": times.min().strftime("%Y-%m-%d"),
            "time_end": times.max().strftime("%Y-%m-%d"),
            "months": len(times),
            "latitude_count": int(dataset.sizes["latitude"]),
            "longitude_count": int(dataset.sizes["longitude"]),
            "latitude_range": [
                float(dataset["latitude"].min()),
                float(dataset["latitude"].max()),
            ],
            "longitude_range": [
                float(dataset["longitude"].min()),
                float(dataset["longitude"].max()),
            ],
            "resolution_degrees": float(np.median(np.diff(dataset["longitude"].values))),
            "valid_fraction": float(dataset["sla"].notnull().mean().values),
            "reference_period": "1993-01 through 2012-12 (Copernicus source definition)",
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="한반도 주변 Copernicus 월평균 SLA를 내려받고 검증합니다."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("data/source/observed/copernicus"),
    )
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)

    copernicusmarine.subset(
        dataset_id=DATASET_ID,
        dataset_version=DATASET_VERSION,
        variables=["sla"],
        start_datetime="1993-01-01",
        end_datetime="2025-12-01",
        coordinates_selection_method="inside",
        output_directory=args.output_directory,
        output_filename=FILENAME,
        netcdf_compression_level=5,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        **BOUNDS,
    )
    if args.dry_run:
        return

    path = args.output_directory / FILENAME
    print(json.dumps(validate(path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
