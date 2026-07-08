# Build dell'app portable Windows (HodlVault.exe).
# Eseguire da PowerShell nella RADICE del repo:
#     .\desktop\build-windows.ps1
#
# Prerequisiti: Python 3.12+, Node 18+, e (consigliato) un venv attivo.

$ErrorActionPreference = "Stop"

Write-Host "==> Build frontend" -ForegroundColor Cyan
Push-Location frontend
npm ci
npm run build
Pop-Location

Write-Host "==> Installazione dipendenze Python (backend + desktop)" -ForegroundColor Cyan
pip install -r backend/requirements.txt -r desktop/requirements-desktop.txt

Write-Host "==> PyInstaller" -ForegroundColor Cyan
pyinstaller --clean --noconfirm desktop/hodlvault.spec

Write-Host ""
Write-Host "OK -> dist\HodlVault.exe" -ForegroundColor Green
Write-Host "Portable: copiando la cartella dell'.exe, il DB (data\) viaggia con essa." -ForegroundColor Green
