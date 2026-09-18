from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from .netcdf_io import open_netcdf
from .science import decimal_year, infer_coord_name, linear_fit


class GraceRepository:
    """Serve the completed GRACE/GRACE-FO ocean fingerprint without filling its mission gap."""

    def __init__(self, path: str | Path):
        self.path = Path(os.path.abspath(Path(path).expanduser()))

    def _open(self):
        if not self.path.exists():
            raise ValueError("GRACE 웹용 NetCDF가 없습니다.")
        return open_netcdf(self.path)

    @staticmethod
    def _serialize(values: np.ndarray) -> list[list[float | None]]:
        return [
            [None if not np.isfinite(value) else float(value) for value in row]
            for row in values
        ]

    @staticmethod
    def _period(value: str) -> pd.Period:
        try:
            return pd.Period(value, freq="M")
        except (TypeError, ValueError) as exc:
            raise ValueError("날짜는 YYYY-MM 형식으로 입력해 주세요.") from exc

    def _bounds(self, ds: xr.Dataset) -> tuple[pd.Period, pd.Period]:
        time = infer_coord_name(ds, "time")
        periods = pd.DatetimeIndex(pd.to_datetime(ds[time].values)).to_period("M")
        return periods.min(), periods.max()

    def status(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "connected": False,
                "message": "GRACE 웹용 NetCDF가 없습니다.",
            }
        try:
            with self._open() as ds:
                required = {
                    "grace_fingerprint",
                    "ocean_mean_fingerprint",
                    "source_available",
                    "land_mask",
                }
                missing = sorted(required.difference(ds.variables))
                start, end = self._bounds(ds)
                availability = np.asarray(ds["source_available"].values)
                connected = not missing and ds.attrs.get("processing_status") == "complete"
                return {
                    "connected": connected,
                    "source": self.path.name,
                    "period": {"start": str(start), "end": str(end)},
                    "reference_period": {"start": "2003-01", "end": "2010-12"},
                    "available_months": int(np.count_nonzero(availability == 1)),
                    "mission_gap_months": int(np.count_nonzero(availability == 0)),
                    "mission_gap": ds.attrs.get(
                        "mission_gap",
                        "2017-06 through 2018-05 retained as missing; no interpolation",
                    ),
                    "unit": ds["grace_fingerprint"].attrs.get("units", "mm"),
                    "issues": [f"{name} 변수 없음" for name in missing],
                }
        except (OSError, ValueError, KeyError) as exc:
            return {"connected": False, "message": f"GRACE 자료 검사 실패: {exc}"}

    @lru_cache(maxsize=64)
    def series(self, start: str, end: str) -> dict[str, Any]:
        requested_start = self._period(start)
        requested_end = self._period(end)
        if requested_start > requested_end:
            raise ValueError("시작 월은 종료 월보다 빠르거나 같아야 합니다.")

        with self._open() as ds:
            time = infer_coord_name(ds, "time")
            available_start, available_end = self._bounds(ds)
            if requested_start < available_start or requested_end > available_end:
                raise ValueError(
                    f"GRACE 자료 사용 가능 기간은 {available_start}–{available_end}입니다. "
                    "선택 기간을 자동으로 바꾸지 않았습니다."
                )
            dates = pd.DatetimeIndex(pd.to_datetime(ds[time].values))
            periods = dates.to_period("M")
            keep = (periods >= requested_start) & (periods <= requested_end)
            selected_dates = dates[keep]
            values = np.asarray(
                ds["ocean_mean_fingerprint"].values,
                dtype=float,
            ).reshape(-1)[keep]
            availability = np.asarray(
                ds["source_available"].values,
                dtype=float,
            ).reshape(-1)[keep]
            unit = ds["ocean_mean_fingerprint"].attrs.get("units", "mm")

        valid = np.isfinite(values) & (availability == 1)
        if valid.sum() < 2:
            raise ValueError("GRACE 추세를 계산하려면 유효한 월자료가 2개 이상 필요합니다.")
        values = np.where(valid, values, np.nan)
        years = decimal_year(selected_dates)
        slope, intercept = linear_fit(values, years)
        moving = pd.Series(values).rolling(
            12,
            center=True,
            min_periods=12,
        ).mean().to_numpy()
        trend = slope * years + intercept

        rows = []
        for date, value, moving_value, trend_value, is_available in zip(
            selected_dates,
            values,
            moving,
            trend,
            valid,
        ):
            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "monthly_mm": None if not is_available else float(value),
                "moving_12m_mm": None if not np.isfinite(moving_value) else float(moving_value),
                "linear_trend_mm": float(trend_value),
                "quality": "source_monthly" if is_available else "mission_gap",
            })
        return {
            "component": "grace_ocean_mass",
            "label_ko": "GRACE 해양 질량 변화",
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "data_period": {"start": str(requested_start), "end": str(requested_end)},
            "reference_period": {"start": "2003-01", "end": "2010-12"},
            "unit": unit,
            "trend_mm_per_year": float(slope),
            "temporal_treatment": "GRACE/GRACE-FO 임무 공백은 보간하지 않음",
            "series": rows,
        }

    @lru_cache(maxsize=24)
    def map_at(self, date: str) -> dict[str, Any]:
        requested = self._period(date)
        with self._open() as ds:
            lon = infer_coord_name(ds, "lon")
            lat = infer_coord_name(ds, "lat")
            time = infer_coord_name(ds, "time")
            available_start, available_end = self._bounds(ds)
            if not available_start <= requested <= available_end:
                raise ValueError(
                    f"GRACE 지도 사용 가능 기간은 {available_start}–{available_end}입니다."
                )
            dates = pd.DatetimeIndex(pd.to_datetime(ds[time].values))
            periods = dates.to_period("M")
            matches = np.flatnonzero(periods == requested)
            if matches.size != 1:
                raise ValueError(f"{requested}에 해당하는 GRACE 월자료를 찾을 수 없습니다.")
            index = int(matches[0])
            source_available = float(ds["source_available"].isel({time: index}).values)
            if source_available != 1:
                raise ValueError(
                    f"{requested}은 GRACE와 GRACE-FO 사이의 임무 공백입니다. "
                    "이 기간은 보간하지 않았습니다."
                )
            field = ds["grace_fingerprint"].isel({time: index}).transpose(lat, lon)
            values = np.asarray(field.values, dtype=float)
            if "land_mask" in ds:
                land = np.asarray(ds["land_mask"].transpose(lat, lon).values, dtype=bool)
                values[land] = np.nan
            latitudes = np.asarray(ds[lat].values, dtype=float)
            longitudes = np.asarray(ds[lon].values, dtype=float)
            selected_date = dates[index]
            unit = field.attrs.get("units", "mm")

        return {
            "component": "grace_ocean_mass",
            "label_ko": "GRACE 해양 질량 변화",
            "requested_date": str(requested),
            "data_date": selected_date.strftime("%Y-%m-%d"),
            "reference_period": {"start": "2003-01", "end": "2010-12"},
            "latitudes": latitudes.tolist(),
            "longitudes": longitudes.tolist(),
            "values": self._serialize(values),
            "unit": unit,
            "cyclic_endpoint_removed": True,
            "quality": "source_monthly",
        }
