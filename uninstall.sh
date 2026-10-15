#!/usr/bin/env bash
# Remove the desktop entry, icon and virtual environment. Your own files and
# anything in the output folder are left untouched.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rm -f "$HOME/.local/share/applications/pdf-builder.desktop"
rm -f "$HOME/.local/share/icons/hicolor/256x256/apps/pdf-builder.png"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
read -rp "Also delete the Python environment in .venv? [y/N] " a
[[ "${a,,}" == "y" ]] && rm -rf "$here/.venv" && echo "Removed .venv"
echo "Settings and presets are kept in ~/.config/pdf-builder (delete by hand if you want them gone)."
