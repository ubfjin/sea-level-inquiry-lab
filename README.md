# 해수면 탐구실

한반도 주변의 월평균 Sea Level Anomaly(SLA)를 학생이 직접 선택하고 지도와 시계열로 해석하는 교육용 과학 데이터 플랫폼입니다. 화면은 **입력 → 분석 → 결과 → 해석** 흐름을 따르며, 실제 관측 자료와 시연 자료를 명확하게 구분합니다.

## 서비스 구성

- **Frontend**: Next.js, TypeScript, Tailwind CSS, Plotly.js, Leaflet
- **Backend**: FastAPI, xarray, numpy, pandas, netCDF4
- **Frontend 배포**: Vercel
- **Backend 배포**: Docker를 지원하는 서비스 또는 학교 서버
- **자료 저장**: 백엔드의 영구 디스크나 볼륨

Vercel에는 학생용 화면을 배포하고, NetCDF 계산과 업로드는 별도의 FastAPI 서버가 담당합니다. 백엔드나 특정 원인 자료가 준비되지 않았을 때는 가상 수치를 만들지 않고 연결 상태를 분명하게 표시합니다.

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
.\scripts\start-backend.ps1
~~~

API 문서는 http://127.0.0.1:8000/docs 에서 확인할 수 있습니다.

현재처럼 프로젝트 상위 폴더에 한글이 포함되어 있으면 Windows용 netCDF4가 파일을 직접 열지 못할 수 있습니다. 위 스크립트는 실행 중에만 영문 임시 연결 경로를 만들고, 서버가 종료되면 그 연결을 지웁니다. 자료를 복사하거나 이동하지 않습니다. 프로젝트를 영문 경로로 옮긴 뒤에도 같은 명령을 그대로 사용할 수 있습니다.

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
| BARYSTATIC_DATA_DIR | Backend | 7개 질량 성분 fingerprint NetCDF와 카탈로그가 있는 폴더 |
| BARYSTATIC_CATALOG | Backend | component_catalog.json 경로 |
| GRACE_DATASET | Backend | 큰 그림에서 사용할 GRACE 해양 질량 fingerprint NetCDF 경로 |
| CAUSE_COMPARISON_DATASET | Backend | 같은 1° 격자로 정렬한 Copernicus SLA·GRACE 비교 NetCDF 경로 |

ADMIN_PASSWORD와 실제 .mat/.nc 데이터 파일은 GitHub에 올리지 않습니다. 이 저장소의 .gitignore는 data/source와 생성된 NetCDF/MAT 파일을 제외하고, 데이터 구조를 설명하는 component_catalog.json만 포함합니다.

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

### Barystatic 7개 성분

질량 성분 자세히 화면은 BARYSTATIC_DATA_DIR의 실제 자료를 사용합니다.

- 남극 빙상, 그린란드 빙상, 산악 빙하
- 지하수 고갈, 댐 저수, 적설, 토양 수분
- 개별 성분 시계열과 지도
- 선택 성분 합계 A/B 비교
- 선택 월의 fingerprint 지도
- 최소 5년 이상 기간의 격자별 선형 변화율 지도

기간은 자동으로 잘라내지 않습니다. 선택한 모든 성분의 공통 자료 기간을 벗어나면 학생에게 범위를 다시 선택하도록 안내합니다. 5년 이상 10년 미만 변화율에는 단기 변동 주의 문구가 표시됩니다.

### GRACE 큰 그림 연결

큰 그림 화면의 해양 질량 변화는 사용자가 제공한 GRACE forward-model fingerprint를 독립적으로 사용합니다. 원자료의 `FMSAL`을 다시 SLE 계산하지 않고 웹용 NetCDF로 변환하며, 육지 격자는 숨기고 해양 fingerprint만 표시합니다.

- 자료 기간: 2003년 1월~2023년 4월
- 실제 관측 월: 232개월
- GRACE/GRACE-FO 임무 공백: 2017년 6월~2018년 5월, 보간하지 않고 결측으로 표시
- 기준 기간: 2003~2010년 격자별 평균
- 지도 격자: 전 지구 1°(181 × 360)

변환은 MATLAB에서 `scripts/matlab/build_grace_web_netcdf.m`을 실행합니다. 생성 파일은 `data/processed/barystatic/grace_ocean_mass_fingerprint_1deg_monthly_200301_202304.nc`이며 GitHub에는 포함하지 않습니다.

### Copernicus 한반도 SLA

관측 SLA 원자료를 다시 받을 때는 별도의 데이터 처리 의존성을 설치한 뒤 재현 가능한 다운로드 스크립트를 사용합니다. Copernicus 계정 정보는 사용자 설정에만 저장하며 저장소에 넣지 않습니다.

~~~powershell
python -m pip install -r scripts\requirements-data.txt
python scripts\download_copernicus_sla.py --dry-run
python scripts\download_copernicus_sla.py --overwrite
~~~

확정 범위는 동경 115~135°, 북위 25~45°이며, 실제 0.125° 격자 중심은 115.0625~134.9375°E와 25.0625~44.9375°N입니다.

### Copernicus 전 지구 1° SLA

