from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from .netcdf_io import open_netcdf
from .science import decimal_year, linear_fit


class CauseComparisonRepository:
    """Serve aligned SLA, total steric, and GRACE fields on one fixed ocean mask."""

    def __init__(self, path: str | Path):
        self.path = Path(os.path.abspath(Path(path).expanduser()))

    def _open(self):
        if not self.path.exists():
            raise ValueError("관측 SLA·Steric·GRACE 공통 비교 NetCDF가 없습니다.")
        return open_netcdf(self.path)

    @staticmethod
    def _period(value: str) -> pd.Period:
        try:
            return pd.Period(value, freq="M")
        except (TypeError, ValueError) as exc:
            raise ValueError("날짜는 YYYY-MM 형식으로 입력해 주세요.") from exc

    @staticmethod
    def _periods(ds: xr.Dataset) -> pd.PeriodIndex:
        return pd.DatetimeIndex(pd.to_datetime(ds["time"].values)).to_period("M")

    @staticmethod
    def _serialize(values: np.ndarray) -> list[list[float | None]]:
        return [
            [None if not np.isfinite(value) else float(value) for value in row]
            for row in values
        ]

    @staticmethod
    def _normalize_longitude(value: float) -> float:
        return float((value + 180.0) % 360.0 - 180.0)

    @lru_cache(maxsize=128)
    def observed_point_series(
        self,
        start: str,
        end: str,
        lat: float,
        lon: float,
    ) -> dict[str, Any]:
        if not np.isfinite(lat) or not -90.0 <= lat <= 90.0:
            raise ValueError("위도는 -90°에서 90° 사이여야 합니다.")
        if not np.isfinite(lon):
            raise ValueError("경도는 유한한 숫자여야 합니다.")
        requested_start = self._period(start)
        requested_end = self._period(end)
        if requested_start > requested_end:
            raise ValueError("시작 월은 종료 월보다 빠르거나 같아야 합니다.")
        requested_lon = self._normalize_longitude(lon)

        with self._open() as ds:
            periods = self._periods(ds)
            available_start = periods.min()
            available_end = periods.max()
            data_start = max(requested_start, available_start)
            data_end = min(requested_end, available_end)
            if data_start > data_end:
                raise ValueError(
                    f"전 지구 1° SLA 사용 가능 기간은 {available_start}–{available_end}입니다."
                )

            latitudes = np.asarray(ds["latitude"].values, dtype=float)
            longitudes = np.asarray(ds["longitude"].values, dtype=float)
            ocean = np.asarray(ds["common_ocean_mask"].values, dtype=bool)
            lat_grid = np.deg2rad(latitudes)[:, None]
            lon_grid = np.deg2rad(longitudes)[None, :]
            requested_lat_rad = np.deg2rad(lat)
            requested_lon_rad = np.deg2rad(requested_lon)
            delta_lat = lat_grid - requested_lat_rad
            delta_lon = (lon_grid - requested_lon_rad + np.pi) % (2 * np.pi) - np.pi
            haversine = (
                np.sin(delta_lat / 2) ** 2
                + np.cos(requested_lat_rad) * np.cos(lat_grid) * np.sin(delta_lon / 2) ** 2
            )
            distances = 2 * np.arcsin(np.sqrt(np.clip(haversine, 0.0, 1.0)))
            distances[~ocean] = np.inf
            flat_index = int(np.argmin(distances))
            if not np.isfinite(distances.flat[flat_index]):
                raise ValueError("선택 위치 주변에서 유효한 전 지구 해양 격자를 찾지 못했습니다.")
            lat_index, lon_index = np.unravel_index(flat_index, distances.shape)

            keep = (periods >= data_start) & (periods <= data_end)
            dates = pd.DatetimeIndex(pd.to_datetime(ds["time"].values))[keep]
            values_mm = np.asarray(
                ds["observed_sla"].isel(
                    time=np.flatnonzero(keep),
                    latitude=int(lat_index),
                    longitude=int(lon_index),
                ).values,
                dtype=float,
            ).reshape(-1)

        if values_mm.size < 2 or not np.all(np.isfinite(values_mm)):
            raise ValueError("선택한 전 지구 해양 격자의 시계열 자료가 완전하지 않습니다.")
        years = decimal_year(dates)
        slope_mm, intercept_mm = linear_fit(values_mm, years)
        moving_mm = pd.Series(values_mm).rolling(12, center=True, min_periods=12).mean().to_numpy()
        trend_mm = slope_mm * years + intercept_mm
        rows = [
            {
                "date": date.strftime("%Y-%m-%d"),
                "monthly": float(value / 1000.0),
                "moving": None if not np.isfinite(moving) else float(moving / 1000.0),
                "trend": float(trend / 1000.0),
            }
            for date, value, moving, trend in zip(dates, values_mm, moving_mm, trend_mm)
        ]
        adjusted = data_start != requested_start or data_end != requested_end
        return {
            "requested_location": {"lat": float(lat), "lon": requested_lon},
            "grid_location": {
                "lat": float(latitudes[lat_index]),
                "lon": float(longitudes[lon_index]),
            },
            "snap_distance_km": float(distances[lat_index, lon_index] * 6371.0088),
            "data_source": "global_1deg",
            "data_source_label": "전 지구 1° 평균 SLA",
            "grid_resolution_degrees": 1.0,
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "data_period": {"start": str(data_start), "end": str(data_end)},
            "period_adjusted": adjusted,
            "period_note": (
                f"전 지구 자료 사용 가능 기간에 맞춰 {data_start}–{data_end}을 사용했습니다."
                if adjusted else None
            ),
            "trend_mm_per_year": float(slope_mm),
            "series": rows,
        }

    @lru_cache(maxsize=128)
    def steric_point_series(
        self, start: str, end: str, lat: float, lon: float
    ) -> dict[str, Any]:
        if not np.isfinite(lat) or not -90.0 <= lat <= 90.0:
            raise ValueError("위도는 -90°에서 90° 사이여야 합니다.")
        if not np.isfinite(lon):
            raise ValueError("경도는 유한한 숫자여야 합니다.")
        requested_start = self._period(start)
        requested_end = self._period(end)
        if requested_start > requested_end:
            raise ValueError("시작 월은 종료 월보다 빠르거나 같아야 합니다.")
        requested_lon = self._normalize_longitude(lon)

        with self._open() as ds:
            periods = self._periods(ds)
            if requested_start < periods.min() or requested_end > periods.max():
                raise ValueError(
                    f"Total steric 사용 가능 기간은 {periods.min()}–{periods.max()}입니다."
                )
            latitudes = np.asarray(ds["latitude"].values, dtype=float)
            longitudes = np.asarray(ds["longitude"].values, dtype=float)
            ocean = np.asarray(ds["common_ocean_mask"].values, dtype=bool)
            lat_grid = np.deg2rad(latitudes)[:, None]
            lon_grid = np.deg2rad(longitudes)[None, :]
            requested_lat_rad = np.deg2rad(lat)
            requested_lon_rad = np.deg2rad(requested_lon)
            delta_lat = lat_grid - requested_lat_rad
            delta_lon = (lon_grid - requested_lon_rad + np.pi) % (2 * np.pi) - np.pi
            haversine = (
                np.sin(delta_lat / 2) ** 2
                + np.cos(requested_lat_rad) * np.cos(lat_grid) * np.sin(delta_lon / 2) ** 2
            )
            distances = 2 * np.arcsin(np.sqrt(np.clip(haversine, 0.0, 1.0)))
            distances[~ocean] = np.inf
            flat_index = int(np.argmin(distances))
            if not np.isfinite(distances.flat[flat_index]):
                raise ValueError("선택 위치 주변에서 유효한 전 지구 해양 격자를 찾지 못했습니다.")
            lat_index, lon_index = np.unravel_index(flat_index, distances.shape)
            keep = (periods >= requested_start) & (periods <= requested_end)
            dates = pd.DatetimeIndex(pd.to_datetime(ds["time"].values))[keep]
            values = np.asarray(
                ds["steric_total"].isel(
                    time=np.flatnonzero(keep),
                    latitude=int(lat_index),
                    longitude=int(lon_index),
                ).values,
                dtype=float,
            ).reshape(-1)

        return self._steric_series_result(
            values, dates, requested_start, requested_end,
            requested_location={"lat": float(lat), "lon": requested_lon},
            grid_location={"lat": float(latitudes[lat_index]), "lon": float(longitudes[lon_index])},
            snap_distance_km=float(distances[lat_index, lon_index] * 6371.0088),
        )

    @staticmethod
    def _steric_series_result(
        values: np.ndarray,
        dates: pd.DatetimeIndex,
        start: pd.Period,
        end: pd.Period,
        **location: Any,
    ) -> dict[str, Any]:
        if values.size < 2 or not np.all(np.isfinite(values)):
            raise ValueError("선택 기간의 Total steric 자료가 완전하지 않습니다.")
        years = decimal_year(dates)
        slope, intercept = linear_fit(values, years)
        moving = pd.Series(values).rolling(12, center=True, min_periods=12).mean().to_numpy()
        trend = slope * years + intercept
        return {
            "component": "steric_total",
            "label_ko": "해수 밀도 변화",
            "requested_period": {"start": str(start), "end": str(end)},
            "data_period": {"start": str(start), "end": str(end)},
            "reference_period": {"start": "2003-01", "end": "2010-12", "operation": "각 격자 평균 제거"},
            "unit": "mm",
            "trend_mm_per_year": float(slope),
            "temporal_treatment": "월자료",
            "scope": "point" if location else "global",
            **location,
            "series": [
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "monthly_mm": float(value),
                    "moving_12m_mm": None if not np.isfinite(avg) else float(avg),
                    "linear_trend_mm": float(fitted),
                    "quality": "source_monthly",
                }
                for date, value, avg, fitted in zip(dates, values, moving, trend)
            ],
        }

    @lru_cache(maxsize=32)
    def steric_series(self, start: str, end: str) -> dict[str, Any]:
        requested_start = self._period(start)
        requested_end = self._period(end)
        if requested_start > requested_end:
            raise ValueError("시작 월은 종료 월보다 빠르거나 같아야 합니다.")
        with self._open() as ds:
            periods = self._periods(ds)
            if requested_start < periods.min() or requested_end > periods.max():
                raise ValueError(f"Total steric 사용 가능 기간은 {periods.min()}–{periods.max()}입니다.")
            keep = (periods >= requested_start) & (periods <= requested_end)
            dates = pd.DatetimeIndex(pd.to_datetime(ds["time"].values))[keep]
            values = np.asarray(ds["steric_ocean_mean"].values, dtype=float)[keep]
        return self._steric_series_result(values, dates, requested_start, requested_end)

    @lru_cache(maxsize=48)
    def observed_map_at(self, date: str) -> dict[str, Any]:
        result = self.map_at(date, "observed")
        return {
            **result,
            "values": [
                [None if value is None else value / 1000.0 for value in row]
                for row in result["values"]
            ],
            "unit": "m",
            "data_source": "global_1deg",
            "data_source_label": "전 지구 1° 평균 SLA",
            "grid_resolution_degrees": 1.0,
        }

    @lru_cache(maxsize=32)
    def observed_trend_map(self, start: str, end: str) -> dict[str, Any]:
        requested_start = self._period(start)
        requested_end = self._period(end)
        if requested_start > requested_end:
            raise ValueError("시작 월은 종료 월보다 빠르거나 같아야 합니다.")

        with self._open() as ds:
            periods = self._periods(ds)
            data_start = max(requested_start, periods.min())
            data_end = min(requested_end, periods.max())
            if data_start > data_end:
                raise ValueError(
                    f"전 지구 1° SLA 사용 가능 기간은 {periods.min()}–{periods.max()}입니다."
                )
            keep = (periods >= data_start) & (periods <= data_end)
            dates = pd.DatetimeIndex(pd.to_datetime(ds["time"].values))[keep]
            values = np.asarray(ds["observed_sla"].isel(time=np.flatnonzero(keep)).values, dtype=float)
            ocean = np.asarray(ds["common_ocean_mask"].values, dtype=bool)
            latitudes = np.asarray(ds["latitude"].values, dtype=float)
            longitudes = np.asarray(ds["longitude"].values, dtype=float)

        years = decimal_year(dates)[:, None, None]
        valid = np.isfinite(values)
        count = valid.sum(axis=0)
        x = np.where(valid, years, 0.0)
        y = np.where(valid, values, 0.0)
        sum_x = x.sum(axis=0)
        sum_y = y.sum(axis=0)
        denominator = count * (x * x).sum(axis=0) - sum_x * sum_x
        numerator = count * (x * y).sum(axis=0) - sum_x * sum_y
        slopes = np.full(count.shape, np.nan, dtype=float)
        usable = ocean & (count >= 2) & (denominator != 0)
        slopes[usable] = numerator[usable] / denominator[usable]
        adjusted = data_start != requested_start or data_end != requested_end
        return {
            "latitudes": latitudes.tolist(),
            "longitudes": longitudes.tolist(),
            "values": self._serialize(slopes),
            "unit": "mm/year",
            "area_mean": float(np.nanmean(slopes)),
            "data_source": "global_1deg",
            "data_source_label": "전 지구 1° 평균 SLA",
            "grid_resolution_degrees": 1.0,
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "data_period": {"start": str(data_start), "end": str(data_end)},
            "period_adjusted": adjusted,
            "period_note": (
                f"전 지구 자료 사용 가능 기간에 맞춰 {data_start}–{data_end}을 사용했습니다."
                if adjusted else None
            ),
        }

    @lru_cache(maxsize=32)
    def steric_trend_map(self, start: str, end: str) -> dict[str, Any]:
        requested_start = self._period(start)
        requested_end = self._period(end)
        if requested_start > requested_end:
            raise ValueError("시작 월은 종료 월보다 빠르거나 같아야 합니다.")
        with self._open() as ds:
            periods = self._periods(ds)
            if requested_start < periods.min() or requested_end > periods.max():
                raise ValueError(f"Total steric 사용 가능 기간은 {periods.min()}–{periods.max()}입니다.")
            keep = (periods >= requested_start) & (periods <= requested_end)
            dates = pd.DatetimeIndex(pd.to_datetime(ds["time"].values))[keep]
            values = np.asarray(ds["steric_total"].isel(time=np.flatnonzero(keep)).values, dtype=float)
            ocean = np.asarray(ds["common_ocean_mask"].values, dtype=bool)
            latitudes = np.asarray(ds["latitude"].values, dtype=float)
            longitudes = np.asarray(ds["longitude"].values, dtype=float)
        years = decimal_year(dates)[:, None, None]
        valid = np.isfinite(values)
        count = valid.sum(axis=0)
        x = np.where(valid, years, 0.0)
        y = np.where(valid, values, 0.0)
        sum_x = x.sum(axis=0)
        sum_y = y.sum(axis=0)
        denominator = count * (x * x).sum(axis=0) - sum_x * sum_x
        numerator = count * (x * y).sum(axis=0) - sum_x * sum_y
        slopes = np.full(count.shape, np.nan, dtype=float)
        usable = ocean & (count >= 2) & (denominator != 0)
        slopes[usable] = numerator[usable] / denominator[usable]
        return {
            "component": "steric_total",
            "label_ko": "해수 밀도 변화",
            "latitudes": latitudes.tolist(),
            "longitudes": longitudes.tolist(),
            "values": self._serialize(slopes),
            "unit": "mm/year",
            "reference_period": {"start": "2003-01", "end": "2010-12", "operation": "각 격자 평균 제거"},
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "data_period": {"start": str(requested_start), "end": str(requested_end)},
            "months_used": int(len(dates)),
            "warning": None,
            "cyclic_endpoint_removed": True,
        }

    @lru_cache(maxsize=48)
    def steric_map_at(self, date: str) -> dict[str, Any]:
        result = self.map_at(date, "steric")
        return {**result, "component": "steric_total"}

    def status(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "connected": False,
                "message": "관측 SLA·Steric·GRACE 공통 비교 자료가 아직 만들어지지 않았습니다.",
            }
        try:
            with self._open() as ds:
                required = {
                    "observed_sla",
                    "steric_total",
                    "grace_fingerprint",
                    "component_sum",
                    "residual",
                    "common_ocean_mask",
                    "observed_ocean_mean",
                    "steric_ocean_mean",
                    "grace_ocean_mean",
                    "component_sum_ocean_mean",
                    "residual_ocean_mean",
                    "grace_source_available",
                }
                missing = sorted(required.difference(ds.variables))
                periods = self._periods(ds)
                availability = np.asarray(ds["grace_source_available"].values)
                common_cells = int((ds["common_ocean_mask"].values == 1).sum())
                connected = not missing and ds.attrs.get("processing_status") == "complete"
                return {
                    "connected": connected,
                    "source": self.path.name,
                    "period": {"start": str(periods.min()), "end": str(periods.max())},
                    "reference_period": {"start": "2003-01", "end": "2010-12"},
                    "available_grace_months": int(np.count_nonzero(availability == 1)),
                    "mission_gap_months": int(np.count_nonzero(availability == 0)),
                    "common_ocean_cells": common_cells,
                    "grid": "전 지구 1° 고정 해양 격자",
                    "alignment": ds.attrs.get("grace_alignment", "GRACE를 SLA 격자 중심으로 정렬"),
                    "mask_policy": ds.attrs.get("mask_policy", "SLA와 GRACE 유효 해양 영역의 교집합"),
                    "layers": {
                        "observed": True,
                        "steric": True,
                        "grace": True,
                        "component_sum": True,
                        "residual": True,
                    },
                    "unit": "mm",
                    "issues": [f"{name} 변수 없음" for name in missing],
                }
        except (OSError, ValueError, KeyError) as exc:
            return {"connected": False, "message": f"공통 비교 자료 검사 실패: {exc}"}

    @lru_cache(maxsize=32)
    def series(self, start: str, end: str) -> dict[str, Any]:
        requested_start = self._period(start)
        requested_end = self._period(end)
        if requested_start > requested_end:
            raise ValueError("시작 월은 종료 월보다 빠르거나 같아야 합니다.")

        with self._open() as ds:
            periods = self._periods(ds)
            if requested_start < periods.min() or requested_end > periods.max():
                raise ValueError(
                    f"공통 비교 자료 사용 가능 기간은 {periods.min()}–{periods.max()}입니다."
                )
            keep = (periods >= requested_start) & (periods <= requested_end)
            dates = pd.DatetimeIndex(pd.to_datetime(ds["time"].values))[keep]
            observed = np.asarray(ds["observed_ocean_mean"].values, dtype=float)[keep]
            steric = np.asarray(ds["steric_ocean_mean"].values, dtype=float)[keep]
            grace = np.asarray(ds["grace_ocean_mean"].values, dtype=float)[keep]
            component_sum = np.asarray(
                ds["component_sum_ocean_mean"].values,
                dtype=float,
            )[keep]
            residual = np.asarray(ds["residual_ocean_mean"].values, dtype=float)[keep]
            availability = np.asarray(ds["grace_source_available"].values, dtype=int)[keep]
            common_cells = int((ds["common_ocean_mask"].values == 1).sum())

        common_valid = (
            np.isfinite(observed)
            & np.isfinite(steric)
            & np.isfinite(grace)
            & np.isfinite(component_sum)
            & np.isfinite(residual)
            & (availability == 1)
        )
        if common_valid.sum() < 2:
            raise ValueError("성분 변화율을 비교하려면 공통 관측월이 2개 이상 필요합니다.")

        years = decimal_year(dates)
        observed_slope, _ = linear_fit(observed[common_valid], years[common_valid])
        steric_slope, _ = linear_fit(steric[common_valid], years[common_valid])
        grace_slope, _ = linear_fit(grace[common_valid], years[common_valid])
        component_sum_slope, _ = linear_fit(
            component_sum[common_valid],
            years[common_valid],
        )
        residual_slope, _ = linear_fit(residual[common_valid], years[common_valid])

        def moving_average(values: np.ndarray) -> np.ndarray:
            return (
                pd.Series(values)
                .rolling(12, center=True, min_periods=12)
                .mean()
                .to_numpy()
            )

        observed_moving = moving_average(observed)
        steric_moving = moving_average(steric)
        grace_moving = moving_average(grace)
        component_sum_moving = moving_average(component_sum)
        residual_moving = moving_average(residual)

        rows = []
        for (
            date,
            observed_value,
            steric_value,
            grace_value,
            component_sum_value,
            residual_value,
            observed_avg,
            steric_avg,
            grace_avg,
            component_sum_avg,
            residual_avg,
            available,
        ) in zip(
            dates,
            observed,
            steric,
            grace,
            component_sum,
            residual,
            observed_moving,
            steric_moving,
            grace_moving,
            component_sum_moving,
            residual_moving,
            availability,
        ):
            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "observed_mm": None if not np.isfinite(observed_value) else float(observed_value),
                "steric_mm": None if not np.isfinite(steric_value) else float(steric_value),
                "grace_mm": None if available != 1 or not np.isfinite(grace_value) else float(grace_value),
                "component_sum_mm": (
                    None
                    if available != 1 or not np.isfinite(component_sum_value)
                    else float(component_sum_value)
                ),
                "residual_mm": (
                    None
                    if available != 1 or not np.isfinite(residual_value)
                    else float(residual_value)
                ),
                "observed_moving_12m_mm": None if not np.isfinite(observed_avg) else float(observed_avg),
                "steric_moving_12m_mm": None if not np.isfinite(steric_avg) else float(steric_avg),
                "grace_moving_12m_mm": None if not np.isfinite(grace_avg) else float(grace_avg),
                "component_sum_moving_12m_mm": (
                    None
                    if available != 1 or not np.isfinite(component_sum_avg)
                    else float(component_sum_avg)
                ),
                "residual_moving_12m_mm": (
                    None
                    if available != 1 or not np.isfinite(residual_avg)
                    else float(residual_avg)
                ),
                "quality": "source_monthly" if available == 1 else "grace_mission_gap",
            })
        return {
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "reference_period": {"start": "2003-01", "end": "2010-12"},
            "unit": "mm",
            "common_ocean_cells": common_cells,
            "common_observation_months": int(common_valid.sum()),
            "trend_month_policy": "모든 변화율에 GRACE 자료가 있는 동일한 공통 월만 사용",
            "observed_trend_mm_per_year": float(observed_slope),
            "steric_trend_mm_per_year": float(steric_slope),
            "grace_trend_mm_per_year": float(grace_slope),
            "component_sum_trend_mm_per_year": float(component_sum_slope),
            "residual_trend_mm_per_year": float(residual_slope),
            "series": rows,
        }

    @lru_cache(maxsize=48)
    def map_at(self, date: str, layer: str) -> dict[str, Any]:
        variables = {
            "observed": ("observed_sla", "관측된 해수면 변화"),
            "steric": ("steric_total", "해수 밀도에 따른 해수면 변화"),
            "grace": ("grace_fingerprint", "물·얼음 이동에 따른 해수면 변화"),
            "component_sum": ("component_sum", "두 원인 성분의 합"),
            "residual": ("residual", "관측값 − 성분 합 잔차"),
        }
        if layer not in variables:
            raise ValueError(
                "지도 자료는 observed, steric, grace, component_sum, residual 중에서 "
                "선택해 주세요."
            )
        requested = self._period(date)
        with self._open() as ds:
            periods = self._periods(ds)
            if not periods.min() <= requested <= periods.max():
                raise ValueError(f"지도 사용 가능 기간은 {periods.min()}–{periods.max()}입니다.")
            matches = np.flatnonzero(periods == requested)
            if matches.size != 1:
                raise ValueError(f"{requested}에 해당하는 월자료를 찾을 수 없습니다.")
            index = int(matches[0])
            available = int(ds["grace_source_available"].isel(time=index).values)
            if layer in {"grace", "component_sum", "residual"} and available != 1:
                raise ValueError(
                    f"{requested}은 GRACE와 GRACE-FO 사이의 임무 공백입니다. "
                    "이 기간은 보간하지 않았습니다."
                )
            variable, label_ko = variables[layer]
            field = ds[variable].isel(time=index).transpose("latitude", "longitude")
            values = np.asarray(field.values, dtype=float)
            mask = np.asarray(ds["common_ocean_mask"].values, dtype=bool)
            values[~mask] = np.nan
            latitudes = np.asarray(ds["latitude"].values, dtype=float)
            longitudes = np.asarray(ds["longitude"].values, dtype=float)
            selected_date = pd.Timestamp(ds["time"].values[index])

        return {
            "component": layer,
            "label_ko": label_ko,
            "requested_date": str(requested),
            "data_date": selected_date.strftime("%Y-%m-%d"),
            "reference_period": {"start": "2003-01", "end": "2010-12"},
            "latitudes": latitudes.tolist(),
            "longitudes": longitudes.tolist(),
            "values": self._serialize(values),
            "unit": "mm",
            "cyclic_endpoint_removed": True,
            "quality": "source_monthly",
            "mask": "fixed_common_ocean",
        }
