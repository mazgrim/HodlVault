#!/usr/bin/env bash
# Build dell'AppImage Linux di HodlVault.
# Eseguire dalla RADICE del repo:  ./desktop/build-appimage.sh
#
# Prerequisiti:
#   - Python 3.12+, Node 18+
#   - runtime GUI per pywebview: GTK + WebKit2GTK (vedi requirements-desktop.txt)
#   - appimagetool nel PATH (https://github.com/AppImage/AppImageKit/releases)
set -euo pipefail

echo "==> Preflight"
command -v appimagetool >/dev/null 2>&1 || {
  echo "ERRORE: 'appimagetool' non è nel PATH."
  echo "        Scaricalo da https://github.com/AppImage/AppImageKit/releases,"
  echo "        rendilo eseguibile e mettilo nel PATH."
  exit 1
}

echo "==> Build frontend"
( cd frontend && npm ci && npm run build )

echo "==> Dipendenze Python (backend + desktop)"
pip install -r backend/requirements.txt -r desktop/requirements-desktop.txt

# pywebview su Linux si appoggia a GTK + WebKit2GTK *di sistema*: se manca,
# meglio saperlo adesso che a build finito.
python -c "import webview" >/dev/null 2>&1 || {
  echo "ERRORE: 'import webview' fallisce — mancano i runtime GUI di sistema."
  echo "        Debian/Ubuntu: sudo apt install python3-gi gir1.2-webkit2-4.1 libwebkit2gtk-4.1-0"
  exit 1
}

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
StartupWMClass=HodlVault
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
echo "Dati utente in ~/.local/share/HodlVault (XDG), NON accanto all'AppImage."
echo ""
echo "NOTA: questo AppImage non include GTK/WebKit2GTK (PyInstaller non li impacchetta)."
echo "      Gira su sistemi che hanno già webkit2gtk installato. Per renderlo davvero"
echo "      autonomo servirebbe linuxdeploy con il plugin GTK."
