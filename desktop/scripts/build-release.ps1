param(
    [switch]$SkipSidecar,
    [switch]$SkipInstaller,
    # Number of most-recent installers to retain in desktop/release/.
    # Older installer .exe files (and their .blockmap siblings) are pruned
    # after a successful build. Pass 0 to disable pruning.
    [int]$KeepInstallers = 3
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

# Prune old installers — each NSIS .exe is ~240 MB so it adds up fast.
# Keep the N most recent by mtime; remove older .exe + matching .blockmap
# files. Also sweep orphan .blockmap files left over from prior cleanups.
if (-not $SkipInstaller -and $KeepInstallers -gt 0) {
    $releaseDir = Join-Path $Desktop "release"
    if (Test-Path $releaseDir) {
        $installers = @(
            Get-ChildItem -Path $releaseDir -Filter "NexGen-BBPro Setup *.exe" -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending
        )
        if ($installers.Count -gt $KeepInstallers) {
            $toRemove = $installers | Select-Object -Skip $KeepInstallers
            Write-Host ("`n[prune] Removing {0} old installer(s); keeping {1} most recent." -f $toRemove.Count, $KeepInstallers) -ForegroundColor Cyan
            foreach ($file in $toRemove) {
                Write-Host "  rm $($file.Name)"
                Remove-Item $file.FullName -Force
                $blockmap = "$($file.FullName).blockmap"
                if (Test-Path $blockmap) { Remove-Item $blockmap -Force }
            }
        }
        # Sweep orphan .blockmap files (no matching .exe in the keep set).
        $kept = @($installers | Select-Object -First $KeepInstallers | ForEach-Object { $_.Name })
        $blockmaps = @(Get-ChildItem -Path $releaseDir -Filter "NexGen-BBPro Setup *.exe.blockmap" -File -ErrorAction SilentlyContinue)
        foreach ($bm in $blockmaps) {
            $exeName = $bm.Name -replace '\.blockmap$', ''
            if ($kept -notcontains $exeName) {
                Write-Host "  rm $($bm.Name) (orphan blockmap)"
                Remove-Item $bm.FullName -Force
            }
        }
    }
}

Write-Host "`nDone. Look in desktop/release/ for the installer." -ForegroundColor Green
