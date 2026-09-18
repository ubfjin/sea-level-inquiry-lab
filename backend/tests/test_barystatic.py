import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from app.barystatic import BarystaticRepository


def sample_repository(tmp_path: Path) -> BarystaticRepository:
    times = pd.date_range("2010-01-01", periods=120, freq="MS") + pd.Timedelta(days=14)
    latitudes = np.array([90.0, 0.0, -90.0])
    longitudes = np.array([0.0, 1.0, 360.0])
    land_mask = np.zeros((3, 3), dtype=np.uint8)
    land_mask[1, 1] = 1
    spatial = np.arange(9, dtype=float).reshape(3, 3) / 10

    definitions = [
        ("groundwater", "지하수 고갈", 1.0, "source_monthly"),
        ("dam_reservoir_storage", "댐 저수", -0.4, "interpolated_from_annual"),
    ]
    components = []
    for key, label, annual_slope, treatment in definitions:
        years = np.arange(120, dtype=float) / 12
        series = annual_slope * years
        fingerprint = series[:, None, None] + spatial[None, :, :]
        filename = f"{key}.nc"
        variable = f"{key}_fingerprint"
        dataset = xr.Dataset(
            {
                variable: (("time", "lat", "lon"), fingerprint, {"units": "mm"}),
                "ocean_mean_fingerprint": (("time",), series, {"units": "mm"}),
                "land_mask": (("lat", "lon"), land_mask),
            },
            coords={"time": times, "lat": latitudes, "lon": longitudes},
            attrs={"processing_status": "complete"},
        )
        dataset.to_netcdf(tmp_path / filename)
        component = {
            "key": key,
            "label_ko": label,
            "filename": filename,
            "fingerprint_variable": variable,
            "series_variable": "ocean_mean_fingerprint",
            "analysis_start": "2010-01",
            "analysis_end": "2019-12",
            "temporal_treatment": treatment,
        }
        if key == "groundwater":
            component["extrapolated_start"] = "2016-01"
            component["extrapolated_end"] = "2019-12"
        components.append(component)

    catalog = {
        "schema_version": "1.0.0",
        "reference_period": {"start": "2003-01", "end": "2010-12"},
        "value_convention": {"fingerprint_variable_unit": "mm"},
        "analysis_policy": {"default_start": "1993-01", "implicit_component_sum": False},
        "components": components,
    }
    catalog_path = tmp_path / "component_catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    return BarystaticRepository(tmp_path, catalog_path)


def test_barystatic_status_and_strict_series_period(tmp_path):
    repository = sample_repository(tmp_path)
    status = repository.status()
    assert status["connected"] is True
    assert status["common_period_all_connected_components"] == {"start": "2010-01", "end": "2019-12"}

    result = repository.series("groundwater", "2015-01", "2016-12")
    assert result["data_period"] == {"start": "2015-01", "end": "2016-12"}
    assert result["unit"] == "mm"
    assert result["series"][0]["quality"] == "source_monthly"
    assert result["series"][-1]["quality"] == "extrapolated"

    with pytest.raises(ValueError, match="자동으로 바꾸지 않았습니다"):
        repository.series("groundwater", "2009-01", "2011-12")


def test_barystatic_map_removes_cyclic_endpoint_and_masks_land(tmp_path):
    repository = sample_repository(tmp_path)
    result = repository.map_at("groundwater", "2016-02")
    assert result["cyclic_endpoint_removed"] is True
    assert result["longitudes"] == [0.0, 1.0]
    assert len(result["values"]) == 3
    assert len(result["values"][0]) == 2
    assert result["values"][1][1] is None
    assert result["quality"] == "extrapolated"


def test_combined_series_and_map_are_component_sums(tmp_path):
    repository = sample_repository(tmp_path)
    keys = ("groundwater", "dam_reservoir_storage")
    combined_series = repository.series_sum(keys, "2012-01", "2014-12")
    groundwater = repository.series("groundwater", "2012-01", "2014-12")
    dam = repository.series("dam_reservoir_storage", "2012-01", "2014-12")
    expected = groundwater["series"][5]["monthly_mm"] + dam["series"][5]["monthly_mm"]
    assert combined_series["series"][5]["monthly_mm"] == pytest.approx(expected)
    assert combined_series["components"] == list(keys)

    combined_map = repository.map_sum_at(keys, "2014-06")
    groundwater_map = repository.map_at("groundwater", "2014-06")
    dam_map = repository.map_at("dam_reservoir_storage", "2014-06")
    assert combined_map["values"][0][0] == pytest.approx(
        groundwater_map["values"][0][0] + dam_map["values"][0][0]
    )
    assert combined_map["values"][1][1] is None


def test_trend_map_minimum_period_warning_and_sum(tmp_path):
    repository = sample_repository(tmp_path)
    with pytest.raises(ValueError, match="최소 5년"):
        repository.trend_map("groundwater", "2015-01", "2018-12")

    short = repository.trend_map("groundwater", "2015-01", "2019-12")
    assert short["months_used"] == 60
    assert short["warning"] is not None
    assert short["values"][0][0] == pytest.approx(1.0, abs=5e-4)

    full = repository.trend_map("groundwater", "2010-01", "2019-12")
    assert full["warning"] is None
    assert full["values"][0][0] == pytest.approx(1.0, abs=5e-4)

    combined = repository.trend_map_sum(
        ("groundwater", "dam_reservoir_storage"), "2010-01", "2019-12"
    )
    assert combined["values"][0][0] == pytest.approx(0.6, abs=5e-4)
    assert combined["values"][1][1] is None
