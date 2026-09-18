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
    """Serve pre-aligned Copernicus SLA and GRACE fields on one fixed ocean mask."""

    def __init__(self, path: str | Path):
        self.path = Path(os.path.abspath(Path(path).expanduser()))

    def _open(self):
        if not self.path.exists():
            raise ValueError("관측 SLA·GRACE 공통 비교 NetCDF가 없습니다.")
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

    def status(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "connected": False,
                "message": "관측 SLA·GRACE 공통 비교 자료가 아직 만들어지지 않았습니다.",
            }
        try:
            with self._open() as ds:
                required = {
                    "observed_sla",
                    "grace_fingerprint",
                    "common_ocean_mask",
                    "observed_ocean_mean",
                    "grace_ocean_mean",
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
                    "layers": {"observed": True, "grace": True, "steric": False},
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
            grace = np.asarray(ds["grace_ocean_mean"].values, dtype=float)[keep]
            availability = np.asarray(ds["grace_source_available"].values, dtype=int)[keep]
            common_cells = int((ds["common_ocean_mask"].values == 1).sum())

        common_valid = (
            np.isfinite(observed)
            & np.isfinite(grace)
            & (availability == 1)
        )
        if common_valid.sum() < 2:
            raise ValueError("두 자료의 변화율을 비교하려면 공통 관측월이 2개 이상 필요합니다.")

        years = decimal_year(dates)
        observed_slope, _ = linear_fit(observed[common_valid], years[common_valid])
        grace_slope, _ = linear_fit(grace[common_valid], years[common_valid])
        observed_moving = pd.Series(observed).rolling(
            12,
            center=True,
            min_periods=12,
        ).mean().to_numpy()
        grace_moving = pd.Series(grace).rolling(
            12,
            center=True,
            min_periods=12,
        ).mean().to_numpy()

        rows = []
        for date, observed_value, grace_value, observed_avg, grace_avg, available in zip(
            dates,
            observed,
            grace,
            observed_moving,
            grace_moving,
            availability,
        ):
            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "observed_mm": None if not np.isfinite(observed_value) else float(observed_value),
                "grace_mm": None if available != 1 or not np.isfinite(grace_value) else float(grace_value),
                "observed_moving_12m_mm": None if not np.isfinite(observed_avg) else float(observed_avg),
                "grace_moving_12m_mm": None if not np.isfinite(grace_avg) else float(grace_avg),
                "quality": "source_monthly" if available == 1 else "grace_mission_gap",
            })
        return {
            "requested_period": {"start": str(requested_start), "end": str(requested_end)},
            "reference_period": {"start": "2003-01", "end": "2010-12"},
            "unit": "mm",
            "common_ocean_cells": common_cells,
            "common_observation_months": int(common_valid.sum()),
            "trend_month_policy": "두 변화율 모두 GRACE 자료가 있는 공통 월만 사용",
            "observed_trend_mm_per_year": float(observed_slope),
            "grace_trend_mm_per_year": float(grace_slope),
            "series": rows,
        }

    @lru_cache(maxsize=48)
    def map_at(self, date: str, layer: str) -> dict[str, Any]:
        if layer not in {"observed", "grace"}:
            raise ValueError("지도 자료는 observed 또는 grace 중에서 선택해 주세요.")
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
            if layer == "grace" and available != 1:
                raise ValueError(
                    f"{requested}은 GRACE와 GRACE-FO 사이의 임무 공백입니다. "
                    "이 기간은 보간하지 않았습니다."
                )
            variable = "observed_sla" if layer == "observed" else "grace_fingerprint"
            field = ds[variable].isel(time=index).transpose("latitude", "longitude")
            values = np.asarray(field.values, dtype=float)
            mask = np.asarray(ds["common_ocean_mask"].values, dtype=bool)
            values[~mask] = np.nan
            latitudes = np.asarray(ds["latitude"].values, dtype=float)
            longitudes = np.asarray(ds["longitude"].values, dtype=float)
            selected_date = pd.Timestamp(ds["time"].values[index])

        return {
            "component": layer,
            "label_ko": "관측된 해수면 변화" if layer == "observed" else "GRACE 해양 질량 변화",
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
