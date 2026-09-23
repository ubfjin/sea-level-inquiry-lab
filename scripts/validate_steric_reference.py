"""Create reproducible scientific QC outputs for the steric reference field."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import gsw
import matplotlib
import numpy as np
import xarray as xr

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT_INPUT = Path("data/processed/steric/reference_200301_201012_025deg.nc")
DEFAULT_OUTPUT_DIRECTORY = Path("data/processed/steric/qc")
PROFILE_TARGETS = {
    "Kuroshio Extension": (35.0, 145.0),
    "Equatorial Pacific": (0.0, -160.0),
    "North Atlantic": (45.0, -30.0),
    "Southern Ocean": (-55.0, 0.0),
}


def nearest_wet_column(
    latitude: np.ndarray,
    longitude: np.ndarray,
    valid: np.ndarray,
    target_latitude: float,
    target_longitude: float,
) -> tuple[int, int]:
    """Return the nearest column with surface water and at least 1 km depth."""
    depth_count = valid.sum(axis=0)
    candidates = depth_count >= 25
    latitude_distance = latitude[:, None] - target_latitude
    longitude_distance = (
        (longitude[None, :] - target_longitude + 180.0) % 360.0
    ) - 180.0
    distance = latitude_distance**2 + (
        longitude_distance * np.cos(np.deg2rad(target_latitude))
    ) ** 2
    distance[~candidates] = np.inf
    if not np.isfinite(distance).any():
        raise ValueError(f"No wet column near {target_latitude}, {target_longitude}")
    return np.unravel_index(np.argmin(distance), distance.shape)


def save_surface_maps(
    output: Path,
    longitude: np.ndarray,
    latitude: np.ndarray,
    surface_salinity: np.ndarray,
    surface_temperature: np.ndarray,
) -> None:
    figure, axes = plt.subplots(2, 1, figsize=(14, 8), constrained_layout=True)
    panels = (
        (
            surface_salinity,
            "Reference surface Absolute Salinity",
            "g kg$^{-1}$",
            "viridis",
        ),
        (
            surface_temperature,
            "Reference surface Conservative Temperature",
            "°C",
            "plasma",
        ),
    )
    for axis, (values, title, units, colour_map) in zip(axes, panels):
        finite = values[np.isfinite(values)]
        lower, upper = np.nanpercentile(finite, [1.0, 99.0])
        image = axis.pcolormesh(
            longitude,
            latitude,
            values,
            shading="auto",
            cmap=colour_map,
            vmin=lower,
            vmax=upper,
            rasterized=True,
        )
        axis.contour(
            longitude,
            latitude,
            np.isfinite(values).astype(float),
            levels=[0.5],
            colors="0.25",
            linewidths=0.3,
        )
        axis.set(title=title, xlabel="Longitude", ylabel="Latitude")
        axis.set_xlim(-180, 180)
        axis.set_ylim(-80, 90)
        axis.grid(color="0.75", linewidth=0.3, alpha=0.5)
        colour_bar = figure.colorbar(image, ax=axis, pad=0.015, shrink=0.9)
        colour_bar.set_label(units)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def save_profiles(
    output: Path,
    depth: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    salinity: np.ndarray,
    temperature: np.ndarray,
    valid: np.ndarray,
) -> dict[str, dict[str, float | int]]:
    figure, axes = plt.subplots(1, 2, figsize=(10, 7), sharey=True)
    report: dict[str, dict[str, float | int]] = {}
    for label, (target_latitude, target_longitude) in PROFILE_TARGETS.items():
        latitude_index, longitude_index = nearest_wet_column(
            latitude,
            longitude,
            valid,
            target_latitude,
            target_longitude,
        )
        profile_valid = valid[:, latitude_index, longitude_index]
        profile_depth = depth[profile_valid]
        profile_salinity = salinity[profile_valid, latitude_index, longitude_index]
        profile_temperature = temperature[
            profile_valid, latitude_index, longitude_index
        ]
        sigma_zero = gsw.sigma0(profile_salinity, profile_temperature)
        strong_inversions = int(np.sum(np.diff(sigma_zero) < -0.05))
        actual_latitude = float(latitude[latitude_index])
        actual_longitude = float(longitude[longitude_index])
        axes[0].plot(profile_salinity, profile_depth, label=label, linewidth=1.7)
        axes[1].plot(profile_temperature, profile_depth, label=label, linewidth=1.7)
        report[label] = {
            "latitude": actual_latitude,
            "longitude": actual_longitude,
            "valid_levels": int(profile_valid.sum()),
            "deepest_level_m": float(profile_depth[-1]),
            "surface_absolute_salinity_g_kg": float(profile_salinity[0]),
            "surface_conservative_temperature_c": float(profile_temperature[0]),
            "sigma0_inversions_below_minus_0_05": strong_inversions,
        }

    axes[0].set(
        title="Absolute Salinity profiles",
        xlabel="Absolute Salinity (g kg$^{-1}$)",
        ylabel="Depth (m)",
    )
    axes[1].set(
        title="Conservative Temperature profiles",
        xlabel="Conservative Temperature (°C)",
    )
    for axis in axes:
        axis.invert_yaxis()
        axis.grid(color="0.8", linewidth=0.5)
    axes[1].legend(loc="lower right", fontsize=8)
    figure.suptitle("2003–2010 reference hydrography")
    figure.tight_layout()
    figure.savefig(output, dpi=150)
    plt.close(figure)
    return report


def save_validity(
    output: Path,
    depth: np.ndarray,
    longitude: np.ndarray,
    latitude: np.ndarray,
    valid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    maximum_depth = np.full(valid.shape[1:], np.nan, dtype=np.float32)
    for depth_index, depth_value in enumerate(depth):
        maximum_depth[valid[depth_index]] = depth_value
    surface_count = int(valid[0].sum())
    fraction = valid.sum(axis=(1, 2)) / surface_count

    figure, axes = plt.subplots(
        1,
        2,
        figsize=(14, 4.8),
        gridspec_kw={"width_ratios": [2.3, 1.0]},
        constrained_layout=True,
    )
    image = axes[0].pcolormesh(
        longitude,
        latitude,
        maximum_depth,
        shading="auto",
        cmap="viridis",
        vmin=0,
        vmax=float(depth[-1]),
        rasterized=True,
    )
    axes[0].contour(
        longitude,
        latitude,
        np.isfinite(maximum_depth).astype(float),
        levels=[0.5],
        colors="0.2",
        linewidths=0.3,
    )
    axes[0].set(
        title="Deepest valid reference level",
        xlabel="Longitude",
        ylabel="Latitude",
        xlim=(-180, 180),
        ylim=(-80, 90),
    )
    axes[0].grid(color="0.75", linewidth=0.3, alpha=0.5)
    colour_bar = figure.colorbar(image, ax=axes[0], pad=0.015)
    colour_bar.set_label("Depth (m)")

    axes[1].plot(fraction * 100.0, depth, color="#176b87", linewidth=2)
    axes[1].invert_yaxis()
    axes[1].set(
        title="Valid ocean area by depth",
        xlabel="Share of surface-ocean cells (%)",
        ylabel="Depth (m)",
        xlim=(0, 100),
    )
    axes[1].grid(color="0.8", linewidth=0.5)
    figure.savefig(output, dpi=120)
    plt.close(figure)
    return maximum_depth, fraction


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    with xr.open_dataset(args.input, engine="h5netcdf") as dataset:
        required = {"absolute_salinity", "conservative_temperature"}
        missing = required.difference(dataset.data_vars)
        if missing:
            raise ValueError(f"Missing variables: {sorted(missing)}")
        depth = np.asarray(dataset.depth.values, dtype=np.float64)
        latitude = np.asarray(dataset.latitude.values, dtype=np.float64)
        longitude = np.asarray(dataset.longitude.values, dtype=np.float64)
        salinity = np.asarray(dataset.absolute_salinity.values, dtype=np.float32)
        temperature = np.asarray(
            dataset.conservative_temperature.values, dtype=np.float32
        )
        attributes = dict(dataset.attrs)

    valid = np.isfinite(salinity) & np.isfinite(temperature)
    mask_mismatch = int(
        np.count_nonzero(np.isfinite(salinity) != np.isfinite(temperature))
    )
    reappears_below_gap = valid & np.maximum.accumulate(~valid, axis=0)
    gap_columns = int(np.any(reappears_below_gap, axis=0).sum())

    surface_path = args.output_directory / "reference_surface_maps.png"
    profile_path = args.output_directory / "reference_profiles.png"
    validity_path = args.output_directory / "reference_validity.png"
    save_surface_maps(
        surface_path,
        longitude,
        latitude,
        salinity[0],
        temperature[0],
    )
    profiles = save_profiles(
        profile_path,
        depth,
        latitude,
        longitude,
        salinity,
        temperature,
        valid,
    )
    maximum_depth, depth_fraction = save_validity(
        validity_path, depth, longitude, latitude, valid
    )

    finite_salinity = salinity[valid]
    finite_temperature = temperature[valid]
    report = {
        "input": str(args.input),
        "reference_period": attributes.get("reference_period"),
        "reference_month_count": int(attributes.get("reference_month_count", 0)),
        "dimensions": {
            "depth": int(depth.size),
            "latitude": int(latitude.size),
            "longitude": int(longitude.size),
        },
        "coordinate_ranges": {
            "depth_m": [float(depth[0]), float(depth[-1])],
            "latitude": [float(latitude[0]), float(latitude[-1])],
            "longitude": [float(longitude[0]), float(longitude[-1])],
        },
        "validity": {
            "finite_3d_cells": int(valid.sum()),
            "surface_ocean_cells": int(valid[0].sum()),
            "mask_mismatch_cells": mask_mismatch,
            "columns_with_vertical_gaps": gap_columns,
            "maximum_valid_depth_m": float(np.nanmax(maximum_depth)),
            "deepest_level_area_fraction": float(depth_fraction[-1]),
        },
        "ranges": {
            "absolute_salinity_g_kg": [
                float(finite_salinity.min()),
                float(finite_salinity.max()),
            ],
            "conservative_temperature_c": [
                float(finite_temperature.min()),
                float(finite_temperature.max()),
            ],
            "surface_absolute_salinity_percentile_1_99": [
                float(np.nanpercentile(salinity[0], 1)),
                float(np.nanpercentile(salinity[0], 99)),
            ],
            "surface_conservative_temperature_percentile_1_99": [
                float(np.nanpercentile(temperature[0], 1)),
                float(np.nanpercentile(temperature[0], 99)),
            ],
        },
        "profiles": profiles,
        "checks": {
            "coordinates_strictly_increasing": bool(
                np.all(np.diff(depth) > 0)
                and np.all(np.diff(latitude) > 0)
                and np.all(np.diff(longitude) > 0)
            ),
            "salinity_and_temperature_masks_match": mask_mismatch == 0,
            "valid_columns_are_vertically_contiguous": gap_columns == 0,
            "absolute_salinity_in_broad_physical_range": bool(
                finite_salinity.min() >= 0 and finite_salinity.max() <= 50
            ),
            "conservative_temperature_in_broad_physical_range": bool(
                finite_temperature.min() >= -5 and finite_temperature.max() <= 45
            ),
        },
        "figures": [str(surface_path), str(profile_path), str(validity_path)],
    }
    report_path = args.output_directory / "reference_qc_summary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
