"""Category 8 - scanning, OCR and scan clean-up."""
from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz

from pdfbuilder import deps
from pdfbuilder.core.common import (open_pdf, parse_pages, require_images,
                                    save_pdf)
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Password (if protected)", "str", "")
PAGES = P("pages", "Pages", "pages", "all")

# Tesseract language codes with friendly names; the list is filtered at
# runtime to whatever language packs are actually installed.
LANGS = {
    "eng": "English", "hin": "Hindi", "spa": "Spanish", "fra": "French",
    "deu": "German", "ita": "Italian", "por": "Portuguese", "nld": "Dutch",
    "rus": "Russian", "ara": "Arabic", "chi_sim": "Chinese (simplified)",
    "chi_tra": "Chinese (traditional)", "jpn": "Japanese", "kor": "Korean",
    "ben": "Bengali", "tam": "Tamil", "tel": "Telugu", "mar": "Marathi",
    "guj": "Gujarati", "pan": "Punjabi", "urd": "Urdu", "tha": "Thai",
    "vie": "Vietnamese", "tur": "Turkish", "pol": "Polish", "ukr": "Ukrainian",
    "ind": "Indonesian", "heb": "Hebrew", "ell": "Greek", "swe": "Swedish",
}


def installed_languages() -> list[str]:
    exe = deps.find("tesseract")
    if not exe:
        return []
    try:
        r = deps.run([exe, "--list-langs"], timeout=30)
    except ToolError:
        return []
    out = [l.strip() for l in r.stdout.splitlines()[1:] if l.strip()]
    return out or ["eng"]


def lang_choices() -> tuple:
    got = installed_languages()
    if not got:
        return tuple(f"{c} - {n}" for c, n in list(LANGS.items())[:6])
    pretty = [f"{c} - {LANGS.get(c, c)}" for c in got]
    return tuple(sorted(pretty, key=lambda s: (s.split(" - ")[0] != "eng", s)))


def lang_code(value: str) -> str:
    return str(value or "eng").split(" - ")[0].strip() or "eng"


# --------------------------------------------------------------- engines
#
# Two recognisers are supported. Tesseract is the better all-rounder and
# handles dozens of languages, but needs a system package. RapidOCR ships its
# models inside its Python wheel, so it works with no system install at all -
# which keeps Scan & OCR usable on a machine where apt is not an option.

_RAPID = {"engine": None, "checked": False}


def have_rapidocr() -> bool:
    if not _RAPID["checked"]:
        _RAPID["checked"] = True
        try:
            import rapidocr_onnxruntime  # noqa: F401
            _RAPID["available"] = True
        except Exception:
            _RAPID["available"] = False
    return bool(_RAPID.get("available"))


# The detector's default input limit (736 px) downscales a 300 dpi A4 scan so
# far that long lines of text stop being found at all. 1920 keeps full lines
# detectable without slowing recognition down noticeably.
RAPID_DET_SIDE = 1920
RAPID_MAX_SIDE = 2400


def _rapid():
    """Build the RapidOCR engine once; it is slow to construct."""
    if _RAPID["engine"] is None:
        from rapidocr_onnxruntime import RapidOCR
        _RAPID["engine"] = RapidOCR(det_limit_side_len=RAPID_DET_SIDE)
    return _RAPID["engine"]


def engine_choices() -> tuple:
    opts = ["automatic"]
    if deps.have("tesseract"):
        opts.append("Tesseract")
    if have_rapidocr():
        opts.append("Built-in (no extra software)")
    return tuple(opts)


def any_engine() -> bool:
    return deps.have("tesseract") or have_rapidocr()


def pick_engine(choice: str) -> str:
    """Resolve the engine setting to 'tesseract' or 'rapidocr'."""
    choice = str(choice or "automatic").lower()
    if choice.startswith("tess"):
        if not deps.have("tesseract"):
            deps.require("tesseract")
        return "tesseract"
    if choice.startswith("built"):
        if not have_rapidocr():
            raise ToolError(
                "The built-in recogniser is not installed.\n\n"
                "Add it with:\n"
                "    .venv/bin/pip install rapidocr-onnxruntime")
        return "rapidocr"
    if deps.have("tesseract"):
        return "tesseract"
    if have_rapidocr():
        return "rapidocr"
    raise ToolError(
        "No text recogniser is available.\n\n"
        "Either install Tesseract, which also brings extra languages:\n"
        "    sudo apt install tesseract-ocr\n\n"
        "or the built-in recogniser, which needs no system packages:\n"
        "    .venv/bin/pip install rapidocr-onnxruntime")