원인 비교용 전 지구 자료는 0.125° 원자료 전체를 한 번에 보관하지 않습니다. 다음 도구가 1993~2025년 자료를 한 해씩 내려받고, 각 8×8 격자를 `cos(latitude)` 면적 가중 평균하여 1° 월자료로 바꿉니다. 한 해의 변환 결과를 검증한 뒤 해당 0.125° 임시 파일을 지우므로 중간 저장 공간을 작게 유지하며, 실행이 중단되면 이미 검증된 연도 다음부터 이어집니다.

~~~powershell
python scripts\build_global_copernicus_sla.py
~~~

최종 파일은 `data/processed/observed/copernicus_sla_global_1deg_monthly_199301_202512.nc`에 생성되며 다음을 포함합니다.

- `sla`: 1993년 1월~2025년 12월, 180×360 격자의 월평균 SLA(m)
- `cause_reference_mean`: 원인 비교 화면에서 기준을 맞추기 위한 2003~2010년 격자별 평균(m)
- `sla_complete_mask`: 2003년 1월~2023년 4월에 매달 SLA가 존재하는 격자 표시

`sla_complete_mask`만으로 최종 비교 영역을 정하지 않습니다. GRACE를 같은 격자로 정렬한 뒤 두 자료의 유효 해양 영역을 교집합으로 만들어야 합니다. Copernicus 원자료의 공식 1993~2012 기준면은 `sla`에 그대로 유지됩니다.

### 큰 그림용 SLA·GRACE 공통 격자

전 지구 SLA를 만든 뒤 다음 도구를 한 번 실행합니다.

~~~powershell
python scripts\build_observed_grace_comparison.py
~~~

GRACE의 정수 위·경도 격자를 SLA의 1° 격자 중심으로 정렬합니다. 각 목표 격자 주변 네 GRACE 격자 중 해양 격자만 이용해 값을 정규화하고, 네 격자 중 두 개 이상이 해양인 경우에만 비교 대상으로 사용합니다. 경도 180° 경계는 주기적으로 연결합니다.

결과 파일은 `data/processed/causes/observed_grace_aligned_1deg_monthly_200301_202304.nc`입니다.

- 고정 공통 해양 영역: 32,506개 격자
- 비교 기간: 2003년 1월~2023년 4월
- GRACE/GRACE-FO 실제 관측월: 232개월
- 임무 공백: 2017년 6월~2018년 5월의 12개월을 결측으로 유지
- 공통 기준: 두 자료 모두 2003~2010년 격자별 평균 대비 mm

큰 그림 화면은 이 파일에서 관측 SLA와 GRACE 지도·면적가중 평균 시계열을 바로 읽습니다. 변화율을 나란히 제시할 때는 공정한 비교를 위해 두 자료 모두 GRACE가 존재하는 같은 232개월만 사용합니다. Steric은 실제 수온·염분 계산 자료가 준비될 때까지 연결 준비 상태로 표시합니다.

## 검증

~~~powershell
python -m pytest backend\tests
pnpm lint
pnpm typecheck
pnpm build
~~~

Windows에서 프로젝트 경로에 한글이 포함되어 있으면 테스트용 NetCDF도 영문 임시 폴더에 생성합니다.

~~~powershell
python -m pytest backend\tests --basetemp=$env:LOCALAPPDATA\SeaLevelInquiryLab\pytest
~~~

## 계산 기준

- 날짜별 지도: 요청 날짜에 가장 가까운 월평균 자료 선택
- 한 장소: 가장 가까운 위·경도 격자 선택
- 이동평균: 중심 기준 12개월 rolling mean
- 변화율: 시간을 소수연도로 바꾼 뒤 1차 다항 회귀, m/year × 1000 = mm/year
- 영역 평균: 각 달의 유효한 위·경도 격자 평균 후 같은 방식으로 추세 계산
- 2100년: slope × 2100 + intercept. 실제 기후예측이 아닌 선형 외삽

## 데이터 출처 안내

관측 SLA에는 Copernicus Marine의 전 지구 위성 고도계 재처리 자료 `SEALEVEL_GLO_PHY_L4_MY_008_047`을 사용합니다. 월평균 데이터셋 ID는 `cmems_obs-sl_glo_phy-ssh_my_allsat-l4-duacs-0.125deg_P1M-m`입니다. 이 자료는 여러 위성 관측을 객관 분석해 빈 격자를 채운 L4 자료이므로, 모든 격자가 그 위치에서 직접 측정된 값이라는 뜻은 아닙니다.

- 한반도 주변: 동경 115~135°, 북위 25~45° 범위에서 원래의 0.125° 월평균 격자를 유지
- 전 지구: 면적 가중 평균으로 1° 격자를 생성
- 큰 그림 비교: GRACE와 겹치는 기간을 고려해 2003년부터 제공
- 기준면 통일: Copernicus 원자료의 1993~2012 평균 기준 SLA를 받아, 원인 성분 비교 화면에서는 2003~2010 평균을 다시 빼서 비교
- 자료 계열: 수업용 분석은 일관된 재처리 MY 자료를 사용하고 NRT 자료와 섞지 않음

실제 수업에서는 Copernicus Marine 계정으로 받은 NetCDF를 관리자 화면에서 활성화합니다. 원인 성분에는 출처·단위·기준 기간이 확인되는 실제 자료만 사용하며, 준비되지 않은 성분은 가상값 대신 연결 대기 상태로 표시합니다.
