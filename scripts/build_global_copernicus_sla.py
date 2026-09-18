from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import copernicusmarine
import numpy as np
import pandas as pd
import xarray as xr


DATASET_ID = "cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1M-m"
DATASET_VERSION = "202411"
START_YEAR = 1993
END_YEAR = 2025
COARSEN_FACTOR = 8
CAUSE_START = "2003-01-01"
CAUSE_END = "2023-04-01"
CAUSE_REFERENCE_START = "2003-01-01"
CAUSE_REFERENCE_END = "2010-12-01"
FINAL_FILENAME = "copernicus_sla_global_1deg_monthly_199301_202512.nc"


def expected_months(year: int) -> pd.DatetimeIndex:
    return pd.date_range(f"{year}-01-01", f"{year}-12-01", freq="MS")


def validate_source_year(path: Path, year: int) -> None:
    with xr.open_dataset(path, engine="h5netcdf") as dataset:
        if "sla" not in dataset:
            raise ValueError(f"{path.name}: sla 변수가 없습니다.")
        if dataset["sla"].attrs.get("units") != "m":
            raise ValueError(f"{path.name}: sla 단위가 m가 아닙니다.")
        times = pd.DatetimeIndex(pd.to_datetime(dataset["time"].values))
        if not times.equals(expected_months(year)):
            raise ValueError(f"{path.name}: {year}년 월자료가 완전하지 않습니다.")
        if dataset.sizes.get("latitude") != 1440 or dataset.sizes.get("longitude") != 2880:
            raise ValueError(f"{path.name}: 예상한 전 지구 0.125도 격자가 아닙니다.")


def validate_processed_year(path: Path, year: int) -> bool:
    if not path.exists():
        return False
    try:
        with xr.open_dataset(path, engine="h5netcdf") as dataset:
            times = pd.DatetimeIndex(pd.to_datetime(dataset["time"].values))
            return (
                "sla" in dataset
                and times.equals(expected_months(year))
                and dataset.sizes.get("latitude") == 180
                and dataset.sizes.get("longitude") == 360
            )
    except (OSError, ValueError):
        return False