class Word:
    """One recognised word or line, in image pixel coordinates."""

    __slots__ = ("text", "x0", "y0", "x1", "y1", "conf")

    def __init__(self, text, x0, y0, x1, y1, conf=0.0):
        self.text = text
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.conf = conf

    @property
    def width(self):
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self):
        return max(0.0, self.y1 - self.y0)


def recognise(img, *, engine="automatic", lang="eng", psm=3) -> list[Word]:
    """Read an image with whichever engine is selected."""
    which = pick_engine(engine)
    if which == "tesseract":
        return _tesseract_words(img, lang, psm)
    return _rapidocr_words(img)


def _tesseract_words(img, lang: str, psm: int) -> list[Word]:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = deps.require("tesseract")
    data = pytesseract.image_to_data(
        img, lang=lang, config=f"--psm {psm}",
        output_type=pytesseract.Output.DICT)
    out = []
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data.get("conf", [0] * n)[i])
        except (TypeError, ValueError):
            conf = 0.0
        if conf < 0:
            continue
        x, y = float(data["left"][i]), float(data["top"][i])
        w, h = float(data["width"][i]), float(data["height"][i])
        if w <= 0 or h <= 0:
            continue
        out.append(Word(text, x, y, x + w, y + h, conf))
    return out


def _rapidocr_words(img) -> list[Word]:
    import numpy as np
    from PIL import Image

    work = img.convert("RGB")
    # Very large scans are downscaled first: the detector works on a bounded
    # input anyway, and the coordinates are mapped back afterwards.
    scale = 1.0
    longest = max(work.size)
    if longest > RAPID_MAX_SIDE:
        scale = RAPID_MAX_SIDE / longest
        work = work.resize((max(1, int(work.width * scale)),
                            max(1, int(work.height * scale))), Image.LANCZOS)
    try:
        result = _rapid()(np.array(work))
    except Exception as e:
        raise ToolError(f"The built-in recogniser failed: {e}") from e
    rows = result[0] if isinstance(result, tuple) else result
    back = 1.0 / scale
    out = []
    for row in rows or []:
        try:
            box, text, score = row[0], row[1], row[2]
        except (TypeError, IndexError):
            continue
        text = str(text).strip()
        if not text:
            continue
        xs = [float(pt[0]) * back for pt in box]
        ys = [float(pt[1]) * back for pt in box]
        out.append(Word(text, min(xs), min(ys), max(xs), max(ys),
                        float(score) * 100))
    return out


OCR_ENGINE = P("engine", "Recogniser", "choice", "automatic",
               choices=engine_choices(),
               help="Tesseract supports many languages; the built-in engine "
                    "needs no system packages")
OCR_LANG = P("lang", "OCR language", "choice", "eng - English",
             choices=lang_choices(),
             help="Tesseract only. Extra languages: "
                  "sudo apt install tesseract-ocr-<code>")
OCR_PSM = P("psm", "Page layout", "choice", "automatic",
            choices=("automatic", "single column", "single block",
                     "single line", "single word", "sparse text"))
PSM_MAP = {"automatic": 3, "single column": 4, "single block": 6,
           "single line": 7, "single word": 8, "sparse text": 11}


# ------------------------------------------------------------ image tweaks

def _to_cv(img):
    import numpy as np
    return np.array(img.convert("L"))


