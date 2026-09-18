from __future__ import annotations

import os
import shutil
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .barystatic import BarystaticRepository
from .causes_comparison import CauseComparisonRepository
from .grace import GraceRepository
from .science import NetCDFCauseAdapter, NetCDFSeaLevelRepository, UnavailableCauseAdapter

BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = Path(os.path.abspath(Path(
    os.getenv("DATA_DIR", str(BASE_DIR / "data"))
).expanduser()))
BARYSTATIC_DATA_DIR = Path(os.path.abspath(Path(
    os.getenv("BARYSTATIC_DATA_DIR", str(PROJECT_DIR / "data" / "processed" / "barystatic"))
).expanduser()))
BARYSTATIC_CATALOG = Path(os.path.abspath(Path(
    os.getenv("BARYSTATIC_CATALOG", str(BARYSTATIC_DATA_DIR / "component_catalog.json"))
).expanduser()))
GRACE_DATASET = Path(os.path.abspath(Path(
    os.getenv(
        "GRACE_DATASET",
        str(BARYSTATIC_DATA_DIR / "grace_ocean_mass_fingerprint_1deg_monthly_200301_202304.nc"),
    )
).expanduser()))
CAUSE_COMPARISON_DATASET = Path(os.path.abspath(Path(
    os.getenv(
        "CAUSE_COMPARISON_DATASET",
        str(PROJECT_DIR / "data" / "processed" / "causes" / "observed_grace_aligned_1deg_monthly_200301_202304.nc"),
    )
).expanduser()))
STAGING_DIR = DATA_DIR / "staging"
ACTIVE_FILE = DATA_DIR / "active.nc"
for directory in (DATA_DIR, STAGING_DIR): directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="해수면 탐구실 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if origin.strip()],
    allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
    allow_methods=["*"],
    allow_headers=["*"],
)


def repository() -> NetCDFSeaLevelRepository:
    if not ACTIVE_FILE.exists(): raise HTTPException(503, "활성 NetCDF 자료가 없습니다. 관리자에서 자료를 업로드해 주세요.")
    return NetCDFSeaLevelRepository(ACTIVE_FILE)


def require_admin(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_PASSWORD", "oceanlab")
    if authorization != f"Bearer {expected}": raise HTTPException(401, "관리자 인증이 필요합니다.")


@app.get("/health")
def health(): return {"status": "ok", "active_dataset": ACTIVE_FILE.exists()}


@app.get("/api/dataset")
def dataset_info(repo: NetCDFSeaLevelRepository = Depends(repository)): return asdict(repo.info())


@app.get("/api/map")
def map_at(date: str, repo: NetCDFSeaLevelRepository = Depends(repository)): return repo.map_at(date)


@app.get("/api/point-series")
def point_series(start: str, end: str, lat: float, lon: float, repo: NetCDFSeaLevelRepository = Depends(repository)): return repo.point_series(start, end, lat, lon)


@app.get("/api/area-series")
def area_series(start: str, end: str, repo: NetCDFSeaLevelRepository = Depends(repository)): return repo.area_series(start, end)


@app.get("/api/trend-map")
def trend_map(start: str, end: str, repo: NetCDFSeaLevelRepository = Depends(repository)): return repo.trend_map(start, end)


@app.get("/api/projection")
def projection(start: str, end: str, base_year: int = 2024, target_year: int = 2100, repo: NetCDFSeaLevelRepository = Depends(repository)): return repo.projection(start, end, base_year, target_year)


def cause_adapter():
    path = os.getenv("CAUSE_DATASET")
    return NetCDFCauseAdapter(path) if path else UnavailableCauseAdapter()


@lru_cache(maxsize=1)
def barystatic_repository() -> BarystaticRepository:
    try:
        return BarystaticRepository(BARYSTATIC_DATA_DIR, BARYSTATIC_CATALOG)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, f"Barystatic 자료 카탈로그를 불러올 수 없습니다: {exc}") from exc


@lru_cache(maxsize=1)
def grace_repository() -> GraceRepository:
    return GraceRepository(GRACE_DATASET)


@lru_cache(maxsize=1)
def cause_comparison_repository() -> CauseComparisonRepository:
    return CauseComparisonRepository(CAUSE_COMPARISON_DATASET)


@app.get("/api/causes/status")
def causes_status(): return cause_adapter().status()


