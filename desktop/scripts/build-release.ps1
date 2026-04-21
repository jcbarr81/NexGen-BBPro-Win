param(
    [switch]$SkipSidecar,
    [switch]$SkipInstaller
)

# Build the complete NexGen-BBPro Electron installer end-to-end.
# Runs from the desktop/ directory; invokes PyInstaller at the repo root,
# then renderer build, then electron-builder.

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Desktop = Resolve-Path (Join-Path $PSScriptRoot "..")

# Honor $env:NEXGEN_PYTHON so the build uses the same interpreter the
# runtime sidecar does. Falls back to `python` on PATH when not set.
$PythonExe = if ($env:NEXGEN_PYTHON) { $env:NEXGEN_PYTHON } else { "python" }

Write-Host "== Build release ==" -ForegroundColor Cyan
Write-Host "  Repo:    $RepoRoot"
Write-Host "  Desktop: $Desktop"
Write-Host "  Python:  $PythonExe"

if (-not $SkipSidecar) {
    Write-Host "`n[1/3] Building Python sidecar..." -ForegroundColor Cyan
    Push-Location $RepoRoot
    try {
        & $PythonExe -m pip install --quiet pyinstaller
        & $PythonExe -m PyInstaller --noconfirm packaging/sidecar.spec
        if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "`n[1/3] Sidecar skipped (--SkipSidecar)"
}

Write-Host "`n[2/3] Building Electron renderer..." -ForegroundColor Cyan
Push-Location $Desktop
try {
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "renderer build failed" }

    if (-not $SkipInstaller) {
        Write-Host "`n[3/3] Packaging NSIS installer..." -ForegroundColor Cyan
        npx electron-builder --win nsis
        if ($LASTEXITCODE -ne 0) { throw "electron-builder failed" }
    } else {
        Write-Host "`n[3/3] Installer skipped (--SkipInstaller)"
    }
} finally {
    Pop-Location
}

Write-Host "`nDone. Look in desktop/release/ for the installer." -ForegroundColor Green
