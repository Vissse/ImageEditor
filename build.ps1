# Rebuilds PhotoBatchEditor.exe. Run from this project folder.
# PyInstaller's atomic file writes fail on very long/deep Windows paths
# (MAX_PATH), so if this project ever lives under a long path, build into
# a short one (e.g. C:\pbe_build) instead and copy the result back here.

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot

pip install -r (Join-Path $projectDir "requirements.txt")

python -m PyInstaller --noconfirm --onefile --windowed --name PhotoBatchEditor `
    --collect-all PySide6 `
    --icon (Join-Path $projectDir "icon.ico") `
    --add-data "$(Join-Path $projectDir 'icon.ico');." `
    (Join-Path $projectDir "main.py")

Copy-Item -Force (Join-Path $projectDir "dist\PhotoBatchEditor.exe") (Join-Path $projectDir "PhotoBatchEditor.exe")
Remove-Item -Recurse -Force (Join-Path $projectDir "build"), (Join-Path $projectDir "dist"), (Join-Path $projectDir "PhotoBatchEditor.spec") -ErrorAction SilentlyContinue
Write-Host "Hotovo: $projectDir\PhotoBatchEditor.exe"
