from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd
import xarray as xr


COORD_CANDIDATES = {
    "lon": ("longitude", "lon", "x"),
    "lat": ("latitude", "lat", "y"),
    "time": ("time",),
}


def infer_coord_name(ds: xr.Dataset, kind: str) -> str:
    for name in COORD_CANDIDATES[kind]:
        if name in ds.coords or name in ds.dims:
            return name
    raise ValueError(f"{kind} 좌표를 찾을 수 없습니다. 후보: {COORD_CANDIDATES[kind]}")


def decimal_year(values: Any) -> np.ndarray:
    dates = pd.DatetimeIndex(pd.to_datetime(values))
    return (dates.year + (dates.dayofyear - 1) / 365.25).to_numpy(dtype=float)


def linear_fit(values: np.ndarray, years: np.ndarray) -> tuple[float, float]:
    valid = np.isfinite(values) & np.isfinite(years)
    if valid.sum() < 2:
        raise ValueError("추세를 계산하려면 유효한 자료가 2개 이상이어야 합니다.")
    slope, intercept = np.polyfit(years[valid], values[valid], 1)
    return float(slope), float(intercept)


@dataclass
class DatasetInfo:
    filename: str
    time_start: str
    time_end: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    interval: str
    variables: list[str]
    has_sla: bool
    sla_unit: str | None


class NetCDFSeaLevelRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _open(self) -> xr.Dataset:
        return xr.open_dataset(self.path)

    def info(self) -> DatasetInfo:
        with self._open() as ds:
            lon, lat, time = (infer_coord_name(ds, key) for key in ("lon", "lat", "time"))
            times = pd.DatetimeIndex(pd.to_datetime(ds[time].values))
            spacing = "확인 불가"
            if len(times) > 1:
                days = float(np.median(np.diff(times.values).astype("timedelta64[D]").astype(float)))
                spacing = "월평균 (P1M)" if 27 <= days <= 32 else f"약 {days:.0f}일"
            return DatasetInfo(
                filename=self.path.name,
                time_start=times.min().strftime("%Y-%m-%d"),
                time_end=times.max().strftime("%Y-%m-%d"),
                lat_min=float(ds[lat].min()), lat_max=float(ds[lat].max()),
                lon_min=float(ds[lon].min()), lon_max=float(ds[lon].max()),
                interval=spacing, variables=list(ds.data_vars), has_sla="sla" in ds.data_vars,
                sla_unit=ds["sla"].attrs.get("units") if "sla" in ds.data_vars else None,
            )

    def validate(self) -> DatasetInfo:
        info = self.info()
        if not info.has_sla:
            raise ValueError("sla 변수가 없습니다.")
        if info.sla_unit not in {"m", "meter", "metre", "meters", "metres"}:
            raise ValueError(f"sla 단위가 m가 아닙니다: {info.sla_unit!r}")
        return info

    def map_at(self, target_date: str) -> dict[str, Any]:
        with self._open() as ds:
            lon, lat, time = (infer_coord_name(ds, key) for key in ("lon", "lat", "time"))
            selected = ds["sla"].sel({time: target_date}, method="nearest")
            return {
                "requested_date": target_date,
                "data_date": pd.Timestamp(selected[time].values).strftime("%Y-%m-%d"),
                "latitudes": ds[lat].values.astype(float).tolist(),
                "longitudes": ds[lon].values.astype(float).tolist(),
                "values": np.asarray(selected.values, dtype=float).tolist(),
                "unit": ds["sla"].attrs.get("units", "unknown"),
            }

    def point_series(self, start: str, end: str, lat_value: float, lon_value: float) -> dict[str, Any]:
        with self._open() as ds:
            lon, lat, time = (infer_coord_name(ds, key) for key in ("lon", "lat", "time"))
            point = ds["sla"].sel({lat: lat_value, lon: lon_value}, method="nearest").sel({time: slice(start, end)})
            dates = pd.DatetimeIndex(pd.to_datetime(point[time].values))
            values = np.asarray(point.values, dtype=float)
            years = decimal_year(dates)
            slope, intercept = linear_fit(values, years)
            moving = pd.Series(values).rolling(12, center=True, min_periods=12).mean().to_numpy()
            return {
                "requested_location": {"lat": lat_value, "lon": lon_value},
                "grid_location": {"lat": float(point[lat]), "lon": float(point[lon])},
                "trend_mm_per_year": slope * 1000,
                "series": [{"date": d.strftime("%Y-%m-%d"), "monthly": None if not np.isfinite(v) else float(v), "moving": None if not np.isfinite(m) else float(m), "trend": float(slope * y + intercept)} for d, v, m, y in zip(dates, values, moving, years)],
            }

    def area_series(self, start: str, end: str) -> dict[str, Any]:
        with self._open() as ds:
            lon, lat, time = (infer_coord_name(ds, key) for key in ("lon", "lat", "time"))
            area = ds["sla"].sel({time: slice(start, end)}).mean(dim=(lat, lon), skipna=True)
            dates = pd.DatetimeIndex(pd.to_datetime(area[time].values))
            values = np.asarray(area.values, dtype=float)
            years = decimal_year(dates)
            slope, intercept = linear_fit(values, years)
            moving = pd.Series(values).rolling(12, center=True, min_periods=12).mean().to_numpy()
            return {"trend_mm_per_year": slope * 1000, "series": [{"date": d.strftime("%Y-%m-%d"), "monthly": None if not np.isfinite(v) else float(v), "moving": None if not np.isfinite(m) else float(m), "trend": float(slope * y + intercept)} for d, v, m, y in zip(dates, values, moving, years)]}

    def trend_map(self, start: str, end: str) -> dict[str, Any]:
        with self._open() as ds:
            lon, lat, time = (infer_coord_name(ds, key) for key in ("lon", "lat", "time"))
            da = ds["sla"].sel({time: slice(start, end)})
            years = decimal_year(da[time].values)
            fitted = da.assign_coords(year_decimal=(time, years)).swap_dims({time: "year_decimal"}).polyfit(dim="year_decimal", deg=1, skipna=True)
            slopes = fitted.polyfit_coefficients.sel(degree=1) * 1000
            return {"latitudes": ds[lat].values.astype(float).tolist(), "longitudes": ds[lon].values.astype(float).tolist(), "values": np.asarray(slopes.values, dtype=float).tolist(), "unit": "mm/year", "area_mean": float(slopes.mean(skipna=True))}

    def projection(self, start: str, end: str, base_year: int, target_year: int = 2100) -> dict[str, Any]:
        with self._open() as ds:
            lon, lat, time = (infer_coord_name(ds, key) for key in ("lon", "lat", "time"))
            da = ds["sla"].sel({time: slice(start, end)})
            years = decimal_year(da[time].values)
            fitted = da.assign_coords(year_decimal=(time, years)).swap_dims({time: "year_decimal"}).polyfit(dim="year_decimal", deg=1, skipna=True)
            slope = fitted.polyfit_coefficients.sel(degree=1)
            intercept = fitted.polyfit_coefficients.sel(degree=0)
            estimate = slope * target_year + intercept
            base = ds["sla"].sel({time: slice(f"{base_year}-01-01", f"{base_year}-12-31")}).mean(time, skipna=True)
            change_mm = (estimate - base) * 1000
            return {"target_year": target_year, "base_year": base_year, "estimate_values": np.asarray(estimate.values, dtype=float).tolist(), "change_mm_values": np.asarray(change_mm.values, dtype=float).tolist(), "latitudes": ds[lat].values.astype(float).tolist(), "longitudes": ds[lon].values.astype(float).tolist()}


