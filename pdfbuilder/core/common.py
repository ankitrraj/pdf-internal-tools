"""Shared helpers for the core operations."""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf as fitz

from pdfbuilder.job import ToolError

PDF_EXT = {".pdf"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp",
             ".gif", ".heic", ".heif", ".ppm", ".pgm"}

PAGE_SIZES = {
    "A4": (595.28, 841.89),
    "A3": (841.89, 1190.55),
    "A5": (419.53, 595.28),
    "Letter": (612.0, 792.0),
    "Legal": (612.0, 1008.0),
    "Tabloid": (792.0, 1224.0),
}

MM = 72.0 / 25.4


def open_pdf(path, password: str = "") -> fitz.Document:
    path = Path(path)
    if not path.exists():
        raise ToolError(f"File not found: {path}")
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise ToolError(f"Could not open {path.name}: {e}") from e
    if doc.needs_pass:
        if not doc.authenticate(password or ""):
            doc.close()
            raise ToolError(
                f"{path.name} is password-protected. Enter the correct "
                f"password in the 'Password' field to continue."
            )
    return doc


def is_pdf(p) -> bool:
    return Path(p).suffix.lower() in PDF_EXT


def is_image(p) -> bool:
    return Path(p).suffix.lower() in IMAGE_EXT


def require_pdfs(ctx, at_least: int = 1):
    pdfs = [p for p in ctx.inputs if is_pdf(p)]
    if len(pdfs) < at_least:
        raise ToolError(f"Select at least {at_least} PDF file(s).")
    return pdfs


def require_images(ctx, at_least: int = 1):
    imgs = [p for p in ctx.inputs if is_image(p)]
    if len(imgs) < at_least:
        raise ToolError(f"Select at least {at_least} image file(s).")
    return imgs


# ------------------------------------------------------------- page ranges

def parse_pages(spec: str, n: int, *, default_all: bool = True) -> list[int]:
    """Turn a page specification into zero-based page indices.

    '1-3,7,9-'  explicit pages and ranges; an open end means 'to the end'
    '-3'        the same as '1-3'
    'all' / 'odd' / 'even' / 'last'   keywords
    '2-last'    counts from the end

    Out-of-range numbers are clamped, duplicates are dropped, and the given
    order is preserved so '3,1,2' really does mean that order.
    """
    spec = (spec or "").strip().lower()
    if not spec or spec in {"all", "*"}:
        if default_all:
            return list(range(n))
        raise ToolError("No pages specified.")
    if spec == "odd":
        return [i for i in range(n) if i % 2 == 0]
    if spec == "even":
        return [i for i in range(n) if i % 2 == 1]

    out: list[int] = []
    for chunk in re.split(r"[,\s;]+", spec):
        if not chunk:
            continue
        chunk = chunk.replace("last", str(n))
        m = re.fullmatch(r"(-?\d+)?\s*-\s*(-?\d+)?", chunk)
        if m and (m.group(1) or m.group(2)):
            a = _one(m.group(1), n, 1)
            b = _one(m.group(2), n, n)
            if a > b:
                a, b = b, a
            out.extend(range(a - 1, b))
        else:
            try:
                out.append(_one(chunk, n, None) - 1)
            except (TypeError, ValueError):
                raise ToolError(f"Could not understand page range: {chunk!r}")
    seen, uniq = set(), []
    for i in out:
        if 0 <= i < n and i not in seen:
            seen.add(i)
            uniq.append(i)
    if not uniq:
        raise ToolError(f"Page range {spec!r} does not match any of the "
                        f"{n} page(s) in this document.")
    return uniq


def _one(tok, n: int, fallback):
    if tok is None or tok == "":
        if fallback is None:
            raise ValueError("empty")
        return fallback
    v = int(tok)
    if v < 0:
        v = n + 1 + v
    return max(1, min(n, v))


