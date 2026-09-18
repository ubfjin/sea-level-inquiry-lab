from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from app.science import NetCDFSeaLevelRepository, UnavailableCauseAdapter, decimal_year


def sample_file(tmp_path: Path) -> Path:
    times = pd.date_range("2020-01-01", periods=36, freq="MS")
    lat = np.array([35.0, 37.0])
    lon = np.array([127.0, 129.0, 131.0])
    years = decimal_year(times)
    values = np.empty((len(times), len(lat), len(lon)))
    for i, year in enumerate(years): values[i] = (year - 2020) * 0.004 + lat[:, None] * 0.0001 + lon[None, :] * 0.00001
    values[:, 0, 0] = np.nan
    ds = xr.Dataset({"sla": (("time", "latitude", "longitude"), values, {"units": "m"})}, coords={"time": times, "latitude": lat, "longitude": lon})
    path = tmp_path / "sample.nc"
    ds.to_netcdf(path)
    return path


def test_validation_and_nearest_date(tmp_path):
    repo = NetCDFSeaLevelRepository(sample_file(tmp_path))
    info = repo.validate()
    assert info.has_sla and info.sla_unit == "m"
    assert info.interval == "월평균 (P1M)"
    result = repo.map_at("2020-02-20")
    assert result["data_date"] == "2020-03-01"
    assert result["values"][0][0] is None


def test_point_area_and_trend(tmp_path):
    repo = NetCDFSeaLevelRepository(sample_file(tmp_path))
    point = repo.point_series("2020-01-01", "2022-12-01", 36.6, 129.2)
    assert point["grid_location"] == {"lat": 37.0, "lon": 129.0}
    assert abs(point["trend_mm_per_year"] - 4.0) < 0.01
    assert len(point["series"]) == 36
    area = repo.area_series("2020-01-01", "2022-12-01")
    assert abs(area["trend_mm_per_year"] - 4.0) < 0.01
    trend = repo.trend_map("2020-01-01", "2022-12-01")
    assert abs(trend["area_mean"] - 4.0) < 0.01
    assert trend["values"][0][0] is None


def test_projection_and_unavailable_causes(tmp_path):
    repo = NetCDFSeaLevelRepository(sample_file(tmp_path))
    projected = repo.projection("2020-01-01", "2022-12-01", 2022, 2100)
    assert projected["target_year"] == 2100
    finite_change = [
        value
        for row in projected["change_mm_values"]
        for value in row
        if value is not None
    ]
    assert np.mean(finite_change) > 300
    assert projected["change_mm_values"][0][0] is None
    status = UnavailableCauseAdapter().status()
    assert status["connected"] is False
    assert "thermosteric" in status["supported_components"]