def deskew_image(img, limit: float = 12.0):
    """Straighten a scanned page using the dominant text angle."""
    import cv2
    import numpy as np
    gray = _to_cv(img)
    inv = cv2.bitwise_not(gray)
    thr = cv2.threshold(inv, 0, 255,
                        cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = cv2.findNonZero(thr)
    if coords is None or len(coords) < 50:
        return img, 0.0
    angle = cv2.minAreaRect(coords)[-1]
    if angle > 45:
        angle -= 90
    if angle < -45:
        angle += 90
    # cross-check with Hough lines; they track text baselines better
    edges = cv2.Canny(gray, 60, 180)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 360, 120,
                            minLineLength=max(40, gray.shape[1] // 4),
                            maxLineGap=12)
    if lines is not None and len(lines):
        angs = []
        for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
            a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(a) < limit:
                angs.append(a)
        if len(angs) >= 5:
            angle = float(np.median(angs))
    if abs(angle) < 0.08 or abs(angle) > limit:
        return img, 0.0
    from PIL import Image
    return img.convert("RGB").rotate(angle, resample=Image.BICUBIC,
                                     expand=False, fillcolor=(255, 255, 255)), \
        float(angle)


def enhance_scan(img, *, contrast=1.3, brightness=1.05, sharpen=1.2,
                 whiten=False, denoise=False):
    from PIL import ImageEnhance, ImageFilter, ImageOps
    out = img.convert("RGB")
    if denoise:
        out = out.filter(ImageFilter.MedianFilter(3))
    if whiten:
        out = ImageOps.autocontrast(out, cutoff=(0.5, 2.0))
    if abs(brightness - 1) > 1e-6:
        out = ImageEnhance.Brightness(out).enhance(brightness)
    if abs(contrast - 1) > 1e-6:
        out = ImageEnhance.Contrast(out).enhance(contrast)
    if abs(sharpen - 1) > 1e-6:
        out = ImageEnhance.Sharpness(out).enhance(sharpen)
    return out


def detect_orientation(img) -> int:
    """Return 0/90/180/270: how far the page is rotated, via tesseract OSD."""
    exe = deps.find("tesseract")
    if not exe:
        return 0
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
        img.convert("RGB").save(fh.name)
        try:
            r = deps.run([exe, fh.name, "stdout", "--psm", "0"], timeout=60)
        except ToolError:
            return 0
        finally:
            Path(fh.name).unlink(missing_ok=True)
    for line in r.stdout.splitlines():
        if line.lower().startswith("rotate:"):
            try:
                return int(line.split(":")[1].strip()) % 360
            except ValueError:
                return 0
    return 0


def page_ink(img) -> float:
    """Fraction of non-white pixels - used for blank page detection."""
    import numpy as np
    arr = np.array(img.convert("L").resize((min(img.width, 600),
                                            min(img.height, 800))))
    return float((arr < 235).mean())


# ----------------------------------------------------------------- tools

def _as_text(words) -> str:
    """Join recognised words back into lines, using their positions."""
    if not words:
        return ""
    ordered = sorted(words, key=lambda w: (round(w.y0 / 12), w.x0))
    lines, current, last_y = [], [], None
    for w in ordered:
        if last_y is not None and abs(w.y0 - last_y) > max(8.0, w.height * 0.7):
            lines.append(" ".join(current))
            current = []
        current.append(w.text)
        last_y = w.y0
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


@tool(id="images_to_scan_pdf", name="Create PDF from scanned images",
      category="ocr", inputs="image+", batchable=False,
      summary="Build a tidy document from photos or scans: straighten, "
              "boost contrast, drop blank pages, and optionally OCR.",
      params=[P("outname", "Output file name", "str", "scan.pdf"),
              P("deskew", "Straighten crooked pages", "bool", True),
              P("autorotate", "Correct page orientation", "bool", True),
              P("enhance", "Improve contrast and brightness", "bool", True),
              P("contrast", "Contrast", "float", 1.35, lo=0.5, hi=3,
                step=0.05, when=("enhance", (True,))),
              P("brightness", "Brightness", "float", 1.05, lo=0.5, hi=2,
                step=0.05, when=("enhance", (True,))),
              P("whiten", "Whiten the background", "bool", True,
                when=("enhance", (True,))),
              P("denoise", "Remove speckles", "bool", False,
                when=("enhance", (True,))),
              P("gray", "Greyscale output (much smaller)", "bool", True),
              P("drop_blank", "Skip blank pages", "bool", True),
              P("blank_level", "Blank threshold", "float", 0.4, lo=0.01,
                hi=5, step=0.05, suffix=" % ink",
                when=("drop_blank", (True,))),
              P("ocr", "Add a searchable text layer (OCR)", "bool", False),
              OCR_ENGINE, OCR_LANG,
              P("quality", "JPEG quality", "int", 80, lo=40, hi=98),
              P("dpi", "Assumed scan resolution", "int", 200, lo=72, hi=1200,
                suffix=" dpi")])
def images_to_scan_pdf(ctx):
    from pdfbuilder.core.images import load_image
    imgs = require_images(ctx)
    if ctx.p["ocr"]:
        pick_engine(ctx.p.get("engine", "automatic"))   # fail early, clearly
    doc = fitz.open()
    skipped = []
    for n, path in enumerate(imgs, 1):
        ctx.progress(0.9 * n / len(imgs), Path(path).name)
        img = load_image(path)
        if ctx.p["autorotate"]:
            rot = detect_orientation(img)
            if rot:
                img = img.rotate(-rot, expand=True)
        if ctx.p["deskew"]:
            img, ang = deskew_image(img)
            if ang:
                ctx.log(f"{Path(path).name}: straightened by {ang:.2f}deg")
        # the enhancement is for how the page *looks*; OCR reads the
        # unenhanced image, which recognises more reliably
        for_ocr = img
        if ctx.p["enhance"]:
            img = enhance_scan(img, contrast=float(ctx.p["contrast"]),
                               brightness=float(ctx.p["brightness"]),
                               whiten=bool(ctx.p["whiten"]),
                               denoise=bool(ctx.p["denoise"]))
        if ctx.p["drop_blank"]:
            ink = page_ink(img) * 100
            if ink < float(ctx.p["blank_level"]):
                skipped.append(Path(path).name)
                continue
        if ctx.p["gray"]:
            img = img.convert("L")
        buf = io.BytesIO()
        img.convert("L" if ctx.p["gray"] else "RGB").save(
            buf, "JPEG", quality=int(ctx.p["quality"]), optimize=True)
        dpi = max(36, int(ctx.p["dpi"]))
        pw, ph = img.width * 72 / dpi, img.height * 72 / dpi
        page = doc.new_page(width=pw, height=ph)
        page.insert_image(page.rect, stream=buf.getvalue())
        if ctx.p["ocr"]:
            _ocr_page_text(page, for_ocr, lang_code(ctx.p["lang"]), 3,
                           ctx.p.get("engine", "automatic"))
    if doc.page_count == 0:
        raise ToolError("Every image looked blank. Lower the blank threshold "
                        "or turn off 'Skip blank pages'.")
    name = str(ctx.p["outname"] or "scan.pdf")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    target = save_pdf(doc, ctx.out(name), garbage=3, deflate=True)
    doc.close()
    if skipped:
        ctx.log(f"Skipped {len(skipped)} blank page(s): "
                f"{', '.join(skipped[:6])}{'...' if len(skipped) > 6 else ''}")
    ctx.log(f"Built a {len(imgs) - len(skipped)}-page document.")
    return ctx.done(target)


def _ocr_page_text(page, img, lang: str, psm: int, engine="automatic",
                   words=None) -> int:
    """Lay an invisible, selectable text layer over a page image.

    Returns how many words were placed. Each word is scaled so its invisible
    glyphs line up with the ink underneath, which is what makes search and
    text selection land in the right place.
    """
    if words is None:
        words = recognise(img, engine=engine, lang=lang, psm=psm)
    sx = page.rect.width / max(1, img.width)
    sy = page.rect.height / max(1, img.height)
    placed = 0
    for word in words:
        x, y = word.x0 * sx, word.y0 * sy
        w, h = word.width * sx, word.height * sy
        if w <= 0 or h <= 0:
            continue
        size = max(2.0, h * 0.86)
        try:
            length = fitz.get_text_length(word.text, "helv", size) or 1
            size *= min(1.6, max(0.3, w / length))
            page.insert_text((x, y + h * 0.82), word.text, fontname="helv",
                             fontsize=max(1.5, size), render_mode=3)
            # one entry may be a whole line, so count actual words
            placed += len(word.text.split()) or 1
        except Exception:
            continue
    return placed


@tool(id="ocr_pdf", name="Make a scanned PDF searchable", category="ocr",
      summary="Recognise the text on every page and add an invisible text "
              "layer, so the PDF becomes searchable and selectable.",
      params=[OCR_ENGINE, OCR_LANG, OCR_PSM,
              P("dpi", "Recognition resolution", "int", 300, lo=150, hi=600,
                suffix=" dpi",
                help="300 dpi is the sweet spot for most documents"),
              P("skip_text", "Skip pages that already have text", "bool", True),
              P("preprocess", "Clean up the image before OCR", "bool", True,
                help="Helps Tesseract; the built-in recogniser reads the "
                     "original scan more accurately and ignores this"),
              P("deskew", "Straighten pages first", "bool", False),
              P("also_text", "Also save the recognised text as .txt", "bool",
                False),
              PAGES, PW])
def ocr_pdf(ctx):
    from PIL import Image
    engine = pick_engine(ctx.p.get("engine", "automatic"))
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    lang = lang_code(ctx.p["lang"])
    psm = PSM_MAP[ctx.p["psm"]]
    done, skipped, texts, total_words = 0, 0, [], 0
    ctx.log(f"Recogniser: {'Tesseract' if engine == 'tesseract' else 'built-in'}"
            + (f", language {lang}" if engine == "tesseract" else ""))
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Reading page {i+1} of {doc.page_count}")
        page = doc[i]
        if ctx.p["skip_text"] and len(page.get_text("text").strip()) > 40:
            skipped += 1
            continue
        pix = page.get_pixmap(dpi=int(ctx.p["dpi"]))
        img = Image.frombytes("RGB" if pix.n >= 3 else "L",
                              (pix.width, pix.height), pix.samples)
        if ctx.p["deskew"]:
            img, _ = deskew_image(img)
        if ctx.p["preprocess"] and engine == "tesseract":
            # Binarisation-style clean-up helps Tesseract but measurably
            # hurts the neural recogniser, which prefers the original pixels.
            img = enhance_scan(img, contrast=1.4, brightness=1.02,
                               whiten=True, sharpen=1.3)
        words = recognise(img, engine=engine, lang=lang, psm=psm)
        total_words += _ocr_page_text(page, img, lang, psm, engine, words)
        if ctx.p["also_text"]:
            texts.append(f"----- page {i+1} -----\n" + _as_text(words))
        done += 1
    target = save_pdf(doc, ctx.derive("searchable"), garbage=3, deflate=True)
    doc.close()
    made = [target]
    if texts:
        tp = ctx.derive("ocr", ".txt")
        tp.write_text("\n\n".join(texts), encoding="utf-8")
        made.append(tp)
    ctx.log(f"OCR'd {done} page(s), {total_words} word(s) recognised"
            + (f"; skipped {skipped} that already had text." if skipped else "."))
    if done == 0 and skipped:
        ctx.log("Nothing to do - this PDF already has a text layer.")
    return ctx.done(*made)


@tool(id="ocr_read", name="Recognise text (copy out)", category="ocr",
      inputs="any+", batchable=False,
      summary="Read printed text out of images or PDFs and save it as text "
              "you can copy.",
      params=[OCR_ENGINE, OCR_LANG, OCR_PSM,
              P("dpi", "Resolution for PDFs", "int", 300, lo=150, hi=600,
                suffix=" dpi"),
              P("preprocess", "Clean up before recognising", "bool", True,
                help="Applies to Tesseract only"),
              P("format", "Output", "choice", "plain text",
                choices=("plain text", "text with confidence", "TSV data")),
              P("per_file", "One output file per input", "bool", True), PW])
def ocr_read(ctx):
    from PIL import Image
    engine = pick_engine(ctx.p.get("engine", "automatic"))
    lang = lang_code(ctx.p["lang"])
    psm = PSM_MAP[ctx.p["psm"]]
    from pdfbuilder.core.common import is_image, is_pdf
    from pdfbuilder.core.images import load_image

    def pages_of(path):
        if is_image(path):
            yield 1, load_image(path)
            return
        doc = open_pdf(path, ctx.p["password"])
        for i in range(doc.page_count):
            pix = doc[i].get_pixmap(dpi=int(ctx.p["dpi"]))
            yield i + 1, Image.frombytes("RGB" if pix.n >= 3 else "L",
                                         (pix.width, pix.height), pix.samples)
        doc.close()

    targets = [p for p in ctx.inputs if is_image(p) or is_pdf(p)]
    if not targets:
        raise ToolError("Select images or PDFs to read.")
    made, combined = [], []
    for f_i, path in enumerate(targets, 1):
        chunks = []
        for pno, img in pages_of(path):
            ctx.progress(f_i / len(targets), f"{path.name} page {pno}")
            if ctx.p["preprocess"] and engine == "tesseract":
                img = enhance_scan(img, contrast=1.4, whiten=True,
                                   sharpen=1.3)
            words = recognise(img, engine=engine, lang=lang, psm=psm)
            if ctx.p["format"] == "TSV data":
                body = ("text\tleft\ttop\twidth\theight\tconf\n" +
                        "\n".join(f"{w.text}\t{w.x0:.0f}\t{w.y0:.0f}\t"
                                  f"{w.width:.0f}\t{w.height:.0f}\t"
                                  f"{w.conf:.0f}" for w in words))
            elif ctx.p["format"] == "text with confidence":
                body = "\n".join(f"{w.text}\t{w.conf:.0f}%" for w in words)
            else:
                body = _as_text(words)
            chunks.append(f"----- {path.name} page {pno} -----\n{body}")
        ext = ".tsv" if ctx.p["format"] == "TSV data" else ".txt"
        if ctx.p["per_file"]:
            out = ctx.derive("ocr", ext, src=path)
            out.write_text("\n\n".join(chunks), encoding="utf-8")
            made.append(out)
        else:
            combined.extend(chunks)
    if combined:
        out = ctx.out("recognised-text.txt")
        out.write_text("\n\n".join(combined), encoding="utf-8")
        made.append(out)
    words = sum(1 for m in made for _ in m.read_text(errors="ignore").split())
    ctx.log(f"Recognised about {words:,} words. Open the file to copy the text.")
    return ctx.done(*made)


@tool(id="fix_orientation", name="Correct page orientation", category="ocr",
      summary="Detect upside-down or sideways pages and turn them the right "
              "way up.",
      params=[P("method", "Detection", "choice", "text direction (OCR)",
                choices=("text direction (OCR)", "page shape only")),
              P("dpi", "Analysis resolution", "int", 150, lo=72, hi=400,
                suffix=" dpi"),
              PAGES, PW])
def fix_orientation(ctx):
    from PIL import Image
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    if ctx.p["method"].startswith("text"):
        deps.require("tesseract")
    changed = 0
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        page = doc[i]
        if ctx.p["method"] == "page shape only":
            rot = _text_direction_rotation(page)
            if rot:
                page.set_rotation((page.rotation + rot) % 360)
                changed += 1
                ctx.log(f"Page {i+1}: rotated {rot}deg (from text direction)")
            continue
        pix = page.get_pixmap(dpi=int(ctx.p["dpi"]))
        img = Image.frombytes("RGB" if pix.n >= 3 else "L",
                              (pix.width, pix.height), pix.samples)
        rot = detect_orientation(img)
        if rot:
            page.set_rotation((page.rotation + rot) % 360)
            changed += 1
            ctx.log(f"Page {i+1}: rotated {rot}deg")
    target = save_pdf(doc, ctx.derive("upright"))
    doc.close()
    ctx.log(f"Adjusted {changed} page(s)." if changed
            else "Every page already looked upright.")
    return ctx.done(target)


def _text_direction_rotation(page) -> int:
    """Infer rotation from the writing direction of the existing text layer."""
    from collections import Counter
    votes = Counter()
    try:
        data = page.get_text("dict")
    except Exception:
        return 0
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1, 0))
            if abs(dx) > abs(dy):
                votes[0 if dx > 0 else 180] += 1
            else:
                votes[270 if dy > 0 else 90] += 1
    if not votes:
        return 0
    best, count = votes.most_common(1)[0]
    return best if count >= 3 and best != 0 else 0


