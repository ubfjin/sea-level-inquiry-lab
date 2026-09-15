# 해수면 탐구실

한반도 주변의 월평균 Sea Level Anomaly(SLA)를 학생이 직접 선택하고 지도와 시계열로 해석하는 교육용 과학 데이터 플랫폼입니다. 화면은 **입력 → 분석 → 결과 → 해석** 흐름을 따르며, 실제 관측 자료와 시연 자료를 명확하게 구분합니다.

## 서비스 구성

- **Frontend**: Next.js, TypeScript, Tailwind CSS, Plotly.js, Leaflet
- **Backend**: FastAPI, xarray, numpy, pandas, netCDF4
- **Frontend 배포**: Vercel
- **Backend 배포**: Docker를 지원하는 서비스 또는 학교 서버
- **자료 저장**: 백엔드의 영구 디스크나 볼륨

Vercel에는 학생용 화면을 배포하고, NetCDF 계산과 업로드는 별도의 FastAPI 서버가 담당합니다. 백엔드가 연결되지 않았거나 활성 NetCDF가 없을 때는 사이트가 시연 모드로 동작합니다.

## 로컬 실행

### 1. 프론트엔드

~~~powershell
pnpm install
Copy-Item .env.example .env.local
pnpm dev
~~~

브라우저에서 http://localhost:3000 을 엽니다.

### 2. 백엔드

~~~powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
$env:ADMIN_PASSWORD="안전한-비밀번호"
python -m uvicorn app.main:app --app-dir backend --reload
~~~

API 문서는 http://127.0.0.1:8000/docs 에서 확인할 수 있습니다.

## 환경변수

| 이름 | 사용 위치 | 설명 |
| --- | --- | --- |
| NEXT_PUBLIC_API_URL | Vercel | 배포된 FastAPI 주소. 예: https://api.example.com |
| NEXT_PUBLIC_SITE_URL | Vercel | 배포된 웹사이트 주소. 예: https://sea-level-lab.vercel.app |
| ADMIN_PASSWORD | Backend | 관리자 API 비밀번호 |
| CORS_ORIGINS | Backend | 허용할 프론트엔드 주소를 쉼표로 구분 |
| CORS_ORIGIN_REGEX | Backend | Vercel Preview 등 동적 주소가 필요할 때 사용할 정규식 |
| DATA_DIR | Backend | 활성 NetCDF와 업로드 후보를 저장할 영구 디스크 경로 |
| CAUSE_DATASET | Backend | 원인 성분 NetCDF 파일 경로 |

ADMIN_PASSWORD와 실제 데이터 파일은 GitHub에 올리지 않습니다.

## GitHub에 올리기

현재 프로젝트는 Git 저장소로 초기화되어 있으며 기본 브랜치는 main입니다. GitHub에서 빈 저장소를 만든 다음 다음 명령으로 연결합니다.

~~~powershell
git remote add origin https://github.com/사용자명/저장소명.git
git push -u origin main
~~~

이미 origin이 있다면 git remote set-url origin ... 을 사용합니다.

## Vercel 배포

1. Vercel에서 **Add New → Project**를 선택합니다.
2. GitHub 저장소를 가져옵니다.
3. Framework Preset은 **Next.js**, Root Directory는 저장소 루트로 둡니다.
4. NEXT_PUBLIC_API_URL과 NEXT_PUBLIC_SITE_URL을 등록합니다.
5. Deploy를 실행합니다.

vercel.json과 표준 Next.js 스크립트가 포함되어 있어 별도의 Build Command 설정은 필요하지 않습니다.

## FastAPI 배포

backend/Dockerfile은 Render, Railway, Fly.io, Google Cloud Run 등 Docker 배포 환경에서 사용할 수 있습니다.

- Docker build context 또는 서비스 root를 backend로 지정합니다.
- 영구 디스크를 연결하고 DATA_DIR을 마운트 경로로 설정합니다. 예: /data
- CORS_ORIGINS에 실제 Vercel Production URL을 등록합니다.
- Vercel Preview까지 허용하려면 CORS_ORIGIN_REGEX를 신뢰할 수 있는 프로젝트 주소 범위로 제한합니다.
- 배포 후 /health가 정상 응답하는지 확인합니다.

배포 순서는 **백엔드 배포 → 백엔드 주소를 Vercel 환경변수에 등록 → 프론트엔드 재배포**가 가장 간단합니다.

## 실제 NetCDF 자료 적용

1. 사이트의 **관리자** 화면에서 로그인합니다.
2. .nc, .nc4, .netcdf 파일을 올립니다.
3. 기간, 좌표 범위, 시간 간격, 변수 목록, SLA 존재 여부와 단위를 확인합니다.
4. **이 자료를 활성 데이터로 적용**을 누릅니다.

자료에는 시간 좌표(time), 위도(latitude, lat, y 중 하나), 경도(longitude, lon, x 중 하나), 미터 단위의 sla 변수가 필요합니다.

## 원인 성분 데이터 어댑터

CAUSE_DATASET으로 지정한 NetCDF에는 같은 월 좌표를 가진 observed, steric, ocean_mass 변수가 필요합니다. 어댑터는 각 성분의 합과 관측값의 차이를 계산합니다. 향후 thermosteric, halosteric, greenland, antarctica, mountain_glaciers, land_water_storage 성분을 같은 계층에서 확장할 수 있습니다.

## 검증

~~~powershell
python -m pytest backend\tests
pnpm lint
pnpm typecheck
pnpm build
~~~

## 계산 기준

- 날짜별 지도: 요청 날짜에 가장 가까운 월평균 자료 선택
- 한 장소: 가장 가까운 위·경도 격자 선택
- 이동평균: 중심 기준 12개월 rolling mean
- 변화율: 시간을 소수연도로 바꾼 뒤 1차 다항 회귀, m/year × 1000 = mm/year
- 영역 평균: 각 달의 유효한 위·경도 격자 평균 후 같은 방식으로 추세 계산
- 2100년: slope × 2100 + intercept. 실제 기후예측이 아닌 선형 외삽

## 데이터 출처 안내

Notebook은 Copernicus Marine의 월평균 위성 해수면 자료 사용을 전제로 합니다. 실제 수업에서는 기관의 이용 조건에 따라 받은 NetCDF를 관리자 화면에서 활성화하세요. 원인 성분에는 출처·단위·기준 기간이 확인되는 실제 자료를 사용해야 합니다.
