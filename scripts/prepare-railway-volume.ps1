param(
  [Parameter(Mandatory = $true)]
  [string]$Destination
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$destinationRoot = [System.IO.Path]::GetFullPath($Destination)

if (Test-Path -LiteralPath $destinationRoot) {
  if ((Get-ChildItem -LiteralPath $destinationRoot -Force | Measure-Object).Count -gt 0) {
    throw "대상 폴더가 비어 있지 않습니다: $destinationRoot"
  }
} else {
  New-Item -ItemType Directory -Path $destinationRoot | Out-Null
}

$files = @(
  "backend/data/active.nc",
  "data/processed/causes/observed_grace_steric_aligned_1deg_monthly_200301_202304.nc",
  "data/processed/barystatic/component_catalog.json",
  "data/processed/barystatic/ais_fingerprint_1deg_monthly_199201_202012.nc",
  "data/processed/barystatic/greenland_fingerprint_1deg_monthly_199201_202012.nc",
  "data/processed/barystatic/mountain_glaciers_fingerprint_1deg_monthly_196501_201612.nc",
  "data/processed/barystatic/groundwater_fingerprint_1deg_monthly_199301_202304.nc",
  "data/processed/barystatic/dam_fingerprint_1deg_monthly_199301_201712.nc",
  "data/processed/barystatic/snow_fingerprint_1deg_monthly_199301_202212.nc",
  "data/processed/barystatic/soil_moisture_fingerprint_1deg_monthly_199301_202212.nc",
  "data/processed/barystatic/grace_ocean_mass_fingerprint_1deg_monthly_200301_202304.nc"
)

foreach ($relativePath in $files) {
  $sourcePath = Join-Path $projectRoot $relativePath
  if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
    throw "배포에 필요한 자료를 찾을 수 없습니다: $sourcePath"
  }
  $targetPath = Join-Path $destinationRoot $relativePath
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetPath) | Out-Null
  Copy-Item -LiteralPath $sourcePath -Destination $targetPath
}

$totalBytes = (Get-ChildItem -LiteralPath $destinationRoot -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Output ("Railway 볼륨용 자료 준비 완료: {0:N1} MB" -f ($totalBytes / 1MB))
Write-Output "업로드할 때는 이 폴더 안의 backend/data 와 data/processed 구조를 Railway 볼륨의 /data 아래에 그대로 유지하세요."
