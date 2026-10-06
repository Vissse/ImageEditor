# Builds the app (PyInstaller, one folder) and the installer (Inno Setup).
# Result: Output\ImageEditor_Setup.exe. Run from this project folder.
# Needs Inno Setup 6 (https://jrsoftware.org/isinfo.php).

$projectDir = $PSScriptRoot
Set-Location $projectDir

function Run-Step([string]$what, [scriptblock]$command) {
    & $command
    if ($LASTEXITCODE -ne 0) { throw "$what selhalo (kod $LASTEXITCODE)" }
}

Run-Step "Instalace zavislosti" { pip install -q --disable-pip-version-check -r requirements.txt }

Run-Step "PyInstaller" {
    python -m PyInstaller --noconfirm --onedir --windowed --name ImageEditor `
        --icon icon.ico `
        --add-data "icon.ico;." `
        main.py
}

$env:APP_VERSION = python -c "from core.config import CURRENT_VERSION; print(CURRENT_VERSION)"

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) nenalezen." }

Run-Step "Inno Setup" { & $iscc inno.iss }

Remove-Item -Recurse -Force build, ImageEditor.spec -ErrorAction SilentlyContinue
Write-Host "Hotovo: $projectDir\Output\ImageEditor_Setup.exe (verze $env:APP_VERSION)"
