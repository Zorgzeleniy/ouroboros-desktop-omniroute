# Ouroboros Windows Build Script
# Builds standalone .exe using PyInstaller

Write-Host "=== Ouroboros Windows Build ===" -ForegroundColor Cyan

# Check Python
Write-Host "`nChecking Python..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python not found. Install Python 3.10+ first." -ForegroundColor Red
    exit 1
}
Write-Host "Found: $pythonVersion" -ForegroundColor Green

# Install PyInstaller and Windows dependencies
Write-Host "`nChecking PyInstaller..." -ForegroundColor Yellow
python -m pip show pyinstaller > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller..." -ForegroundColor Yellow
    python -m pip install pyinstaller
}

Write-Host "Installing Windows dependencies..." -ForegroundColor Yellow
python -m pip install pywin32 pywin32-ctypes --upgrade

# Run pywin32 post-install script (required for pywintypes)
Write-Host "Running pywin32 post-install..." -ForegroundColor Yellow
python -c "import sys; from pathlib import Path; site_packages = Path(sys.executable).parent / 'Lib' / 'site-packages'; pywin32_system32 = site_packages / 'pywin32_system32'; [print(f'Found: {pywin32_system32}') if pywin32_system32.exists() else print('pywin32_system32 not found')]"
python -m pip install --force-reinstall --no-cache-dir pywin32

Write-Host "PyInstaller ready" -ForegroundColor Green

# Clean old build
Write-Host "`nCleaning old build..." -ForegroundColor Yellow
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "Ouroboros.spec") { Remove-Item -Force "Ouroboros.spec" }

# Build with PyInstaller
Write-Host "`nBuilding executable..." -ForegroundColor Yellow
python -m PyInstaller `
    --name="Ouroboros" `
    --onefile `
    --windowed `
    --icon="assets/icon.ico" `
    --add-data="web;web" `
    --add-data="prompts;prompts" `
    --add-data="docs;docs" `
    --add-data="BIBLE.md;." `
    --add-data="VERSION;." `
    --add-data="README.md;." `
    --hidden-import="starlette" `
    --hidden-import="uvicorn" `
    --hidden-import="multiprocessing" `
    --hidden-import="anthropic" `
    --hidden-import="openai" `
    --collect-all="starlette" `
    --collect-all="uvicorn" `
    server.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nERROR: Build failed!" -ForegroundColor Red
    exit 1
}

# Create release package
Write-Host "`nCreating release package..." -ForegroundColor Yellow
$releaseDir = "dist\Ouroboros-windows-x64"
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

# Copy executable
Copy-Item "dist\Ouroboros.exe" "$releaseDir\"

# Copy required files
Copy-Item "README.md" "$releaseDir\"
Copy-Item "LICENSE" "$releaseDir\" -ErrorAction SilentlyContinue
Copy-Item "VERSION" "$releaseDir\"

# Create zip
Write-Host "`nCreating zip archive..." -ForegroundColor Yellow
Compress-Archive -Path "$releaseDir\*" -DestinationPath "dist\Ouroboros-windows-x64.zip" -Force

# Cleanup
Remove-Item -Recurse -Force "$releaseDir"
Remove-Item -Recurse -Force "build"
Remove-Item -Force "Ouroboros.spec"

Write-Host "`n=== Build Complete ===" -ForegroundColor Green
Write-Host "Output: dist\Ouroboros-windows-x64.zip" -ForegroundColor Cyan
Write-Host "`nYou can now upload this to GitHub Releases." -ForegroundColor Yellow
