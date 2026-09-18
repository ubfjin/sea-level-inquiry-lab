from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from app.grace import GraceRepository


def sample_grace(tmp_path: Path) -> GraceRepository:
    times = pd.date_range("2016-01-01", periods=36, freq="MS") + pd.Timedelta(days=14)
    latitudes = np.array([-1.0, 0.0, 1.0])
    longitudes = np.array([-2.0, -1.0, 0.0, 1.0])
    years = np.arange(36, dtype=float) / 12
    spatial = np.arange(12, dtype=float).reshape(3, 4) / 10
    fingerprint = years[:, None, None] + spatial[None, :, :]
    ocean_mean = years.copy()
    availability = np.ones(36, dtype=np.uint8)
    availability[17:19] = 0
    fingerprint[17:19] = np.nan
    ocean_mean[17:19] = np.nan
    land = np.zeros((3, 4), dtype=np.uint8)
    land[1, 2] = 1

    dataset = xr.Dataset(
        {
            "grace_fingerprint": (
                ("time", "lat", "lon"),
                fingerprint,
                {"units": "mm"},
            ),
            "ocean_mean_fingerprint": (
                ("time",),
                ocean_mean,
                {"units": "mm"},
            ),
            "source_available": (("time",), availability),
            "land_mask": (("lat", "lon"), land),
        },
        coords={"time": times, "lat": latitudes, "lon": longitudes},
        attrs={
            "processing_status": "complete",
            "mission_gap": "2017-06 through 2017-07 retained as missing",
        },
    )
    path = tmp_path / "grace.nc"
    dataset.to_netcdf(path)
    return GraceRepository(path)


def test_grace_status_and_series_keep_gap(tmp_path):
    repository = sample_grace(tmp_path)
    status = repository.status()
    assert status["connected"] is True
    assert status["available_months"] == 34
    assert status["mission_gap_months"] == 2

    result = repository.series("2016-01", "2018-12")
    assert len(result["series"]) == 36
    assert result["series"][17]["monthly_mm"] is None
    assert result["series"][17]["quality"] == "mission_gap"
    assert result["series"][19]["monthly_mm"] is not None
    assert result["trend_mm_per_year"] == pytest.approx(1.0, abs=2e-3)


def test_grace_map_rejects_gap_and_masks_land(tmp_path):
    repository = sample_grace(tmp_path)
    with pytest.raises(ValueError, match="임무 공백"):
        repository.map_at("2017-06")

    result = repository.map_at("2018-01")
    assert result["values"][1][2] is None
    assert result["values"][0][0] is not None
    assert result["unit"] == "mm"


def test_grace_period_is_strict(tmp_path):
    repository = sample_grace(tmp_path)
    with pytest.raises(ValueError, match="자동으로 바꾸지 않았습니다"):
        repository.series("2015-01", "2018-12")
