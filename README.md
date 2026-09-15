# 해수면 탐구실

한반도 주변의 월평균 Sea Level Anomaly(SLA)를 학생이 직접 고르고, 지도와 시계열에서 해석하는 교육용 과학 데이터 플랫폼입니다. 첨부 Notebook의 계산 원리를 유지하면서 모든 활동을 `입력 → 분석 → 결과 → 해석` 흐름으로 재구성했습니다.

## 구성

- `app/`: Next.js + TypeScript + Tailwind CSS 기반 학생·관리자 화면
- `backend/app/`: FastAPI + xarray 기반 NetCDF 분석 API
- `backend/tests/`: 날짜 근접 선택, 최근접 격자, 선형 추세, 영역 평균, 2100년 외삽 테스트

프론트엔드는 Plotly의 hover·zoom·범례 토글과 Leaflet의 지도 이동·격자 hover·위치 클릭을 지원합니다. 백엔드가 실행 중이고 활성 NetCDF가 있으면 실제 자료를 사용하며, 그렇지 않으면 화면 구조를 확인할 수 있는 시연 모드임을 명확히 표시합니다. 원인 성분 화면은 가짜 자료를 만들지 않으며 실제 자료 어댑터가 연결되기 전에는 미연결 상태를 보여줍니다.

## 1. 프론트엔드 실행

```powershell
pnpm install
pnpm dev
```

브라우저에서 개발 서버가 안내하는 주소를 엽니다. 기본 API 주소는 `http://127.0.0.1:8000`입니다. 다른 주소를 사용할 때는 `.env.local`에 `NEXT_PUBLIC_API_URL`을 설정합니다.

## 2. 백엔드 실행

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
$env:ADMIN_PASSWORD="안전한-비밀번호"
python -m uvicorn app.main:app --app-dir backend --reload
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다.

## 3. 실제 NetCDF 자료 적용

1. 사이트의 `관리자` 화면에서 로그인합니다.
2. `.nc`, `.nc4`, `.netcdf` 파일을 올립니다.
3. 기간, 좌표 범위, 시간 간격, 변수 목록, `sla` 존재 여부와 단위를 확인합니다.
4. `이 자료를 활성 데이터로 적용`을 누릅니다.

자료에는 시간 좌표(`time`), 위도(`latitude`, `lat`, `y` 중 하나), 경도(`longitude`, `lon`, `x` 중 하나), 미터 단위의 `sla` 변수가 필요합니다. 활성 파일은 `backend/data/active.nc`로 교체됩니다.

## 원인 성분 데이터 어댑터

`CAUSE_DATASET` 환경변수로 NetCDF 파일 경로를 지정할 수 있습니다. 현재 어댑터는 같은 월 좌표를 가진 `observed`, `steric`, `ocean_mass` 변수를 읽어 각 성분의 합과 잔차를 계산합니다. 향후 `thermosteric`, `halosteric`, `greenland`, `antarctica`, `mountain_glaciers`, `land_water_storage`를 같은 어댑터 계층에서 확장할 수 있습니다.

## 검증

```powershell
python -m pytest backend\tests
pnpm lint
pnpm build
```

## 계산 기준

- 날짜별 지도: 요청 날짜에 가장 가까운 월평균 자료 선택
- 한 장소: 가장 가까운 위·경도 격자 선택
- 이동평균: 중심 기준 12개월 rolling mean
- 변화율: 시간을 소수연도로 바꾼 뒤 1차 다항 회귀, `m/year × 1000 = mm/year`
- 영역 평균: 각 달의 유효한 위·경도 격자 평균 후 같은 방식으로 추세 계산
- 2100년: `slope × 2100 + intercept`; 실제 기후예측이 아닌 선형 외삽

## 데이터 출처 안내

Notebook은 Copernicus Marine의 월평균 위성 해수면 자료 사용을 전제로 합니다. 실제 수업에서는 기관의 이용 조건에 따라 받은 NetCDF를 관리자 화면에서 활성화하세요. 원인 성분에는 NASA PO.DAAC HOMAGE 계열처럼 출처·단위·기준 기간이 확인되는 자료를 권장합니다.
