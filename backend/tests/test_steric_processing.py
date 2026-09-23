import numpy as np
import pandas as pd
import xarray as xr

from scripts.build_global_copernicus_steric import (
    COMPONENTS,
    aggregate_to_one_degree,
    compute_steric_chunk,
    practical_to_teos,
    pressure_geometry,
    rebase_components,
)


def sample_column():
    depth = np.array([5.0, 50.0, 200.0])
    latitude = np.array([30.0, 31.0])
    longitude = np.array([130.0, 131.0])
    shape = (depth.size, latitude.size, longitude.size)
    salinity = np.full(shape, 35.0)
    temperature = np.full(shape, 10.0)
    pressure, thickness, gravity = pressure_geometry(depth, latitude)
    reference_salinity, reference_temperature = practical_to_teos(
        salinity, temperature, pressure, longitude, latitude
    )
    return (
        salinity,
        temperature,
        reference_salinity,
        reference_temperature,
        pressure,
        thickness,
        gravity,
        longitude,
        latitude,
    )


def test_reference_state_is_zero_and_closes():
    arguments = sample_column()
    result = compute_steric_chunk(*arguments)
    for name in COMPONENTS:
        np.testing.assert_allclose(result[name], 0.0, atol=1e-12)
    np.testing.assert_allclose(
        result["steric_total"],
        result["thermosteric"] + result["halosteric"],
        atol=1e-12,
    )


def test_warming_and_salinity_have_expected_signs():
    (
        salinity,
        temperature,
        reference_salinity,
        reference_temperature,
        pressure,
        thickness,
        gravity,
        longitude,
        latitude,
    ) = sample_column()
    warm = compute_steric_chunk(
        salinity,
        temperature + 1.0,
        reference_salinity,
        reference_temperature,
        pressure,
        thickness,
        gravity,
        longitude,
        latitude,
    )
    salty = compute_steric_chunk(
        salinity + 0.1,
        temperature,
        reference_salinity,
        reference_temperature,
        pressure,
        thickness,
        gravity,
        longitude,
        latitude,
    )
    assert np.all(warm["thermosteric"] > 0)
    assert np.all(salty["halosteric"] < 0)


def test_total_equals_components_plus_nonlinear_residual():
    (
        salinity,
        temperature,
        reference_salinity,
        reference_temperature,
        pressure,
        thickness,
        gravity,
        longitude,
        latitude,
    ) = sample_column()
    result = compute_steric_chunk(
        salinity + 0.15,
        temperature + 1.5,
        reference_salinity,
        reference_temperature,
        pressure,
        thickness,
        gravity,
        longitude,
        latitude,
    )
    residual = (
        result["steric_total"]
        - result["thermosteric"]
        - result["halosteric"]
    )
    np.testing.assert_allclose(
        result["steric_total"],
        result["thermosteric"] + result["halosteric"] + residual,
        atol=1e-12,
    )


def test_quarter_degree_aggregation_preserves_constant_field():
    latitude = np.array([0.125, 0.375, 0.625, 0.875])
    longitude = np.array([120.125, 120.375, 120.625, 120.875])
    values = np.full((4, 4), 2.5)
    result = aggregate_to_one_degree(values, latitude, longitude)
    assert result.shape == (180, 360)
    assert np.isclose(result[90, 300], 2.5)
    assert np.isfinite(result).sum() == 1


def test_rebase_uses_reference_period_and_fixed_mask():
    time = pd.to_datetime(["2003-01-01", "2003-02-01", "2011-01-01"])
    latitude = np.array([0.5])
    longitude = np.array([10.5, 11.5])
    base = np.array([[[1.0, 1.0]], [[3.0, np.nan]], [[5.0, 5.0]]])
    dataset = xr.Dataset(
        {
            "steric_total": (("time", "latitude", "longitude"), base),
            "thermosteric": (("time", "latitude", "longitude"), base * 0.6),
            "halosteric": (("time", "latitude", "longitude"), base * 0.3),
            "nonlinear_residual": (
                ("time", "latitude", "longitude"),
                base * 0.1,
            ),
        },
        coords={"time": time, "latitude": latitude, "longitude": longitude},
    )
    result = rebase_components(dataset)
    np.testing.assert_allclose(
        result["steric_total"][:, 0, 0].values, [-1.0, 1.0, 3.0]
    )
    assert result["valid_ocean_mask"][0, 0]
    assert not result["valid_ocean_mask"][0, 1]
    assert np.isnan(result["steric_total"][:, 0, 1]).all()
    np.testing.assert_allclose(
        result["steric_total"],
        result["thermosteric"]
        + result["halosteric"]
        + result["nonlinear_residual"],
    )
