[CmdletBinding()]
param(
    [string]$PythonCommand = "python",
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$activeDataSource = Join-Path $backendRoot "data"
$barystaticSource = Join-Path $projectRoot "data\processed\barystatic"
$causeComparisonSource = Join-Path $projectRoot "data\processed\causes\observed_grace_aligned_1deg_monthly_200301_202304.nc"
$asciiRoot = Join-Path $env:LOCALAPPDATA "SeaLevelInquiryLab"
$activeDataLink = Join-Path $asciiRoot "active-data"
$asciiLink = Join-Path $asciiRoot "barystatic"
$createdActiveDataLink = $false
$createdLink = $false

New-Item -ItemType Directory -Path $activeDataSource -Force | Out-Null
if (-not (Test-Path -LiteralPath $barystaticSource)) {
    throw "Barystatic data folder not found: $barystaticSource"
}

try {
    if ($barystaticSource -match "[^\x00-\x7F]") {
        New-Item -ItemType Directory -Path $asciiRoot -Force | Out-Null
        if (Test-Path -LiteralPath $activeDataLink) {
            $existingActiveData = Get-Item -LiteralPath $activeDataLink
            if ($existingActiveData.LinkType -ne "Junction" -or $existingActiveData.Target -ne $activeDataSource) {
                throw "The local preview link already exists but points elsewhere: $activeDataLink"
            }
        } else {
            New-Item -ItemType Junction -Path $activeDataLink -Target $activeDataSource | Out-Null
            $createdActiveDataLink = $true
        }
        $env:DATA_DIR = $activeDataLink
        if (Test-Path -LiteralPath $asciiLink) {
            $existing = Get-Item -LiteralPath $asciiLink
            if ($existing.LinkType -ne "Junction" -or $existing.Target -ne $barystaticSource) {
                throw "The local preview link already exists but points elsewhere: $asciiLink"
            }
        } else {
            New-Item -ItemType Junction -Path $asciiLink -Target $barystaticSource | Out-Null
            $createdLink = $true
        }
        $env:BARYSTATIC_DATA_DIR = $asciiLink
        $env:BARYSTATIC_CATALOG = Join-Path $asciiLink "component_catalog.json"
        $env:GRACE_DATASET = Join-Path $asciiLink "grace_ocean_mass_fingerprint_1deg_monthly_200301_202304.nc"
        $env:CAUSE_COMPARISON_DATASET = $causeComparisonSource
    } else {
        $env:DATA_DIR = $activeDataSource
        $env:BARYSTATIC_DATA_DIR = $barystaticSource
        $env:BARYSTATIC_CATALOG = Join-Path $barystaticSource "component_catalog.json"
        $env:GRACE_DATASET = Join-Path $barystaticSource "grace_ocean_mass_fingerprint_1deg_monthly_200301_202304.nc"
        $env:CAUSE_COMPARISON_DATASET = $causeComparisonSource
    }

    $uvicornArgs = @("-m", "uvicorn", "app.main:app", "--app-dir", $backendRoot)
    if (-not $NoReload) {
        $uvicornArgs += "--reload"
    }
    & $PythonCommand @uvicornArgs
} finally {
    if ($createdActiveDataLink -and (Test-Path -LiteralPath $activeDataLink)) {
        $existingActiveData = Get-Item -LiteralPath $activeDataLink
        if ($existingActiveData.LinkType -eq "Junction" -and $existingActiveData.Target -eq $activeDataSource) {
            Remove-Item -LiteralPath $activeDataLink -Force
        }
    }
    if ($createdLink -and (Test-Path -LiteralPath $asciiLink)) {
        $existing = Get-Item -LiteralPath $asciiLink
        if ($existing.LinkType -eq "Junction" -and $existing.Target -eq $barystaticSource) {
            Remove-Item -LiteralPath $asciiLink -Force
        }
    }
}