@tool(id="deskew_pdf", name="Deskew scanned pages", category="ocr",
      summary="Straighten pages that were fed in crooked. Pages are "
              "re-rendered, so use this on scans, not on text documents.",
      params=[P("dpi", "Output resolution", "int", 200, lo=100, hi=600,
                suffix=" dpi"),
              P("limit", "Maximum correction", "float", 12, lo=1, hi=45,
                suffix=" deg"),
              P("enhance", "Clean up contrast too", "bool", False),
              P("gray", "Greyscale output", "bool", False),
              P("quality", "JPEG quality", "int", 85, lo=40, hi=98),
              PAGES, PW])
def deskew_pdf(ctx):
    from PIL import Image
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = set(parse_pages(ctx.p["pages"], doc.page_count))
    out = fitz.open()
    fixed = 0
    for i in range(doc.page_count):
        ctx.progress((i + 1) / doc.page_count, f"Page {i+1}")
        src = doc[i]
        if i not in idxs:
            out.insert_pdf(doc, from_page=i, to_page=i)
            continue
        pix = src.get_pixmap(dpi=int(ctx.p["dpi"]))
        img = Image.frombytes("RGB" if pix.n >= 3 else "L",
                              (pix.width, pix.height), pix.samples)
        img, ang = deskew_image(img, limit=float(ctx.p["limit"]))
        if ang:
            fixed += 1
            ctx.log(f"Page {i+1}: {ang:+.2f}deg")
        if ctx.p["enhance"]:
            img = enhance_scan(img, contrast=1.35, whiten=True)
        if ctx.p["gray"]:
            img = img.convert("L")
        buf = io.BytesIO()
        img.convert("L" if ctx.p["gray"] else "RGB").save(
            buf, "JPEG", quality=int(ctx.p["quality"]), optimize=True)
        page = out.new_page(width=src.rect.width, height=src.rect.height)
        page.insert_image(page.rect, stream=buf.getvalue())
    target = save_pdf(out, ctx.derive("deskewed"), garbage=3)
    out.close(); doc.close()
    ctx.log(f"Straightened {fixed} page(s).")
    return ctx.done(target)