@app.get("/api/causes/compare")
def causes_compare(start: str, end: str):
    try: return cause_adapter().compare(start, end)
    except ValueError as exc: raise HTTPException(503, str(exc)) from exc


@app.get("/api/causes/overview/status")
def cause_comparison_status(
    repo: CauseComparisonRepository = Depends(cause_comparison_repository),
):
    return repo.status()


@app.get("/api/causes/overview/series")
def cause_comparison_series(
    start: str,
    end: str,
    repo: CauseComparisonRepository = Depends(cause_comparison_repository),
):
    try:
        return repo.series(start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/causes/overview/map")
def cause_comparison_map(
    date: str,
    layer: str,
    repo: CauseComparisonRepository = Depends(cause_comparison_repository),
):
    try:
        return repo.map_at(date, layer)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/causes/grace/status")
def grace_status(repo: GraceRepository = Depends(grace_repository)):
    return repo.status()


@app.get("/api/causes/grace/series")
def grace_series(
    start: str,
    end: str,
    repo: GraceRepository = Depends(grace_repository),
):
    try:
        return repo.series(start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/causes/grace/map")
def grace_map(
    date: str,
    repo: GraceRepository = Depends(grace_repository),
):
    try:
        return repo.map_at(date)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/causes/barystatic/components")
def barystatic_components(repo: BarystaticRepository = Depends(barystatic_repository)):
    return repo.status()


def parse_components(components: str) -> tuple[str, ...]:
    keys = tuple(dict.fromkeys(key.strip() for key in components.split(",") if key.strip()))
    if not keys:
        raise HTTPException(422, "하나 이상의 barystatic 성분을 선택해 주세요.")
    return keys


@app.get("/api/causes/barystatic/combined/series")
def barystatic_combined_series(
    components: str,
    start: str,
    end: str,
    repo: BarystaticRepository = Depends(barystatic_repository),
):
    try:
        return repo.series_sum(parse_components(components), start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/causes/barystatic/combined/map")
def barystatic_combined_map(
    components: str,
    date: str,
    repo: BarystaticRepository = Depends(barystatic_repository),
):
    try:
        return repo.map_sum_at(parse_components(components), date)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/causes/barystatic/combined/trend-map")
def barystatic_combined_trend_map(
    components: str,
    start: str,
    end: str,
    repo: BarystaticRepository = Depends(barystatic_repository),
):
    try:
        return repo.trend_map_sum(parse_components(components), start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/causes/barystatic/{component}/series")
def barystatic_series(
    component: str,
    start: str,
    end: str,
    repo: BarystaticRepository = Depends(barystatic_repository),
):
    try:
        return repo.series(component, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/causes/barystatic/{component}/map")
def barystatic_map(
    component: str,
    date: str,
    repo: BarystaticRepository = Depends(barystatic_repository),
):
    try:
        return repo.map_at(component, date)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/causes/barystatic/{component}/trend-map")
def barystatic_trend_map(
    component: str,
    start: str,
    end: str,
    repo: BarystaticRepository = Depends(barystatic_repository),
):
    try:
        return repo.trend_map(component, start, end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/admin/validate")
def validate_upload(file: UploadFile = File(...), _: None = Depends(require_admin)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".nc", ".nc4", ".netcdf"}: raise HTTPException(400, "NetCDF 파일만 업로드할 수 있습니다.")
    target = STAGING_DIR / f"candidate{suffix}"
    with target.open("wb") as output: shutil.copyfileobj(file.file, output)
    try: return {"candidate": target.name, "validation": asdict(NetCDFSeaLevelRepository(target).validate())}
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(422, f"자료 검사 실패: {exc}") from exc


@app.post("/api/admin/activate/{candidate}")
def activate(candidate: str, _: None = Depends(require_admin)):
    source = Path(os.path.abspath(STAGING_DIR / candidate))
    if source.parent != STAGING_DIR or not source.exists(): raise HTTPException(404, "검사된 후보 파일을 찾을 수 없습니다.")
    NetCDFSeaLevelRepository(source).validate()
    temporary = DATA_DIR / "active.next.nc"
    shutil.copy2(source, temporary)
    temporary.replace(ACTIVE_FILE)
    return {"applied": True, "dataset": asdict(NetCDFSeaLevelRepository(ACTIVE_FILE).info())}
