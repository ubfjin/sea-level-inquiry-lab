from __future__ import annotations

import os
import shutil
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .science import NetCDFCauseAdapter, NetCDFSeaLevelRepository, UnavailableCauseAdapter

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
STAGING_DIR = DATA_DIR / "staging"
ACTIVE_FILE = DATA_DIR / "active.nc"
for directory in (DATA_DIR, STAGING_DIR): directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="해수면 탐구실 API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(","), allow_methods=["*"], allow_headers=["*"])


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


@app.get("/api/causes/status")
def causes_status(): return cause_adapter().status()


@app.get("/api/causes/compare")
def causes_compare(start: str, end: str):
    try: return cause_adapter().compare(start, end)
    except ValueError as exc: raise HTTPException(503, str(exc)) from exc


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
    source = (STAGING_DIR / candidate).resolve()
    if source.parent != STAGING_DIR.resolve() or not source.exists(): raise HTTPException(404, "검사된 후보 파일을 찾을 수 없습니다.")
    NetCDFSeaLevelRepository(source).validate()
    temporary = DATA_DIR / "active.next.nc"
    shutil.copy2(source, temporary)
    temporary.replace(ACTIVE_FILE)
    return {"applied": True, "dataset": asdict(NetCDFSeaLevelRepository(ACTIVE_FILE).info())}
