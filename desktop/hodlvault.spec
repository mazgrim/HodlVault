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

# `collect_all('gi')` non si limita al package Python: trascina nel bundle
# l'intero stack GTK/GLib di *questa* macchina, e con esso la libstdc++ del suo
# compilatore. Ma la libwebkit NON viene impacchettata (PyInstaller non la vede:
# pywebview la carica via typelib a runtime), quindi sul sistema di destinazione
# la webkit *di sistema* finisce per essere risolta contro la libstdc++ *della
# build*. Su una build 22.04 letta da Debian 13:
#
#   Failed to load shared library 'libwebkit2gtk-4.1.so.0' referenced by the
#   typelib: libstdc++.so.6: version `CXXABI_1.3.15' not found
#   (required by /lib/x86_64-linux-gnu/libicui18n.so.76)
#
# Se pretendiamo webkit2gtk installato sul target (e lo pretendiamo), allora
# quel sistema ha già GTK, GLib e una libstdc++ almeno pari alla sua webkit:
# vanno prese da lì, non da qui. Restano bundlate solo libpython e le librerie
# di supporto dell'interprete (ssl, sqlite3, ffi, compressione…).
_SYSTEM_LIBS = (
    "libstdc++", "libgcc_s", "libatomic",
    "libglib-2.0", "libgobject-2.0", "libgio-2.0", "libgmodule-2.0", "libgirepository",
    "libgtk-3", "libgdk-3", "libgdk_pixbuf", "libatk", "libatspi",
    "libpango", "libcairo", "libharfbuzz", "libepoxy", "libfontconfig", "libfreetype",
    "libfribidi", "libgraphite2", "libpixman", "libthai", "libdatrie", "libxkbcommon",
    "libxcb-render", "libxcb-shm", "librsvg", "libglycin", "libpng16",
    "libdbus-1", "libselinux", "libsystemd", "libmount", "libblkid", "libuuid",
    "libpcre2-8", "libproxy", "libpxbackend", "libduktape", "liblcms2",
    "libcurl-gnutls", "libnghttp2", "librtmp", "libssh2", "libpsl", "libldap", "liblber",
    "libsasl2", "libgnutls", "libnettle", "libhogweed", "libtasn1", "libidn2",
    "libunistring", "libp11-kit", "libgmp", "libkrb5", "libk5crypto", "libgssapi_krb5",
    "libcom_err", "libkeyutils", "libbrotli", "libseccomp", "libxml2",
)


def _is_system_lib(dest: str) -> bool:
    return os.path.basename(dest).startswith(_SYSTEM_LIBS)


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

if _sysplat.platform.startswith("linux"):
    _before = len(a.binaries)
    a.binaries = [_e for _e in a.binaries if not _is_system_lib(_e[0])]
    print(f"spec: escluse {_before - len(a.binaries)} librerie di sistema dal bundle")

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
