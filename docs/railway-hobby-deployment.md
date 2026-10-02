# Railway Hobby 백엔드 배포

이 문서는 학생용 Next.js 화면은 기존 Vercel 배포를 유지하고, FastAPI와 NetCDF 계산만 Railway Hobby에 배포하는 방법을 설명합니다.

## 준비되는 구성

- Railway 서비스: `backend` 폴더의 Dockerfile로 FastAPI 실행
- Railway Volume: `/data`에 연결
- Vercel: `NEXT_PUBLIC_API_URL`로 Railway의 공개 API 주소 사용

현재 서비스 실행에 필요한 웹용 자료는 약 0.48GB입니다. 원본 Copernicus 자료와 계산 중간 파일은 올리지 않으므로 Hobby 기본 5GB 볼륨에 여유가 있습니다.

## Railway에서 한 번만 설정할 항목

1. Railway에서 GitHub 저장소 `sea-level-inquiry-lab`을 새 프로젝트로 가져옵니다.
2. 생성된 서비스의 **Root Directory**를 `/backend`로 설정합니다. `backend/Dockerfile`이 자동으로 사용됩니다.
3. **Volume**을 만들고 서비스에 `/data` 경로로 연결합니다.
4. 서비스의 Variables에 아래 값을 등록합니다. `ADMIN_PASSWORD`는 충분히 긴 임의의 값으로 바꿉니다.

~~~text
DATA_DIR=/data/backend/data
BARYSTATIC_DATA_DIR=/data/data/processed/barystatic
BARYSTATIC_CATALOG=/data/data/processed/barystatic/component_catalog.json
GRACE_DATASET=/data/data/processed/barystatic/grace_ocean_mass_fingerprint_1deg_monthly_200301_202304.nc
CAUSE_COMPARISON_DATASET=/data/data/processed/causes/observed_grace_steric_aligned_1deg_monthly_200301_202304.nc
ADMIN_PASSWORD=충분히-긴-비밀값
CORS_ORIGINS=https://배포된-학생용-사이트.vercel.app
~~~

`CORS_ORIGINS`는 Vercel의 실제 Production 주소로 바꿉니다. Preview 주소도 필요할 때만 `CORS_ORIGIN_REGEX`에 프로젝트 주소 범위를 제한해 추가합니다.

5. Railway의 공개 도메인을 생성합니다. 배포가 끝난 뒤 `https://.../health`가 `{"status":"ok"}`를 반환하면 API가 준비된 것입니다.

## 웹용 NetCDF 업로드

로컬에서 빈 임시 폴더를 지정해 실행합니다.

~~~powershell
.\scripts\prepare-railway-volume.ps1 -Destination C:\Temp\sea-level-railway-data
~~~

생성된 폴더 안의 `backend/data`와 `data/processed`를 Railway Volume의 `/data` 아래에 같은 구조로 업로드합니다. Railway CLI에서는 `railway volume files upload`를 사용할 수 있고, 업로드가 끝난 뒤에는 Volume 파일 목록에서 다음 파일을 확인합니다.

- `/data/backend/data/active.nc`
- `/data/data/processed/causes/observed_grace_steric_aligned_1deg_monthly_200301_202304.nc`
- `/data/data/processed/barystatic/component_catalog.json`
- `/data/data/processed/barystatic` 안의 7개 질량 성분과 GRACE fingerprint 파일

Volume은 빌드 단계가 아닌 실행 단계에 연결됩니다. 따라서 Docker 이미지에 NetCDF 자료를 넣거나 GitHub에 자료를 올릴 필요가 없습니다.

## Vercel 연결

Railway 공개 API 도메인이 정해지면 Vercel의 환경변수를 다음처럼 바꾸고 재배포합니다.

~~~text
NEXT_PUBLIC_API_URL=https://Railway에서-생성된-도메인
NEXT_PUBLIC_SITE_URL=https://배포된-학생용-사이트.vercel.app
~~~

마지막으로 학생용 사이트에서 한반도 지도, 전 지구 지도, `변화의 원인`의 해수 밀도 변화 및 물·얼음 이동 그래프를 각각 한 번씩 확인합니다.

## 비용 확인

Railway Hobby는 현재 월 5달러의 구독료에 같은 금액의 월간 사용량이 포함됩니다. 사용량이 5달러를 넘으면 초과분만 추가됩니다. 배포 후 일주일 정도 사용량을 확인해 실제 메모리·전송량을 기준으로 판단하는 것이 좋습니다.
