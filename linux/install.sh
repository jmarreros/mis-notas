#!/usr/bin/env bash
# Instala Mis Notas para el usuario actual (sin root):
#   ~/.local/bin/misnotas                       lanzador (ejecuta el código de esta carpeta)
#   ~/.local/share/applications/…desktop        entrada en el menú de aplicaciones
#   ~/.local/share/icons/hicolor/…/…svg         icono
# Desinstalar: ./install.sh --uninstall  (las notas en ~/.local/share/misnotas se conservan)
set -euo pipefail
cd "$(dirname "$0")"
SRC="$(pwd)"
APP_ID=com.jmarreros.misnotas
BIN="$HOME/.local/bin/misnotas"
DESKTOP="$HOME/.local/share/applications/$APP_ID.desktop"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/$APP_ID.svg"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$BIN" "$DESKTOP" "$ICON"
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
  echo "Desinstalada. Tus notas siguen en ~/.local/share/misnotas."
  exit 0
fi

# Dependencias del sistema: GTK 4, PyGObject y libsecret.
if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Secret", "1"); from gi.repository import Gtk, Secret' 2>/dev/null; then
  echo "Faltan dependencias. Instálalas con el gestor de paquetes de tu distribución:"
  echo "  Arch/Omarchy:  sudo pacman -S --needed python-gobject gtk4 libsecret"
  echo "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-secret-1"
  echo "  Fedora:        sudo dnf install python3-gobject gtk4 libsecret"
  exit 1
fi

mkdir -p "$(dirname "$BIN")" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
cat > "$BIN" <<LAUNCHER
#!/bin/sh
PYTHONPATH="$SRC\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m misnotas "\$@"
LAUNCHER
chmod +x "$BIN"
cp misnotas/resources/icons/hicolor/scalable/apps/$APP_ID.svg "$ICON"
cat > "$DESKTOP" <<ENTRY
[Desktop Entry]
Type=Application
Name=Mis Notas
Comment=Notas con sincronización propia, importación de Evernote
Exec=$BIN
Icon=$APP_ID
StartupWMClass=$APP_ID
Categories=Office;Utility;
Keywords=notas;notes;evernote;
Terminal=false
ENTRY
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Instalada. Ábrela desde el lanzador de aplicaciones o con: misnotas"