@tool(id="remove_blank", name="Detect and remove blank pages", category="ocr",
      summary="Find near-empty pages and drop them. Run the detection first "
              "to see what would go.",
      params=[P("threshold", "Blank if ink below", "float", 0.35, lo=0.01,
                hi=10, step=0.05, suffix=" %"),
              P("ignore_text", "Treat pages with any text as not blank",
                "bool", True),
              P("dpi", "Analysis resolution", "int", 72, lo=36, hi=300,
                suffix=" dpi"),
              P("action", "Then", "choice", "remove them",
                choices=("remove them", "just report", "export them "
                         "separately")),
              P("margin", "Ignore a border of", "float", 4, lo=0, hi=40,
                suffix=" %", help="Hides scanner edge shadows"),
              PW])
def remove_blank(ctx):
    from PIL import Image
    doc = open_pdf(ctx.src, ctx.p["password"])
    blanks, inks = [], {}
    for i in range(doc.page_count):
        ctx.progress((i + 1) / doc.page_count, f"Page {i+1}")
        page = doc[i]
        if ctx.p["ignore_text"] and page.get_text("text").strip():
            inks[i] = 100.0
            continue
        pix = page.get_pixmap(dpi=int(ctx.p["dpi"]))
        img = Image.frombytes("RGB" if pix.n >= 3 else "L",
                              (pix.width, pix.height), pix.samples)
        m = float(ctx.p["margin"]) / 100
        if m > 0:
            w, h = img.size
            img = img.crop((int(w * m), int(h * m), int(w * (1 - m)),
                            int(h * (1 - m))))
        ink = page_ink(img) * 100
        inks[i] = ink
        if ink < float(ctx.p["threshold"]):
            blanks.append(i)
    from pdfbuilder.core.common import fmt_pages, new_doc_from
    if not blanks:
        ctx.log("No blank pages found.")
        doc.close()
        return []
    ctx.log(f"Blank page(s): {fmt_pages(blanks)}")
    ctx.summary = {f"Page {i+1}": f"{inks[i]:.2f}% ink" for i in blanks}
    made = []
    if ctx.p["action"] == "just report":
        doc.close()
        return []
    if ctx.p["action"] == "export them separately":
        part = new_doc_from(doc, blanks)
        made.append(save_pdf(part, ctx.derive("blank-pages")))
        part.close()
    keep = [i for i in range(doc.page_count) if i not in set(blanks)]
    if not keep:
        doc.close()
        raise ToolError("Every page looks blank - nothing would be left.")
    cleaned = new_doc_from(doc, keep)
    made.insert(0, save_pdf(cleaned, ctx.derive("no-blanks")))
    cleaned.close(); doc.close()
    ctx.log(f"Removed {len(blanks)} page(s); {len(keep)} remain.")
    return ctx.done(*made)


