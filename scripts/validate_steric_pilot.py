"""Validate and plot a one-year steric processing pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import xarray as xr

matplotlib.use("Agg")
import matplotlib.pyplot as plt


COMPONENTS = ("steric_total", "thermosteric", "halosteric")
DEFAULT_GLOBAL = Path("data/processed/steric/chunks/steric_global_1deg_2003.nc")
DEFAULT_DETAIL = Path(
    "data/processed/steric/chunks/steric_kuroshio_025deg_2003.nc"
)
DEFAULT_OUTPUT_DIRECTORY = Path("data/processed/steric/qc/pilot_2003")


def area_weighted_mean(values: np.ndarray, latitude: np.ndarray) -> np.ndarray:
    weights = np.cos(np.deg2rad(latitude))[None, :, None]
    valid = np.isfinite(values)
    numerator = np.sum(np.where(valid, values * weights, 0.0), axis=(1, 2))
    denominator = np.sum(
        np.where(valid, np.broadcast_to(weights, values.shape), 0.0),
        axis=(1, 2),
    )
    return numerator / denominator


def validate_dataset(dataset: xr.Dataset) -> dict[str, object]:
    required = set(COMPONENTS) | {"nonlinear_residual"}
    missing = required.difference(dataset.data_vars)
    if missing:
        raise ValueError(f"Missing variables: {sorted(missing)}")
    arrays = {name: dataset[name].values for name in required}
    common = np.logical_and.reduce(
        [np.isfinite(arrays[name]) for name in COMPONENTS]
    )
    closure = (
        arrays["steric_total"]
        - arrays["thermosteric"]
        - arrays["halosteric"]
        - arrays["nonlinear_residual"]
    )
    maximum_closure = float(np.nanmax(np.abs(closure)))
    mask_is_fixed = bool(np.all(common == common[0]))
    return {
        "time_count": int(dataset.sizes["time"]),
        "latitude_count": int(dataset.sizes["latitude"]),
        "longitude_count": int(dataset.sizes["longitude"]),
        "valid_ocean_cells": int(common[0].sum()),
        "fixed_monthly_mask": mask_is_fixed,
        "maximum_closure_error_m": maximum_closure,
    }


def component_statistics(dataset: xr.Dataset) -> dict[str, object]:
    statistics: dict[str, object] = {}
    for name in (*COMPONENTS, "nonlinear_residual"):
        values = dataset[name].values * 1000.0
        minimum_index = np.unravel_index(np.nanargmin(values), values.shape)
        maximum_index = np.unravel_index(np.nanargmax(values), values.shape)

        def location(index: tuple[int, int, int]) -> dict[str, object]:
            time_index, latitude_index, longitude_index = index
            return {
                "date": str(pd.Timestamp(dataset.time.values[time_index]).date()),
                "latitude": float(dataset.latitude.values[latitude_index]),
                "longitude": float(dataset.longitude.values[longitude_index]),
                "value_mm": float(values[index]),
            }

        statistics[name] = {
            "minimum": location(minimum_index),
            "maximum": location(maximum_index),
            "percentile_1_99_mm": [
                float(np.nanpercentile(values, 1)),
                float(np.nanpercentile(values, 99)),
            ],
        }
    return statistics


def save_component_maps(
    dataset: xr.Dataset,
    output: Path,
    time_index: int,
    title_prefix: str,
) -> None:
    fields = [dataset[name].isel(time=time_index).values * 1000.0 for name in COMPONENTS]
    scale = float(
        np.nanpercentile(
            np.abs(np.concatenate([field[np.isfinite(field)] for field in fields])),
            98.5,
        )
    )
    figure, axes = plt.subplots(
        3, 1, figsize=(13, 9), constrained_layout=True, sharex=True, sharey=True
    )
    titles = ("Total steric", "Thermosteric", "Halosteric")
    for axis, field, title in zip(axes, fields, titles):
        image = axis.pcolormesh(
            dataset.longitude,
            dataset.latitude,
            field,
            shading="auto",
            cmap="RdBu_r",
            vmin=-scale,
            vmax=scale,
            rasterized=True,
        )
        axis.contour(
            dataset.longitude,
            dataset.latitude,
            np.isfinite(field).astype(float),
            levels=[0.5],
            colors="0.25",
            linewidths=0.3,
        )
        axis.set(title=title, ylabel="Latitude")
        axis.grid(color="0.75", linewidth=0.3, alpha=0.5)
    axes[-1].set_xlabel("Longitude")
    date = pd.Timestamp(dataset.time.values[time_index]).strftime("%Y-%m")
    figure.suptitle(f"{title_prefix} steric components · {date}")
    colour_bar = figure.colorbar(image, ax=axes, pad=0.012, shrink=0.85)
    colour_bar.set_label("Sea-level anomaly (mm)")
    figure.savefig(output, dpi=120)
    plt.close(figure)


def save_detail_comparison(dataset: xr.Dataset, output: Path) -> None:
    first_index = 1
    second_index = 8
    fields = [
        dataset.steric_total.isel(time=first_index).values * 1000.0,
        dataset.steric_total.isel(time=second_index).values * 1000.0,
    ]
    scale = float(
        np.nanpercentile(
            np.abs(np.concatenate([field[np.isfinite(field)] for field in fields])),
            98.5,
        )
    )
    figure, axes = plt.subplots(
        1, 2, figsize=(12, 4.6), constrained_layout=True, sharex=True, sharey=True
    )
    for axis, field, time_index in zip(
        axes, fields, (first_index, second_index)
    ):
        image = axis.pcolormesh(
            dataset.longitude,
            dataset.latitude,
            field,
            shading="auto",
            cmap="RdBu_r",
            vmin=-scale,
            vmax=scale,
            rasterized=True,
        )
        axis.contour(
            dataset.longitude,
            dataset.latitude,
            np.isfinite(field).astype(float),
            levels=[0.5],
            colors="0.25",
            linewidths=0.35,
        )
        date = pd.Timestamp(dataset.time.values[time_index]).strftime("%Y-%m")
        axis.set(title=f"Total steric · {date}", xlabel="Longitude")
        axis.grid(color="0.75", linewidth=0.3, alpha=0.5)
    axes[0].set_ylabel("Latitude")
    colour_bar = figure.colorbar(image, ax=axes, pad=0.015, shrink=0.85)
    colour_bar.set_label("Sea-level anomaly (mm)")
    figure.savefig(output, dpi=140)
    plt.close(figure)


def save_area_means(
    global_dataset: xr.Dataset,
    detail_dataset: xr.Dataset,
    output: Path,
) -> dict[str, dict[str, list[float]]]:
    figure, axes = plt.subplots(
        2, 1, figsize=(10, 7), sharex=True, constrained_layout=True
    )
    colours = {
        "steric_total": "#172c54",
        "thermosteric": "#cf5c36",
        "halosteric": "#008f8c",
    }
    labels = {
        "steric_total": "Total",
        "thermosteric": "Thermosteric",
        "halosteric": "Halosteric",
    }
    results: dict[str, dict[str, list[float]]] = {}
    for axis, dataset, region in (
        (axes[0], global_dataset, "Global 1° valid ocean"),
        (axes[1], detail_dataset, "Kuroshio region 0.25°"),
    ):
        dates = pd.DatetimeIndex(dataset.time.values)
        region_values: dict[str, list[float]] = {}
        for name in COMPONENTS:
            mean = (
                area_weighted_mean(
                    dataset[name].values, dataset.latitude.values
                )
                * 1000.0
            )
            axis.plot(
                dates,
                mean,
                color=colours[name],
                marker="o",
                markersize=3,
                linewidth=1.7,
                label=labels[name],
            )
            region_values[name] = [float(value) for value in mean]
        axis.axhline(0, color="0.45", linewidth=0.7)
        axis.set(title=region, ylabel="Area mean (mm)")
        axis.grid(color="0.8", linewidth=0.5)
        results[region] = region_values
    axes[0].legend(ncol=3, loc="upper center")
    axes[-1].set_xlabel("Month")
    figure.savefig(output, dpi=150)
    plt.close(figure)
    return results


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--global-input", type=Path, default=DEFAULT_GLOBAL)
    parser.add_argument("--detail-input", type=Path, default=DEFAULT_DETAIL)
    parser.add_argument(
        "--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    with xr.open_dataset(args.global_input, engine="h5netcdf") as source:
        global_dataset = source.load()
    with xr.open_dataset(args.detail_input, engine="h5netcdf") as source:
        detail_dataset = source.load()

    global_validation = validate_dataset(global_dataset)
    detail_validation = validate_dataset(detail_dataset)
    global_map = args.output_directory / "global_components_2003_09.png"
    detail_map = args.output_directory / "kuroshio_total_2003_02_09.png"
    means_plot = args.output_directory / "area_mean_components_2003.png"
    save_component_maps(
        global_dataset,
        global_map,
        time_index=8,
        title_prefix="Global 1°",
    )
    save_detail_comparison(detail_dataset, detail_map)
    area_means = save_area_means(global_dataset, detail_dataset, means_plot)

    report = {
        "global": {
            "input": str(args.global_input),
            "validation": global_validation,
            "statistics": component_statistics(global_dataset),
        },
        "detail": {
            "input": str(args.detail_input),
            "validation": detail_validation,
            "statistics": component_statistics(detail_dataset),
        },
        "area_mean_components_mm": area_means,
        "figures": [str(global_map), str(detail_map), str(means_plot)],
    }
    report_path = args.output_directory / "pilot_qc_summary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
