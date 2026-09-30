from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from app.causes_comparison import CauseComparisonRepository


def sample_comparison(tmp_path: Path) -> CauseComparisonRepository:
    times = pd.date_range("2016-01-01", periods=36, freq="MS")
    latitudes = np.array([-0.5, 0.5])
    longitudes = np.array([-1.5, -0.5, 0.5, 1.5])
    years = np.arange(36, dtype=float) / 12
    spatial = np.arange(8, dtype=float).reshape(2, 4) / 10
    observed = 2 * years[:, None, None] + spatial[None, :, :]
    grace = years[:, None, None] + spatial[None, :, :]
    steric = 0.5 * years[:, None, None] + 0.2 * spatial[None, :, :]
    component_sum = steric + grace
    residual = observed - component_sum
    availability = np.ones(36, dtype=np.uint8)
    availability[17:19] = 0
    grace[17:19] = np.nan
    component_sum[17:19] = np.nan
    residual[17:19] = np.nan
    mask = np.ones((2, 4), dtype=np.uint8)
    mask[0, 0] = 0

    dataset = xr.Dataset(
        {
            "observed_sla": (("time", "latitude", "longitude"), observed),
            "steric_total": (("time", "latitude", "longitude"), steric),
            "grace_fingerprint": (("time", "latitude", "longitude"), grace),
            "component_sum": (("time", "latitude", "longitude"), component_sum),
            "residual": (("time", "latitude", "longitude"), residual),
            "common_ocean_mask": (("latitude", "longitude"), mask),
            "observed_ocean_mean": (("time",), 2 * years),
            "steric_ocean_mean": (("time",), 0.5 * years),
            "grace_ocean_mean": (("time",), np.where(availability == 1, years, np.nan)),
            "component_sum_ocean_mean": (
                ("time",),
                np.where(availability == 1, 1.5 * years, np.nan),
            ),
            "residual_ocean_mean": (
                ("time",),
                np.where(availability == 1, 0.5 * years, np.nan),
            ),
            "grace_source_available": (("time",), availability),
        },
        coords={"time": times, "latitude": latitudes, "longitude": longitudes},
        attrs={"processing_status": "complete"},
    )
    path = tmp_path / "comparison.nc"
    dataset.to_netcdf(path, engine="h5netcdf")
    return CauseComparisonRepository(path)


def test_status_reports_fixed_common_grid(tmp_path):
    repository = sample_comparison(tmp_path)
    status = repository.status()
    assert status["connected"] is True
    assert status["common_ocean_cells"] == 7
    assert status["available_grace_months"] == 34
    assert status["mission_gap_months"] == 2
    assert status["layers"] == {
        "observed": True,
        "steric": True,
        "grace": True,
        "component_sum": True,
        "residual": True,
    }


def test_series_uses_same_available_months_for_all_trends(tmp_path):
    repository = sample_comparison(tmp_path)
    result = repository.series("2016-01", "2018-12")
    assert result["common_observation_months"] == 34
    assert result["observed_trend_mm_per_year"] == pytest.approx(2.0, abs=2e-3)
    assert result["steric_trend_mm_per_year"] == pytest.approx(0.5, abs=2e-3)
    assert result["grace_trend_mm_per_year"] == pytest.approx(1.0, abs=2e-3)
    assert result["component_sum_trend_mm_per_year"] == pytest.approx(1.5, abs=2e-3)
    assert result["residual_trend_mm_per_year"] == pytest.approx(0.5, abs=2e-3)
    assert result["series"][17]["observed_mm"] is not None
    assert result["series"][17]["steric_mm"] is not None
    assert result["series"][17]["grace_mm"] is None
    assert result["series"][17]["component_sum_mm"] is None
    assert result["series"][17]["residual_mm"] is None
    assert result["series"][17]["quality"] == "grace_mission_gap"


def test_maps_share_mask_and_grace_gap_is_not_filled(tmp_path):
    repository = sample_comparison(tmp_path)
    observed = repository.map_at("2017-06", "observed")
    assert observed["values"][0][0] is None
    assert observed["values"][0][1] is not None
    steric = repository.map_at("2017-06", "steric")
    assert steric["values"][0][0] is None
    assert steric["values"][0][1] is not None

    for layer in ("grace", "component_sum", "residual"):
        with pytest.raises(ValueError, match="임무 공백"):
            repository.map_at("2017-06", layer)

    grace = repository.map_at("2018-01", "grace")
    assert grace["values"][0][0] is None
    assert grace["values"][0][1] is not None
    component_sum = repository.map_at("2018-01", "component_sum")
    assert component_sum["values"][0][0] is None
    assert component_sum["values"][0][1] is not None


def test_observed_point_series_normalizes_longitude_snaps_to_ocean_and_clips_period(tmp_path):
    repository = sample_comparison(tmp_path)
    result = repository.observed_point_series("2015-01", "2019-12", -0.5, 358.5)

    assert result["requested_location"] == {"lat": -0.5, "lon": -1.5}
    assert result["grid_location"] != result["requested_location"]
    assert result["data_source"] == "global_1deg"
    assert result["grid_resolution_degrees"] == 1.0
    assert result["period_adjusted"] is True
    assert result["data_period"] == {"start": "2016-01", "end": "2018-12"}
    assert len(result["series"]) == 36
    assert result["trend_mm_per_year"] == pytest.approx(2.0, abs=2e-3)
    assert result["series"][0]["monthly"] == pytest.approx(0.0001)


def test_observed_map_uses_metres_and_fixed_ocean_mask(tmp_path):
    repository = sample_comparison(tmp_path)
    result = repository.observed_map_at("2016-01")

    assert result["unit"] == "m"
    assert result["data_source"] == "global_1deg"
    assert result["grid_resolution_degrees"] == 1.0
    assert result["values"][0][0] is None
    assert result["values"][0][1] == pytest.approx(0.0001)


def test_observed_trend_map_clips_period_and_keeps_land_empty(tmp_path):
    repository = sample_comparison(tmp_path)
    result = repository.observed_trend_map("2015-01", "2019-12")

    assert result["period_adjusted"] is True
    assert result["data_period"] == {"start": "2016-01", "end": "2018-12"}
    assert result["values"][0][0] is None
    assert result["values"][0][1] == pytest.approx(2.0, abs=2e-3)
    assert result["area_mean"] == pytest.approx(2.0, abs=2e-3)


def test_steric_detail_series_matches_monthly_source(tmp_path):
    repository = sample_comparison(tmp_path)
    result = repository.steric_series("2016-01", "2018-12")

    assert result["component"] == "steric_total"
    assert result["trend_mm_per_year"] == pytest.approx(0.5, abs=2e-3)
    assert len(result["series"]) == 36
    assert result["series"][0]["monthly_mm"] == pytest.approx(0.0)
    assert result["series"][0]["quality"] == "source_monthly"


def test_steric_point_and_maps_use_nearest_ocean_cell(tmp_path):
    repository = sample_comparison(tmp_path)
    point = repository.steric_point_series("2016-01", "2018-12", -0.5, 358.5)
    month = repository.steric_map_at("2016-01")
    trend = repository.steric_trend_map("2016-01", "2018-12")

    assert point["grid_location"] != point["requested_location"]
    assert point["trend_mm_per_year"] == pytest.approx(0.5, abs=2e-3)
    assert month["component"] == "steric_total"
    assert month["values"][0][0] is None
    assert trend["values"][0][0] is None
    assert trend["values"][0][1] == pytest.approx(0.5, abs=2e-3)
