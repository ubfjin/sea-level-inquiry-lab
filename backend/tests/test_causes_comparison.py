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
    availability = np.ones(36, dtype=np.uint8)
    availability[17:19] = 0
    grace[17:19] = np.nan
    mask = np.ones((2, 4), dtype=np.uint8)
    mask[0, 0] = 0

    dataset = xr.Dataset(
        {
            "observed_sla": (("time", "latitude", "longitude"), observed),
            "grace_fingerprint": (("time", "latitude", "longitude"), grace),
            "common_ocean_mask": (("latitude", "longitude"), mask),
            "observed_ocean_mean": (("time",), 2 * years),
            "grace_ocean_mean": (("time",), np.where(availability == 1, years, np.nan)),
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
    assert status["layers"] == {"observed": True, "grace": True, "steric": False}


def test_series_uses_same_available_months_for_both_trends(tmp_path):
    repository = sample_comparison(tmp_path)
    result = repository.series("2016-01", "2018-12")
    assert result["common_observation_months"] == 34
    assert result["observed_trend_mm_per_year"] == pytest.approx(2.0, abs=2e-3)
    assert result["grace_trend_mm_per_year"] == pytest.approx(1.0, abs=2e-3)
    assert result["series"][17]["observed_mm"] is not None
    assert result["series"][17]["grace_mm"] is None
    assert result["series"][17]["quality"] == "grace_mission_gap"


def test_maps_share_mask_and_grace_gap_is_not_filled(tmp_path):
    repository = sample_comparison(tmp_path)
    observed = repository.map_at("2017-06", "observed")
    assert observed["values"][0][0] is None
    assert observed["values"][0][1] is not None

    with pytest.raises(ValueError, match="임무 공백"):
        repository.map_at("2017-06", "grace")

    grace = repository.map_at("2018-01", "grace")
    assert grace["values"][0][0] is None
    assert grace["values"][0][1] is not None