class CauseDataAdapter(Protocol):
    def status(self) -> dict[str, Any]: ...
    def compare(self, start: str, end: str) -> dict[str, Any]: ...


class UnavailableCauseAdapter:
    def status(self) -> dict[str, Any]:
        return {"connected": False, "message": "실제 원인 성분 자료가 아직 연결되지 않았습니다.", "supported_components": ["observed", "steric", "thermosteric", "halosteric", "ocean_mass", "greenland", "antarctica", "mountain_glaciers", "land_water_storage"]}

    def compare(self, start: str, end: str) -> dict[str, Any]:
        raise ValueError("원인 성분 자료가 연결되지 않았습니다. 가짜 값은 반환하지 않습니다.")


class NetCDFCauseAdapter:
    """Adapter for aligned monthly observed/steric/ocean-mass NetCDF series."""
    def __init__(self, path: str | Path): self.path = Path(path)

    def status(self) -> dict[str, Any]:
        if not self.path.exists(): return UnavailableCauseAdapter().status()
        with xr.open_dataset(self.path) as ds:
            present = [name for name in ("observed", "steric", "ocean_mass") if name in ds]
        return {"connected": len(present) == 3, "variables": present, "source": self.path.name}

    def compare(self, start: str, end: str) -> dict[str, Any]:
        with xr.open_dataset(self.path) as ds:
            time = infer_coord_name(ds, "time")
            subset = ds[["observed", "steric", "ocean_mass"]].sel({time: slice(start, end)})
            dates = pd.DatetimeIndex(pd.to_datetime(subset[time].values))
            rows = []
            for i, date in enumerate(dates):
                o, s, m = (float(subset[name].values[i]) for name in ("observed", "steric", "ocean_mass"))
                rows.append({"date": date.strftime("%Y-%m-%d"), "observed": o, "steric": s, "ocean_mass": m, "components_sum": s + m, "residual": o - s - m})
            return {"series": rows, "unit": subset["observed"].attrs.get("units", "m")}
