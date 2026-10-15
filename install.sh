#!/usr/bin/env bash
# PDF Builder - set up the Python environment and (optionally) a desktop entry.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m !\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- python
if ! command -v python3 >/dev/null; then
  echo "python3 is required. Install it with: sudo apt install python3" >&2
  exit 1
fi
ver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [[ $(python3 -c 'import sys; print(sys.version_info >= (3,10))') != "True" ]]; then
  echo "Python 3.10 or newer is required (found $ver)." >&2
  exit 1
fi
say "Python $ver"

if [[ ! -d .venv ]]; then
  say "Creating the virtual environment in .venv"
  python3 -m venv .venv || {
    echo "Could not create a virtual environment." >&2
    echo "On Debian/Ubuntu run: sudo apt install python3-venv" >&2
    exit 1; }
fi

say "Installing Python packages (a few hundred MB, this takes a minute)"
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install --quiet -r requirements.txt
say "Python packages installed"

# ------------------------------------------------------ optional programs
missing=()
for pair in "soffice:libreoffice" "tesseract:tesseract-ocr" "gs:ghostscript" \
            "qpdf:qpdf" "pdftoppm:poppler-utils"; do
  bin="${pair%%:*}"; pkg="${pair##*:}"
  command -v "$bin" >/dev/null || missing+=("$pkg")
done
if ((${#missing[@]})); then
  warn "Optional system components not found: ${missing[*]}"
  echo "   OCR already works out of the box with the built-in recogniser."
  echo "   These unlock Office conversion, extra OCR languages and the"
  echo "   strongest compression:"
  echo "   Install them with:"
  echo "       sudo apt install ${missing[*]}"
  echo "   Extra OCR languages, for example:"
  echo "       sudo apt install tesseract-ocr-hin tesseract-ocr-fra"
else
  say "All optional components are present"
fi

# ----------------------------------------------------------- desktop entry
apps="$HOME/.local/share/applications"
icons="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$apps" "$icons"
.venv/bin/python - "$icons/pdf-builder.png" <<'PY' 2>/dev/null || true
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath("install.sh")))
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from pdfbuilder.ui import icons
icons.write_app_icon(sys.argv[1], 256)
PY

cat > "$apps/pdf-builder.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=PDF Builder
GenericName=PDF Toolkit
Comment=Merge, split, convert, sign, compress and edit PDFs - entirely offline
Exec=$here/run.sh %F
Icon=$icons/pdf-builder.png
Terminal=false
Categories=Office;Graphics;Publishing;Utility;
Keywords=pdf;merge;split;compress;convert;scan;ocr;sign;form;image;
MimeType=application/pdf;image/jpeg;image/png;image/webp;image/tiff;image/bmp;application/zip;text/markdown;text/html;
StartupNotify=true
StartupWMClass=pdf-builder
DESKTOP
chmod +x "$apps/pdf-builder.desktop" run.sh
update-desktop-database "$apps" 2>/dev/null || true
say "Desktop entry installed - look for 'PDF Builder' in your app menu"

echo
say "Done. Start it with:  ./run.sh"
