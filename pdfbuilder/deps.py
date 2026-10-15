"""Detection of optional external programs, with actionable install hints."""
from __future__ import annotations

import shutil
import subprocess
from functools import lru_cache

from pdfbuilder.job import ToolError

# name -> (candidate binaries, apt package, what it unlocks)
EXTERNAL = {
    "soffice": (("soffice", "libreoffice"), "libreoffice",
                "Office document conversion (DOCX/XLSX/PPTX/ODT/RTF)"),
    "tesseract": (("tesseract",), "tesseract-ocr",
                  "Extra OCR languages and orientation detection "
                  "(basic OCR already works without it)"),
    "ghostscript": (("gs",), "ghostscript", "Strong PDF compression and PDF/A"),
    "qpdf": (("qpdf",), "qpdf", "Structural repair and linearisation"),
    "pdftoppm": (("pdftoppm",), "poppler-utils", "Fast page rasterising"),
}


@lru_cache(maxsize=None)
def find(name: str) -> str | None:
    cands, _, _ = EXTERNAL.get(name, ((name,), "", ""))
    for c in cands:
        p = shutil.which(c)
        if p:
            return p
    return None


def have(name: str) -> bool:
    return find(name) is not None


def require(name: str) -> str:
    p = find(name)
    if p:
        return p
    _, pkg, what = EXTERNAL.get(name, ((), name, ""))
    raise ToolError(
        f"'{name}' is not installed, so {what or name} is unavailable.\n\n"
        f"Install it with:\n    sudo apt install {pkg}\n\n"
        f"Then reopen PDF Builder (or use Help → Re-check dependencies)."
    )


def run(cmd, *, timeout=600, cwd=None) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd)
    except FileNotFoundError as e:
        raise ToolError(f"Program not found: {e.filename}") from e
    except subprocess.TimeoutExpired:
        raise ToolError(f"{cmd[0]} timed out after {timeout}s.")
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        raise ToolError(f"{cmd[0]} failed:\n" + "\n".join(tail[-8:]))
    return r


def report() -> list[tuple[str, bool, str, str]]:
    out = []
    for name, (_, pkg, what) in EXTERNAL.items():
        out.append((name, have(name), pkg, what))
    return out


def reset_cache() -> None:
    find.cache_clear()
