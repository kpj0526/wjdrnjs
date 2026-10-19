<#
.SYNOPSIS
  Build the Windows release of R2 Target Helper: tests -> PyInstaller (one folder) -> self-test of
  the built exe -> zip + SHA256.

.DESCRIPTION
  Reproducible inputs: a fresh .build-venv from the pinned requirements-build.txt, PYTHONHASHSEED=0,
  SOURCE_DATE_EPOCH from the last git commit, --clean PyInstaller build.

  Output (repository root):
    dist\R2TargetHelper\                       unpacked app (R2TargetHelper.exe + _internal\)
    dist\R2TargetHelper-<ver>-win64.zip        the download
    dist\R2TargetHelper-<ver>-win64.zip.sha256
    build\selftest.json                        result of the exe's offline self-test

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
  powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Python C:\Python312\python.exe -SkipTests
#>
param(
    [string]$Python = "",
    [switch]$SkipTests,
    [switch]$KeepVenv
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked([string]$what, [scriptblock]$cmd) {
    Write-Host "==> $what"
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

# --- interpreter ---------------------------------------------------------------
if (-not $Python) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $Python = (& py -3.12 -c "import sys; print(sys.executable)") 2>$null }
    if (-not $Python) { $Python = "python" }
}
$ver = (& $Python -c "import sys; print('%d.%d' % sys.version_info[:2])")
if ($LASTEXITCODE -ne 0) { throw "Python not found: $Python" }
Write-Host "Using Python $ver at $Python"

$Version = (Select-String -Path "r2clicker\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
$Name = "R2TargetHelper"
$ZipName = "$Name-$Version-win64.zip"

# --- reproducibility knobs -------------------------------------------------------
$env:PYTHONHASHSEED = "0"
$env:PYTHONDONTWRITEBYTECODE = "1"
$epoch = (& git log -1 --format=%ct) 2>$null
if ($LASTEXITCODE -eq 0 -and $epoch) { $env:SOURCE_DATE_EPOCH = "$epoch" }

# --- clean build venv from pinned requirements -----------------------------------
$Venv = Join-Path $Root ".build-venv"
if ((Test-Path $Venv) -and -not $KeepVenv) { Remove-Item -Recurse -Force $Venv }
if (-not (Test-Path $Venv)) { Invoke-Checked "create build venv" { & $Python -m venv $Venv } }
$VPy = Join-Path $Venv "Scripts\python.exe"
Invoke-Checked "install pinned build requirements" {
    & $VPy -m pip install --disable-pip-version-check --no-input -q -r requirements-build.txt
}

# --- tests -------------------------------------------------------------------------
if (-not $SkipTests) {
    Invoke-Checked "run tests" { & $VPy -m pytest -q -p no:cacheprovider tests }
}

# --- PyInstaller -------------------------------------------------------------------
foreach ($d in @("build\work", "build\dist", "dist\$Name", "dist\$ZipName", "dist\$ZipName.sha256")) {
    if (Test-Path $d) { Remove-Item -Recurse -Force $d }
}
Invoke-Checked "PyInstaller" {
    & $VPy -m PyInstaller --noconfirm --clean --log-level WARN `
        --distpath build\dist --workpath build\work packaging\R2TargetHelper.spec
}

# --- stage the release folder -----------------------------------------------------
New-Item -ItemType Directory -Force "dist" | Out-Null
Copy-Item -Recurse "build\dist\$Name" "dist\$Name"
Copy-Item "packaging\README_USER.txt" "dist\$Name\README.txt"
Copy-Item "README.md" "dist\$Name\README_FULL.md"
# example only: the app writes settings.json itself, so an update never overwrites user settings
Invoke-Checked "write settings.example.json" {
    & $VPy -c "from r2clicker.config import Settings; Settings().save(r'dist\$Name\settings.example.json')"
}

# --- the customer PC has no Python: everything the exe loads must be in the folder ----------
$need = @("$Name.exe", "_internal\python3*.dll", "_internal\VCRUNTIME140.dll", "_internal\_tkinter.pyd",
          "_internal\tcl86t.dll", "_internal\tk86t.dll", "_internal\_tcl_data", "_internal\_tk_data",
          "_internal\assets\sample_1600x900.png")
$missing = @($need | Where-Object { -not (Test-Path "dist\$Name\$_") })
if ($missing) { throw "release folder is missing: $($missing -join ', ')" }

# --- self-test the built exe (offline, no clicks; isolated data folder) --------------
$stHome = Join-Path $Root "build\selftest-home"
if (Test-Path $stHome) { Remove-Item -Recurse -Force $stHome }
New-Item -ItemType Directory -Force $stHome | Out-Null
$stOut = Join-Path $Root "build\selftest.json"
if (Test-Path $stOut) { Remove-Item -Force $stOut }
$env:R2_HELPER_HOME = $stHome
# R2_SKIP_DESKTOP_TESTS=1 (locked/headless build machine): the exe's self-test then skips the one
# step that maps a small window for PrintWindow; everything else still runs.
$noWindow = $env:R2_SKIP_DESKTOP_TESTS -eq "1"
if ($noWindow) { $env:R2_SELFTEST_NO_WINDOW = "1" }
Write-Host "==> self-test of dist\$Name\$Name.exe$(if ($noWindow) { ' (no window)' })"
$p = Start-Process -FilePath "dist\$Name\$Name.exe" -ArgumentList @("--selftest", "`"$stOut`"") -Wait -PassThru
Remove-Item Env:\R2_HELPER_HOME
if ($noWindow) { Remove-Item Env:\R2_SELFTEST_NO_WINDOW }
if (-not (Test-Path $stOut)) { throw "self-test wrote no result (exit $($p.ExitCode))" }
$st = Get-Content $stOut -Raw -Encoding UTF8 | ConvertFrom-Json
if ($p.ExitCode -ne 0 -or -not $st.passed) {
    Get-Content $stOut -Encoding UTF8 | Write-Host
    throw "self-test failed (exit $($p.ExitCode))"
}
if (Get-ChildItem "dist\$Name" -Filter "settings.json" -ErrorAction SilentlyContinue) {
    throw "settings.json leaked into the release folder"
}
Write-Host "    self-test passed (frozen=$($st.frozen))"

# --- zip + checksum -------------------------------------------------------------------
Compress-Archive -Path "dist\$Name" -DestinationPath "dist\$ZipName" -CompressionLevel Optimal
$hash = (Get-FileHash "dist\$ZipName" -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "dist\$ZipName.sha256" -Value "$hash  $ZipName" -Encoding ASCII
$size = [math]::Round((Get-Item "dist\$ZipName").Length / 1MB, 1)
Write-Host "==> done: dist\$ZipName ($size MB) sha256 $hash"