@tool(id="enhance_pdf", name="Improve scan contrast and brightness",
      category="ocr",
      summary="Make faint photocopies readable: whiten the paper, darken "
              "the ink.",
      params=[P("preset", "Preset", "choice", "document clean-up",
                choices=("document clean-up", "faint pencil", "photo",
                         "custom")),
              P("contrast", "Contrast", "float", 1.4, lo=0.5, hi=3, step=0.05,
                when=("preset", ("custom",))),
              P("brightness", "Brightness", "float", 1.05, lo=0.5, hi=2,
                step=0.05, when=("preset", ("custom",))),
              P("sharpen", "Sharpness", "float", 1.3, lo=0, hi=4, step=0.1,
                when=("preset", ("custom",))),
              P("whiten", "Whiten background", "bool", True,
                when=("preset", ("custom",))),
              P("denoise", "Remove speckles", "bool", False),
              P("gray", "Greyscale output", "bool", True),
              P("dpi", "Output resolution", "int", 200, lo=100, hi=600,
                suffix=" dpi"),
              P("quality", "JPEG quality", "int", 85, lo=40, hi=98),
              PAGES, PW])
def enhance_pdf(ctx):
    from PIL import Image
    presets = {
        "document clean-up": dict(contrast=1.45, brightness=1.05, sharpen=1.3,
                                  whiten=True),
        "faint pencil": dict(contrast=2.0, brightness=0.95, sharpen=1.6,
                             whiten=True),
        "photo": dict(contrast=1.15, brightness=1.05, sharpen=1.1,
                      whiten=False),
    }
    cfg = presets.get(ctx.p["preset"], dict(
        contrast=float(ctx.p["contrast"]), brightness=float(ctx.p["brightness"]),
        sharpen=float(ctx.p["sharpen"]), whiten=bool(ctx.p["whiten"])))
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = set(parse_pages(ctx.p["pages"], doc.page_count))
    out = fitz.open()
    for i in range(doc.page_count):
        ctx.progress((i + 1) / doc.page_count, f"Page {i+1}")
        src = doc[i]
        if i not in idxs:
            out.insert_pdf(doc, from_page=i, to_page=i)
            continue
        pix = src.get_pixmap(dpi=int(ctx.p["dpi"]))
        img = Image.frombytes("RGB" if pix.n >= 3 else "L",
                              (pix.width, pix.height), pix.samples)
        img = enhance_scan(img, denoise=bool(ctx.p["denoise"]), **cfg)
        if ctx.p["gray"]:
            img = img.convert("L")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=int(ctx.p["quality"]), optimize=True)
        page = out.new_page(width=src.rect.width, height=src.rect.height)
        page.insert_image(page.rect, stream=buf.getvalue())
    target = save_pdf(out, ctx.derive("enhanced"), garbage=3)
    out.close(); doc.close()
    return ctx.done(target)


@tool(id="camera_scan", name="Scan with a camera", category="ocr",
      inputs="none", view="scanner",
      summary="Capture pages with a connected webcam or phone camera, "
              "straighten them and build a PDF.")
def camera_scan(ctx):
    raise ToolError("This tool runs in its own capture panel.")
