#!/usr/bin/env bash
# Build dell'AppImage Linux di HodlVault.
# Eseguire dalla RADICE del repo:  ./desktop/build-appimage.sh
#
# Prerequisiti:
#   - Python 3.12+, Node 18+
#   - runtime GUI per pywebview: GTK + WebKit2GTK (vedi requirements-desktop.txt)
#   - appimagetool nel PATH (https://github.com/AppImage/AppImageKit/releases)
set -euo pipefail

echo "==> Build frontend"
( cd frontend && npm ci && npm run build )

echo "==> Dipendenze Python (backend + desktop)"
pip install -r backend/requirements.txt -r desktop/requirements-desktop.txt

echo "==> PyInstaller (binario onefile)"
pyinstaller --clean --noconfirm desktop/hodlvault.spec
# -> dist/HodlVault

echo "==> Composizione AppDir"
APPDIR="dist/HodlVault.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp dist/HodlVault "$APPDIR/usr/bin/HodlVault"
chmod +x "$APPDIR/usr/bin/HodlVault"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/HodlVault" "$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/HodlVault.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=HodlVault
Exec=HodlVault
Icon=hodlvault
Categories=Office;Finance;
Terminal=false
EOF

# Icona (usa desktop/icon.png se presente, altrimenti un placeholder 1x1).
if [ -f desktop/icon.png ]; then
  cp desktop/icon.png "$APPDIR/hodlvault.png"
else
  printf '\x89PNG\r\n\x1a\n' > "$APPDIR/hodlvault.png"  # placeholder: sostituisci con un'icona vera
fi

echo "==> appimagetool"
appimagetool "$APPDIR" dist/HodlVault-x86_64.AppImage

echo ""
echo "OK -> dist/HodlVault-x86_64.AppImage"
echo "Dati utente in ~/.local/share/HodlVault (XDG)."