def fmt_pages(idxs) -> str:
    """Inverse-ish: compact 1-based description for logs."""
    idxs = sorted(set(idxs))
    if not idxs:
        return "none"
    parts, start, prev = [], idxs[0], idxs[0]
    for i in idxs[1:]:
        if i == prev + 1:
            prev = i
            continue
        parts.append(f"{start+1}" if start == prev else f"{start+1}-{prev+1}")
        start = prev = i
    parts.append(f"{start+1}" if start == prev else f"{start+1}-{prev+1}")
    return ",".join(parts)


# -------------------------------------------------------------------- misc

def parse_color(s, default=(0, 0, 0)):
    """'#ff0000' / 'red' / '255,0,0' -> (r,g,b) floats 0..1"""
    named = {"black": (0, 0, 0), "white": (1, 1, 1), "red": (1, 0, 0),
             "green": (0, .6, 0), "blue": (0, 0, 1), "yellow": (1, .95, 0),
             "orange": (1, .55, 0), "pink": (1, .4, .7), "cyan": (0, .8, .9),
             "grey": (.5, .5, .5), "gray": (.5, .5, .5)}
    if s is None:
        return default
    if isinstance(s, (tuple, list)):
        v = tuple(float(x) for x in s[:3])
        return tuple(x / 255 if x > 1 else x for x in v)
    s = str(s).strip().lower()
    if s in named:
        return named[s]
    if s.startswith("#"):
        s = s[1:]
    if re.fullmatch(r"[0-9a-f]{6}", s):
        return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    if re.fullmatch(r"[0-9a-f]{3}", s):
        return tuple(int(c * 2, 16) / 255 for c in s)
    m = re.findall(r"[\d.]+", s)
    if len(m) >= 3:
        v = [float(x) for x in m[:3]]
        return tuple(x / 255 if x > 1 else x for x in v)
    return default


def to_hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in rgb[:3])


FONT_CHOICES = ("helv", "tiro", "cour", "hebo", "tibo", "cobo", "hei", "tiit")
FONT_LABELS = {
    "helv": "Helvetica", "hebo": "Helvetica Bold",
    "tiro": "Times", "tibo": "Times Bold", "tiit": "Times Italic",
    "cour": "Courier", "cobo": "Courier Bold", "hei": "Helvetica (CJK)",
}


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def save_pdf(doc: fitz.Document, path, *, garbage=3, deflate=True,
             clean=True, linear=False, **kw) -> Path:
    path = Path(path)
    try:
        doc.save(str(path), garbage=garbage, deflate=deflate, clean=clean,
                 linear=linear, **kw)
    except Exception as e:
        # linearisation and incremental hints fail on some damaged files
        doc.save(str(path), garbage=1, deflate=deflate)
        if not path.exists():
            raise ToolError(f"Could not write {path.name}: {e}") from e
    return path


def search_text(page, term: str, *, case: bool = False, limit: int = 0):
    """Find a phrase on a page.

    MuPDF's own search is always case-insensitive, so exact-case matching is
    done afterwards by re-reading the text inside each hit.
    """
    if not term:
        return []
    try:
        hits = page.search_for(term) or []
    except Exception:
        return []
    if case:
        kept = []
        for rect in hits:
            try:
                found = page.get_textbox(rect) or ""
            except Exception:
                found = ""
            if term in found:
                kept.append(rect)
        hits = kept
    return hits[:limit] if limit else hits


def fade_image(img, opacity: float):
    """Bake an opacity level into an image's alpha channel.

    PyMuPDF cannot set an opacity when placing an image, so the transparency
    has to be part of the pixels.
    """
    opacity = max(0.0, min(1.0, float(opacity)))
    if opacity >= 0.999:
        return img
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda v: int(v * opacity))
    rgba.putalpha(alpha)
    return rgba


def new_doc_from(doc: fitz.Document, idxs) -> fitz.Document:
    out = fitz.open()
    for i in idxs:
        out.insert_pdf(doc, from_page=i, to_page=i)
    return out