def area_weighted_coarsen(source_path: Path, output_path: Path, year: int) -> None:
    with xr.open_dataset(source_path, engine="h5netcdf") as source:
        sla = source["sla"].transpose("time", "latitude", "longitude")
        latitude_weights = np.cos(np.deg2rad(source["latitude"]))
        valid = sla.notnull()
        weighted_values = xr.where(valid, sla * latitude_weights, 0.0)
        valid_weights = xr.where(valid, latitude_weights, 0.0)

        numerator = weighted_values.coarsen(
            latitude=COARSEN_FACTOR,
            longitude=COARSEN_FACTOR,
            boundary="exact",
        ).sum()
        denominator = valid_weights.coarsen(
            latitude=COARSEN_FACTOR,
            longitude=COARSEN_FACTOR,
            boundary="exact",
        ).sum()
        coarse = (numerator / denominator).where(denominator > 0).astype("float32")
        coarse.name = "sla"
        coarse.attrs = {
            "long_name": "Sea level anomaly, 1-degree area-weighted mean",
            "units": "m",
            "source_variable": "sla",
            "source_resolution_degrees": 0.125,
            "coarsening_method": "cos(latitude)-weighted mean of valid 0.125-degree cells",
            "reference_period": "1993-01 through 2012-12 (Copernicus source definition)",
        }
        output = coarse.to_dataset()
        output.attrs = {
            "title": f"Copernicus global monthly SLA at 1 degree ({year})",
            "source_dataset_id": DATASET_ID,
            "source_dataset_version": DATASET_VERSION,
            "processing_status": "intermediate yearly chunk",
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(".part.nc")
        output.to_netcdf(
            temporary,
            engine="h5netcdf",
            encoding={
                "sla": {
                    "zlib": True,
                    "complevel": 5,
                    "shuffle": True,
                    "dtype": "float32",
                    "chunksizes": (12, 45, 90),
                }
            },
        )
        temporary.replace(output_path)


def download_year(raw_path: Path, year: int, overwrite: bool) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists() and not overwrite:
        try:
            validate_source_year(raw_path, year)
            print(f"[{year}] 이미 받은 원자료를 사용합니다.", flush=True)
            return
        except (OSError, ValueError):
            raw_path.unlink()

    copernicusmarine.subset(
        dataset_id=DATASET_ID,
        dataset_version=DATASET_VERSION,
        variables=["sla"],
        start_datetime=f"{year}-01-01",
        end_datetime=f"{year}-12-01",
        minimum_longitude=-180.0,
        maximum_longitude=180.0,
        minimum_latitude=-90.0,
        maximum_latitude=90.0,
        coordinates_selection_method="inside",
        output_directory=raw_path.parent,
        output_filename=raw_path.name,
        netcdf_compression_level=1,
        overwrite=True,
    )
    validate_source_year(raw_path, year)


def build_year(
    raw_directory: Path,
    chunk_directory: Path,
    year: int,
    overwrite: bool,
) -> Path:
    chunk_path = chunk_directory / f"copernicus_sla_global_1deg_{year}.nc"
    if validate_processed_year(chunk_path, year) and not overwrite:
        print(f"[{year}] 검증된 1도 자료가 있어 건너뜁니다.", flush=True)
        return chunk_path

    raw_path = raw_directory / f"copernicus_sla_global_0125_{year}.nc"
    print(f"[{year}] 전 지구 월자료를 내려받습니다.", flush=True)
    download_year(raw_path, year, overwrite=overwrite)
    print(f"[{year}] 면적 가중 평균으로 1도 격자를 만듭니다.", flush=True)
    area_weighted_coarsen(raw_path, chunk_path, year)
    if not validate_processed_year(chunk_path, year):
        raise ValueError(f"{year}년 1도 변환 결과 검증에 실패했습니다.")
    raw_path.unlink()
    print(f"[{year}] 변환 완료 - 검증 후 0.125도 임시 파일을 지웠습니다.", flush=True)
    return chunk_path


def build_final(chunk_paths: list[Path], output_path: Path) -> dict[str, object]:
    yearly_datasets: list[xr.Dataset] = []
    for path in chunk_paths:
        with xr.open_dataset(path, engine="h5netcdf") as dataset:
            yearly_datasets.append(dataset[["sla"]].load())

    combined = xr.concat(yearly_datasets, dim="time").sortby("time")
    times = pd.DatetimeIndex(pd.to_datetime(combined["time"].values))
    expected = pd.date_range(f"{START_YEAR}-01-01", f"{END_YEAR}-12-01", freq="MS")
    if not times.equals(expected):
        raise ValueError("최종 자료의 월 좌표가 1993-01~2025-12와 일치하지 않습니다.")

    cause_period = combined["sla"].sel(time=slice(CAUSE_START, CAUSE_END))
    reference = combined["sla"].sel(
        time=slice(CAUSE_REFERENCE_START, CAUSE_REFERENCE_END)
    ).mean("time", skipna=True).astype("float32")
    reference.name = "cause_reference_mean"
    reference.attrs = {
        "long_name": "Mean SLA used to rebase the causes comparison",
        "units": "m",
        "reference_period": "2003-01 through 2010-12",
    }

    complete_mask = cause_period.notnull().all("time").astype("uint8")
    complete_mask.name = "sla_complete_mask"
    complete_mask.attrs = {
        "long_name": "SLA is valid in every month of the GRACE comparison period",
        "flag_values": np.array([0, 1], dtype="uint8"),
        "flag_meanings": "incomplete complete",
        "period": "2003-01 through 2023-04",
        "note": "Candidate SLA mask only; intersect with the regridded GRACE ocean mask before comparison.",
    }

    final = xr.Dataset(
        {
            "sla": combined["sla"].astype("float32"),
            "cause_reference_mean": reference,
            "sla_complete_mask": complete_mask,
        }
    )
    final["sla"].attrs.update(
        {
            "long_name": "Sea level anomaly, 1-degree area-weighted mean",
            "units": "m",
            "source_variable": "sla",
            "source_resolution_degrees": 0.125,
            "output_resolution_degrees": 1.0,
            "coarsening_method": "cos(latitude)-weighted mean of valid 0.125-degree cells",
            "reference_period": "1993-01 through 2012-12 (Copernicus source definition)",
        }
    )
    final.attrs = {
        "title": "Copernicus global monthly SLA, area-weighted to 1 degree",
        "source_product": "SEALEVEL_GLO_PHY_L4_MY_008_047",
        "source_dataset_id": DATASET_ID,
        "source_dataset_version": DATASET_VERSION,
        "source_resolution_degrees": 0.125,
        "output_resolution_degrees": 1.0,
        "source_reference_period": "1993-01 through 2012-12",
        "causes_comparison_reference_period": "2003-01 through 2010-12",
        "processing_method": "yearly download; cos(latitude)-weighted 8x8-cell mean",
        "created_utc": datetime.now(UTC).isoformat(),
        "processing_status": "complete",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".part.nc")
    final.to_netcdf(
        temporary,
        engine="h5netcdf",
        encoding={
            "sla": {
                "zlib": True,
                "complevel": 5,
                "shuffle": True,
                "dtype": "float32",
                "chunksizes": (12, 45, 90),
            },
            "cause_reference_mean": {
                "zlib": True,
                "complevel": 5,
                "shuffle": True,
                "dtype": "float32",
            },
            "sla_complete_mask": {
                "zlib": True,
                "complevel": 5,
                "shuffle": True,
                "dtype": "uint8",
            },
        },
    )
    temporary.replace(output_path)

    with xr.open_dataset(output_path, engine="h5netcdf") as check:
        if check.sizes != {"time": 396, "latitude": 180, "longitude": 360}:
            raise ValueError(f"최종 자료 크기가 예상과 다릅니다: {dict(check.sizes)}")
        valid_any = check["sla"].sel(time=slice(CAUSE_START, CAUSE_END)).notnull().any("time")
        complete = check["sla_complete_mask"].astype(bool)
        lat_weights = np.cos(np.deg2rad(check["latitude"]))
        any_area = float(lat_weights.broadcast_like(valid_any).where(valid_any).sum().values)
        complete_area = float(lat_weights.broadcast_like(complete).where(complete).sum().values)
        summary = {
            "path": str(output_path.resolve()),
            "size_mb": round(output_path.stat().st_size / 1024**2, 2),
            "time_start": str(pd.Timestamp(check["time"].values[0]).date()),
            "time_end": str(pd.Timestamp(check["time"].values[-1]).date()),
            "months": int(check.sizes["time"]),
            "latitude_count": int(check.sizes["latitude"]),
            "longitude_count": int(check.sizes["longitude"]),
            "latitude_range": [float(check["latitude"].min()), float(check["latitude"].max())],
            "longitude_range": [float(check["longitude"].min()), float(check["longitude"].max())],
            "complete_sla_cells_200301_202304": int(complete.sum().values),
            "complete_sla_area_fraction_of_any_valid_ocean": round(complete_area / any_area, 6),
        }
    return summary


def remove_empty_directory(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copernicus 전 지구 0.125도 월평균 SLA를 연도별로 받아 1도로 변환합니다."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/observed") / FINAL_FILENAME,
    )
    parser.add_argument(
        "--raw-directory",
        type=Path,
        default=Path("data/source/observed/copernicus/_global_yearly_raw"),
    )
    parser.add_argument(
        "--chunk-directory",
        type=Path,
        default=Path("data/processed/observed/_global_1deg_yearly"),
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--keep-chunks",
        action="store_true",
        help="최종 파일 검증 뒤에도 연도별 1도 중간 파일을 남깁니다.",
    )
    args = parser.parse_args()

    free_bytes = shutil.disk_usage(args.output.resolve().anchor).free
    if free_bytes < 2 * 1024**3:
        raise OSError("안전한 연도별 처리를 위해 최소 2 GB의 여유 공간이 필요합니다.")

    chunk_paths = [
        build_year(
            raw_directory=args.raw_directory,
            chunk_directory=args.chunk_directory,
            year=year,
            overwrite=args.overwrite,
        )
        for year in range(START_YEAR, END_YEAR + 1)
    ]
    print("연도별 자료를 하나의 1993~2025 월자료로 합칩니다.", flush=True)
    summary = build_final(chunk_paths, args.output)

    if not args.keep_chunks:
        for path in chunk_paths:
            path.unlink()
        remove_empty_directory(args.chunk_directory)
        remove_empty_directory(args.raw_directory)

    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
