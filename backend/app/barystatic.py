from __future__ import annotations

import json
import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from .netcdf_io import open_netcdf
from .science import decimal_year, infer_coord_name, linear_fit


MIN_TREND_MONTHS = 60
SHORT_TREND_MONTHS = 120


class BarystaticRepository:
    """Normalize separate barystatic fingerprint NetCDFs for the web API."""

    def __init__(self, data_dir: str | Path, catalog_path: str | Path | None = None):
        # Keep a Windows junction path intact. netCDF4 cannot open some Unicode
        # paths, while an ASCII junction to the same directory works correctly.
        self.data_dir = Path(os.path.abspath(Path(data_dir).expanduser()))
        self.catalog_path = Path(
            os.path.abspath(Path(catalog_path or self.data_dir / "component_catalog.json").expanduser())
        )
        with self.catalog_path.open(encoding="utf-8") as source:
            self.catalog: dict[str, Any] = json.load(source)
        self._components = {item["key"]: item for item in self.catalog["components"]}

    def _component(self, key: str) -> dict[str, Any]:
        try:
            return self._components[key]
        except KeyError as exc:
            choices = ", ".join(self._components)
            raise ValueError(f"알 수 없는 barystatic 성분입니다: {key}. 선택 가능: {choices}") from exc

    def _path(self, component: dict[str, Any]) -> Path:
        path = Path(os.path.abspath(self.data_dir / component["filename"]))
        if path.parent != self.data_dir:
            raise ValueError("카탈로그의 파일 경로가 자료 폴더 밖을 가리킵니다.")
        return path

    @staticmethod
    def _analysis_bounds(component: dict[str, Any]) -> tuple[pd.Period, pd.Period]:
        return pd.Period(component["analysis_start"], freq="M"), pd.Period(component["analysis_end"], freq="M")

    def _component_keys(self, keys: tuple[str, ...]) -> tuple[str, ...]:
        requested = set(keys)
        unknown = requested.difference(self._components)
        if unknown:
            raise ValueError(f"알 수 없는 barystatic 성분입니다: {', '.join(sorted(unknown))}")
        ordered = tuple(key for key in self._components if key in requested)
        if not ordered:
            raise ValueError("하나 이상의 barystatic 성분을 선택해 주세요.")
        return ordered

    def _strict_period(
        self,
        keys: tuple[str, ...],
        start: str,
        end: str,
        *,
        minimum_months: int | None = None,
    ) -> tuple[tuple[str, ...], pd.Period, pd.Period, int]:
        ordered = self._component_keys(keys)
        requested_start = pd.Period(start, freq="M")
        requested_end = pd.Period(end, freq="M")
        if requested_start > requested_end:
            raise ValueError("시작 월은 종료 월보다 빠르거나 같아야 합니다.")
        month_count = requested_end.ordinal - requested_start.ordinal + 1
        if minimum_months is not None and month_count < minimum_months:
            raise ValueError(
                f"변화율은 최소 {minimum_months // 12}년({minimum_months}개월) 이상의 기간을 선택해야 합니다."
            )
        for key in ordered:
            available_start, available_end = self._analysis_bounds(self._component(key))
            if requested_start < available_start or requested_end > available_end:
                label = self._component(key)["label_ko"]
                raise ValueError(
                    f"{label} 자료 사용 가능 기간은 {available_start}–{available_end}입니다. "
                    "선택 기간을 자동으로 바꾸지 않았습니다."
                )
        return ordered, requested_start, requested_end, month_count

    @staticmethod
    def _warning_for_months(month_count: int) -> str | None:
        if month_count < SHORT_TREND_MONTHS:
            return "10년 미만의 짧은 기간에서 계산한 추세이므로 계절변동과 단기 변동의 영향을 주의해서 해석하세요."
        return None

    @staticmethod
    def _serialize_values(values: np.ndarray) -> list[list[float | None]]:
        return [
            [None if not np.isfinite(value) else float(value) for value in row]
            for row in values
        ]

    def _inspect(self, component: dict[str, Any]) -> tuple[bool, list[str]]:
        issues: list[str] = []
        path = self._path(component)
        if not path.exists():
            return False, ["파일 없음"]
        try:
            with open_netcdf(path) as ds:
                for name in ("time", "lat", "lon", component["fingerprint_variable"], component["series_variable"]):
                    if name not in ds:
                        issues.append(f"{name} 변수 없음")
                status = ds.attrs.get("processing_status")
                if status != "complete":
                    issues.append(f"processing_status={status!r}")
                for name in (component["fingerprint_variable"], component["series_variable"]):
                    if name in ds and ds[name].attrs.get("units") != "mm":
                        issues.append(f"{name} 단위가 mm가 아님")
        except Exception as exc:
            issues.append(f"파일 검사 실패: {exc}")
        return not issues, issues

    def status(self) -> dict[str, Any]:
        components = []
        for source in self.catalog["components"]:
            item = deepcopy(source)
            connected, issues = self._inspect(source)
            item["connected"] = connected
            item["issues"] = issues
            components.append(item)
        starts = [pd.Period(item["analysis_start"], freq="M") for item in components if item["connected"]]
        ends = [pd.Period(item["analysis_end"], freq="M") for item in components if item["connected"]]
        common = None if not starts else {"start": str(max(starts)), "end": str(min(ends))}
        return {
            "connected": bool(components) and all(item["connected"] for item in components),
            "schema_version": self.catalog["schema_version"],
            "reference_period": self.catalog["reference_period"],
            "value_convention": self.catalog["value_convention"],
            "analysis_policy": self.catalog["analysis_policy"],
            "common_period_all_connected_components": common,
            "components": components,
        }

    @staticmethod
    def _quality(component: dict[str, Any], period: pd.Period) -> str:
        if "extrapolated_start" in component:
            start = pd.Period(component["extrapolated_start"], freq="M")
            end = pd.Period(component["extrapolated_end"], freq="M")
            if start <= period <= end:
                return "extrapolated"
        if component["key"] == "dam_reservoir_storage":
            return "interpolated_from_annual"
        return "source_monthly"

    @lru_cache(maxsize=128)
    def series(self, key: str, start: str, end: str) -> dict[str, Any]:
        component = self._component(key)
        path = self._path(component)
        if not path.exists():
            raise ValueError(f"{component['label_ko']} 자료 파일이 없습니다.")

        _, requested_start, requested_end, _ = self._strict_period((key,), start, end)

        with open_netcdf(path) as ds:
            time = infer_coord_name(ds, "time")
            dates = pd.DatetimeIndex(pd.to_datetime(ds[time].values))
            periods = dates.to_period("M")
            keep = (periods >= requested_start) & (periods <= requested_end)
            values = np.asarray(ds[component["series_variable"]].values, dtype=float).reshape(-1)[keep]
            selected_dates = dates[keep]
            unit = ds[component["series_variable"]].attrs.get("units", "mm")

        if values.size < 2:
            raise ValueError("추세를 계산하려면 연속된 월자료가 2개 이상 필요합니다.")
        years = decimal_year(selected_dates)
        slope, intercept = linear_fit(values, years)
        moving = pd.Series(values).rolling(12, center=True, min_periods=12).mean().to_numpy()
        trend = slope * years + intercept

        rows = []
        for date, value, moving_value, trend_value in zip(selected_dates, values, moving, trend):
            period = date.to_period("M")
            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "monthly_mm": None if not np.isfinite(value) else float(value),
                "moving_12m_mm": None if not np.isfinite(moving_value) else float(moving_value),
                "linear_trend_mm": None if not np.isfinite(trend_value) else float(trend_value),
                "quality": self._quality(component, period),
            })
        return {
            "component": key,
            "label_ko": component["label_ko"],
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "data_period": {"start": str(requested_start), "end": str(requested_end)},
            "reference_period": self.catalog["reference_period"],
            "unit": unit,
            "trend_mm_per_year": float(slope),
            "temporal_treatment": component["temporal_treatment"],
            "series": rows,
        }

    @lru_cache(maxsize=24)
    def map_at(self, key: str, date: str) -> dict[str, Any]:
        component = self._component(key)
        path = self._path(component)
        if not path.exists():
            raise ValueError(f"{component['label_ko']} 자료 파일이 없습니다.")
        requested = pd.Period(date, freq="M")
        available_start, available_end = self._analysis_bounds(component)
        if not available_start <= requested <= available_end:
            raise ValueError(
                f"{component['label_ko']} 지도 사용 가능 기간은 {available_start}–{available_end}입니다."
            )

        with open_netcdf(path) as ds:
            lon = infer_coord_name(ds, "lon")
            lat = infer_coord_name(ds, "lat")
            time = infer_coord_name(ds, "time")
            target = requested.to_timestamp(how="start")
            field = ds[component["fingerprint_variable"]].sel({time: target}, method="nearest").transpose(lat, lon)
            selected_date = pd.Timestamp(field[time].values)
            values = np.asarray(field.values, dtype=float)
            latitudes = np.asarray(ds[lat].values, dtype=float)
            longitudes = np.asarray(ds[lon].values, dtype=float)
            if "land_mask" in ds:
                land = np.asarray(ds["land_mask"].transpose(lat, lon).values, dtype=bool)
                values = np.where(land, np.nan, values)
            unit = field.attrs.get("units", "mm")

        cyclic_endpoint_removed = bool(
            longitudes.size > 1 and np.isclose(abs(longitudes[-1] - longitudes[0]), 360.0)
        )
        if cyclic_endpoint_removed:
            longitudes = longitudes[:-1]
            values = values[:, :-1]
        return {
            "component": key,
            "label_ko": component["label_ko"],
            "requested_date": str(requested),
            "data_date": selected_date.strftime("%Y-%m-%d"),
            "reference_period": self.catalog["reference_period"],
            "latitudes": latitudes.tolist(),
            "longitudes": longitudes.tolist(),
            "values": self._serialize_values(values),
            "unit": unit,
            "cyclic_endpoint_removed": cyclic_endpoint_removed,
            "quality": self._quality(component, selected_date.to_period("M")),
        }

    @lru_cache(maxsize=128)
    def series_sum(self, keys: tuple[str, ...], start: str, end: str) -> dict[str, Any]:
        ordered, requested_start, requested_end, _ = self._strict_period(keys, start, end)
        results = [self.series(key, start, end) for key in ordered]
        dates = [row["date"] for row in results[0]["series"]]
        if any([row["date"] for row in result["series"]] != dates for result in results[1:]):
            raise ValueError("선택 성분의 월자료 날짜가 서로 일치하지 않습니다.")

        monthly = np.sum(
            [[np.nan if row["monthly_mm"] is None else row["monthly_mm"] for row in result["series"]] for result in results],
            axis=0,
        )
        date_index = pd.DatetimeIndex(pd.to_datetime(dates))
        years = decimal_year(date_index)
        slope, intercept = linear_fit(monthly, years)
        moving = pd.Series(monthly).rolling(12, center=True, min_periods=12).mean().to_numpy()
        trend = slope * years + intercept
        priority = {"source_monthly": 0, "interpolated_from_annual": 1, "extrapolated": 2}

        rows = []
        for index, date in enumerate(date_index):
            qualities = [result["series"][index]["quality"] for result in results]
            quality = max(qualities, key=lambda value: priority[value])
            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "monthly_mm": float(monthly[index]),
                "moving_12m_mm": None if not np.isfinite(moving[index]) else float(moving[index]),
                "linear_trend_mm": float(trend[index]),
                "quality": quality,
            })
        return {
            "component": "selected_component_sum",
            "components": list(ordered),
            "label_ko": "선택 성분 합계",
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "data_period": {"start": str(requested_start), "end": str(requested_end)},
            "reference_period": self.catalog["reference_period"],
            "unit": "mm",
            "trend_mm_per_year": float(slope),
            "temporal_treatment": "선택한 성분의 공통 월자료만 합산",
            "series": rows,
        }

    @lru_cache(maxsize=24)
    def map_sum_at(self, keys: tuple[str, ...], date: str) -> dict[str, Any]:
        ordered, requested, _, _ = self._strict_period(keys, date, date)
        results = [self.map_at(key, date) for key in ordered]
        latitudes = results[0]["latitudes"]
        longitudes = results[0]["longitudes"]
        if any(result["latitudes"] != latitudes or result["longitudes"] != longitudes for result in results[1:]):
            raise ValueError("선택 성분의 지도 격자가 서로 일치하지 않습니다.")
        arrays = [
            np.asarray([[np.nan if value is None else value for value in row] for row in result["values"]], dtype=float)
            for result in results
        ]
        values = np.sum(arrays, axis=0)
        values[np.any(~np.isfinite(arrays), axis=0)] = np.nan
        return {
            "component": "selected_component_sum",
            "components": list(ordered),
            "label_ko": "선택 성분 합계",
            "requested_date": str(requested),
            "data_date": results[0]["data_date"],
            "reference_period": self.catalog["reference_period"],
            "latitudes": latitudes,
            "longitudes": longitudes,
            "values": self._serialize_values(values),
            "unit": "mm",
            "cyclic_endpoint_removed": all(result["cyclic_endpoint_removed"] for result in results),
            "quality": "mixed" if len({result["quality"] for result in results}) > 1 else results[0]["quality"],
        }

    @lru_cache(maxsize=64)
    def trend_map(self, key: str, start: str, end: str) -> dict[str, Any]:
        component = self._component(key)
        _, requested_start, requested_end, month_count = self._strict_period(
            (key,), start, end, minimum_months=MIN_TREND_MONTHS
        )
        path = self._path(component)
        if not path.exists():
            raise ValueError(f"{component['label_ko']} 자료 파일이 없습니다.")

        with open_netcdf(path) as ds:
            lon = infer_coord_name(ds, "lon")
            lat = infer_coord_name(ds, "lat")
            time = infer_coord_name(ds, "time")
            dates = pd.DatetimeIndex(pd.to_datetime(ds[time].values))
            periods = dates.to_period("M")
            keep = (periods >= requested_start) & (periods <= requested_end)
            selected_dates = dates[keep]
            if selected_dates.size != month_count:
                raise ValueError(
                    f"{component['label_ko']} 자료에 선택 기간 중 빠진 월이 있어 변화율을 계산할 수 없습니다."
                )
            cube = np.asarray(
                ds[component["fingerprint_variable"]].isel({time: np.flatnonzero(keep)}).transpose(time, lat, lon).values,
                dtype=np.float32,
            )
            latitudes = np.asarray(ds[lat].values, dtype=float)
            longitudes = np.asarray(ds[lon].values, dtype=float)
            land = None
            if "land_mask" in ds:
                land = np.asarray(ds["land_mask"].transpose(lat, lon).values, dtype=bool)

        years = decimal_year(selected_dates)
        centered = years - years.mean()
        finite = np.all(np.isfinite(cube), axis=0)
        safe = np.where(np.isfinite(cube), cube, 0.0)
        denominator = float(np.dot(centered, centered))
        slopes = np.einsum("t,tij->ij", centered, safe, optimize=True) / denominator
        slopes[~finite] = np.nan
        if land is not None:
            slopes[land] = np.nan

        cyclic_endpoint_removed = bool(
            longitudes.size > 1 and np.isclose(abs(longitudes[-1] - longitudes[0]), 360.0)
        )
        if cyclic_endpoint_removed:
            longitudes = longitudes[:-1]
            slopes = slopes[:, :-1]
        return {
            "component": key,
            "label_ko": component["label_ko"],
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "data_period": {"start": str(requested_start), "end": str(requested_end)},
            "months_used": month_count,
            "warning": self._warning_for_months(month_count),
            "reference_period": self.catalog["reference_period"],
            "latitudes": latitudes.tolist(),
            "longitudes": longitudes.tolist(),
            "values": self._serialize_values(slopes),
            "unit": "mm/year",
            "cyclic_endpoint_removed": cyclic_endpoint_removed,
        }

    @lru_cache(maxsize=64)
    def trend_map_sum(self, keys: tuple[str, ...], start: str, end: str) -> dict[str, Any]:
        ordered, requested_start, requested_end, month_count = self._strict_period(
            keys, start, end, minimum_months=MIN_TREND_MONTHS
        )
        results = [self.trend_map(key, start, end) for key in ordered]
        latitudes = results[0]["latitudes"]
        longitudes = results[0]["longitudes"]
        if any(result["latitudes"] != latitudes or result["longitudes"] != longitudes for result in results[1:]):
            raise ValueError("선택 성분의 지도 격자가 서로 일치하지 않습니다.")
        arrays = [
            np.asarray([[np.nan if value is None else value for value in row] for row in result["values"]], dtype=float)
            for result in results
        ]
        values = np.sum(arrays, axis=0)
        values[np.any(~np.isfinite(arrays), axis=0)] = np.nan
        return {
            "component": "selected_component_sum",
            "components": list(ordered),
            "label_ko": "선택 성분 합계",
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "data_period": {"start": str(requested_start), "end": str(requested_end)},
            "months_used": month_count,
            "warning": self._warning_for_months(month_count),
            "reference_period": self.catalog["reference_period"],
            "latitudes": latitudes,
            "longitudes": longitudes,
            "values": self._serialize_values(values),
            "unit": "mm/year",
            "cyclic_endpoint_removed": all(result["cyclic_endpoint_removed"] for result in results),
        }
