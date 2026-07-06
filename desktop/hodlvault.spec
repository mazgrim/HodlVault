# -*- mode: python ; coding: utf-8 -*-
"""
Spec PyInstaller per l'app desktop HodlVault (onefile).

Va lanciato dalla RADICE del repo, dopo aver buildato il frontend:
    cd frontend && npm ci && npm run build && cd ..
    pyinstaller desktop/hodlvault.spec

Produce dist/HodlVault(.exe su Windows). Il frontend buildato viene incluso come
dati e servito dal backend (frontend_static risolve `<_MEIPASS>/frontend`).
"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

ROOT = os.path.abspath(os.getcwd())
BACKEND = os.path.join(ROOT, "backend")
FRONTEND_DIST = os.path.join(ROOT, "frontend", "dist")

if not os.path.isdir(FRONTEND_DIST):
    raise SystemExit(
        "frontend/dist non trovato: builda prima il frontend (npm run build)."
    )

# uvicorn/apscheduler/app caricano moduli dinamicamente → serve raccoglierli.
hiddenimports = []
for pkg in ("uvicorn", "apscheduler", "app"):
    hiddenimports += collect_submodules(pkg)
hiddenimports += ["email_validator"]

datas = [(FRONTEND_DIST, "frontend")]
binaries = []

# pywebview porta con sé binari/dati specifici per piattaforma.
_web_datas, _web_bins, _web_hidden = collect_all("webview")
datas += _web_datas
binaries += _web_bins
hiddenimports += _web_hidden

_icon_ico = os.path.join("desktop", "icon.ico")
_icon_png = os.path.join("desktop", "icon.png")
icon = _icon_ico if os.path.exists(_icon_ico) else (_icon_png if os.path.exists(_icon_png) else None)

a = Analysis(
    [os.path.join("desktop", "launcher.py")],
    pathex=[BACKEND],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HodlVault",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,   # nessuna finestra console; metti True per debug del primo build
    disable_windowed_traceback=False,
    icon=icon,
)
