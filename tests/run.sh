#!/usr/bin/env bash
# Run the whole PDF Builder test suite.
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
py="$root/.venv/bin/python"
[[ -x "$py" ]] || { echo "Run ./install.sh first." >&2; exit 1; }
export PDFBUILDER_TEST_DIR="${PDFBUILDER_TEST_DIR:-$here/_work}"
mkdir -p "$PDFBUILDER_TEST_DIR"
fail=0

step() { printf '\n\033[1;34m== %s\033[0m\n' "$*"; }

step "Building sample files"
"$py" "$here/make_fixtures.py" "$PDFBUILDER_TEST_DIR/fixtures" || fail=1

step "Every tool runs and writes real output"
"$py" "$here/smoke.py" "$PDFBUILDER_TEST_DIR/fixtures" "$PDFBUILDER_TEST_DIR/out" \
  2>&1 | grep -vE "^(MuPDF error|\[INFO\]|warning:)" | tail -40 || fail=1

step "Deep behaviour checks"
"$py" "$here/deep.py" 2>&1 | grep -vE "^(MuPDF error|\[INFO\]|warning:)" | tail -45 || fail=1

step "User interface: every panel builds and works"
"$py" "$here/ui_test.py" 2>&1 | grep -vE "^(MuPDF error|warning:)" | tail -30 || fail=1

step "OCR pipeline"
if command -v tesseract >/dev/null; then
  echo "tesseract found - both engines will be exercised"
else
  echo "tesseract not installed - the built-in recogniser is used,"
  echo "and the tesseract code path is exercised with tests/fakebin"
  export PATH="$here/fakebin:$PATH"
fi
PDFBUILDER_ROOT="$root" "$py" - <<'PY'
import os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent if "__file__" in dir() else Path.cwd()
root = Path(os.environ["PDFBUILDER_ROOT"]); sys.path.insert(0, str(root))
work = Path(os.environ["PDFBUILDER_TEST_DIR"])
from pdfbuilder import deps, registry
registry.load_all(); deps.reset_cache()
from pdfbuilder.registry import REGISTRY
from pdfbuilder.job import Ctx
import pymupdf as fitz
from pdfbuilder.core.ocr import engine_choices, have_rapidocr
print("engines offered:", engine_choices())
t = REGISTRY["ocr_pdf"]
for engine in [e for e in engine_choices() if e != "automatic"]:
    ctx = Ctx([work/"fixtures"/"scanned.pdf"],
              {**t.defaults(), "engine": engine},
              work/"ocr"/engine.split()[0], log=lambda m: None)
    made = t.fn(ctx) or ctx.produced; ctx.cleanup()
    d = fitz.open([m for m in made if m.suffix == ".pdf"][0])
    words = len(" ".join(d[i].get_text() for i in range(d.page_count)).split())
    found = bool(d[0].search_for("INVOICE") or d[0].search_for("invoice"))
    print(f"  {engine:32s} {words:3d} words, searchable: {found}")
    assert found, f"{engine} produced nothing searchable"
    d.close()
PY

printf '\n\033[1;32m== suite finished\033[0m  (results in %s)\n' "$PDFBUILDER_TEST_DIR"
exit $fail
