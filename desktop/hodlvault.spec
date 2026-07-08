# -*- mode: python ; coding: utf-8 -*-
"""
Spec PyInstaller per l'app desktop HodlVault (onefile).

Dopo aver buildato il frontend (npm run build), lanciare da qualunque cwd:
    pyinstaller desktop/hodlvault.spec

Produce dist/HodlVault(.exe su Windows). Il frontend buildato viene incluso come
dati e servito dal backend (frontend_static risolve `<_MEIPASS>/frontend`).

NB: PyInstaller risolve i path relativi rispetto alla cartella dello spec, quindi
qui tutto è basato su SPECPATH (dir dello spec, fornita da PyInstaller) per
funzionare indipendentemente dalla directory di lancio.
"""
import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

SPEC_DIR = SPECPATH                       # .../HodlVault/desktop (iniettata da PyInstaller)
ROOT = os.path.dirname(SPEC_DIR)          # radice del repo
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
# h11: implementazione HTTP usata da uvicorn (import dinamico); email_validator:
# usato da pydantic EmailStr. Entrambi vanno dichiarati esplicitamente.
hiddenimports += ["h11", "email_validator"]

datas = [(FRONTEND_DIST, "frontend")]
binaries = []

# pywebview porta con sé binari/dati specifici per piattaforma.
_web_datas, _web_bins, _web_hidden = collect_all("webview")
datas += _web_datas
binaries += _web_bins
hiddenimports += _web_hidden

# Su Linux il backend GTK di pywebview importa `gi` dinamicamente: senza
# raccoglierlo, l'AppImage parte e poi non trova la webview.
import sys as _sysplat
if _sysplat.platform.startswith("linux"):
    try:
        _gi_datas, _gi_bins, _gi_hidden = collect_all("gi")
        datas += _gi_datas
        binaries += _gi_bins
        hiddenimports += _gi_hidden
    except Exception as _exc:  # gi assente: lo segnala il preflight dello script
        print(f"WARNING: collect_all('gi') fallito: {_exc}")

import sys as _sys

_icon_ico = os.path.join(SPEC_DIR, "icon.ico")
_icon_png = os.path.join(SPEC_DIR, "icon.png")
if _sys.platform.startswith("win"):
    icon = _icon_ico if os.path.exists(_icon_ico) else None
elif _sys.platform == "darwin":
    icon = _icon_png if os.path.exists(_icon_png) else None
else:
    # Linux: PyInstaller ignora l'icona sugli eseguibili ELF; per l'AppImage la
    # fornisce il file .desktop + hodlvault.png nell'AppDir.
    icon = None

a = Analysis(
    [os.path.join(SPEC_DIR, "launcher.py")],
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
    # UPX peggiora sensibilmente i falsi positivi degli antivirus sui binari
    # PyInstaller: per i binari distribuiti conviene lasciarlo disattivato.
    upx=False,
    runtime_tmpdir=None,
    console=False,   # nessuna finestra console; metti True per debug del primo build
    disable_windowed_traceback=False,
    icon=icon,
)
