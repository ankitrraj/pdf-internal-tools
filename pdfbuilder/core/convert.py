"""Category 6 - conversions to and from PDF."""
from __future__ import annotations

import html as _html
import shutil
import zipfile
from pathlib import Path

import pymupdf as fitz

from pdfbuilder.core.common import (IMAGE_EXT, MM, PAGE_SIZES, human_size,
                                    is_image, is_pdf, open_pdf, parse_pages,
                                    require_images, save_pdf)
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Password (if protected)", "str", "")
PAGES = P("pages", "Pages", "pages", "all")


# ------------------------------------------------------------ images -> PDF

@tool(id="images_to_pdf", name="Images to PDF", category="convert",
      inputs="image+", batchable=False,
      summary="JPG, PNG, WebP, TIFF, BMP, GIF and HEIC - one PDF with a page "
              "per image, or a separate PDF each.",
      params=[P("mode", "Output", "choice", "one PDF with every image",
                choices=("one PDF with every image", "one PDF per image")),
              P("outname", "Output file name", "str", "images.pdf",
                when=("mode", ("one PDF with every image",))),
              P("size", "Page size", "choice", "fit the image",
                choices=("fit the image",) + tuple(PAGE_SIZES)),
              P("orient", "Orientation", "choice", "auto",
                choices=("auto", "portrait", "landscape"),
                when=("size", tuple(PAGE_SIZES))),
              P("margin", "Margin", "float", 0, lo=0, hi=100, suffix=" mm"),
              P("fit", "Scaling", "choice", "fit inside the page",
                choices=("fit inside the page", "fill the page (crop)",
                         "stretch")),
              P("dpi", "Assumed image resolution", "int", 96, lo=36, hi=1200,
                suffix=" dpi", when=("size", ("fit the image",))),
              P("quality", "Re-encode quality", "int", 88, lo=30, hi=100,
                help="Lower values make a smaller PDF"),
              P("gray", "Convert to greyscale", "bool", False),
              P("sort", "Order", "choice", "as listed",
                choices=("as listed", "file name", "date modified"))])
def images_to_pdf(ctx):
    import io

    from pdfbuilder.core.images import load_image
    imgs = require_images(ctx)
    if ctx.p["sort"] == "file name":
        imgs = sorted(imgs, key=lambda p: Path(p).name.lower())
    elif ctx.p["sort"] == "date modified":
        imgs = sorted(imgs, key=lambda p: Path(p).stat().st_mtime)

    margin = float(ctx.p["margin"]) * MM
    one_file = ctx.p["mode"] == "one PDF with every image"
    doc = fitz.open() if one_file else None
    made = []

    for n, path in enumerate(imgs, 1):
        ctx.progress(n / len(imgs), Path(path).name)
        img = load_image(path)
        if ctx.p["gray"]:
            img = img.convert("L")
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=int(ctx.p["quality"]), optimize=True)
        data = buf.getvalue()

        if ctx.p["size"] == "fit the image":
            dpi = max(1, int(ctx.p["dpi"]))
            pw = img.width * 72 / dpi + 2 * margin
            ph = img.height * 72 / dpi + 2 * margin
        else:
            w, h = PAGE_SIZES[ctx.p["size"]]
            want = ctx.p["orient"]
            land = (img.width > img.height) if want == "auto" else want == "landscape"
            pw, ph = (max(w, h), min(w, h)) if land else (min(w, h), max(w, h))

        target_doc = doc if one_file else fitz.open()
        page = target_doc.new_page(width=pw, height=ph)
        box = fitz.Rect(margin, margin, pw - margin, ph - margin)
        if ctx.p["fit"] == "stretch":
            place, keep = box, False
        elif ctx.p["fit"].startswith("fill"):
            s = max(box.width / img.width, box.height / img.height)
            cw, ch = img.width * s, img.height * s
            place = fitz.Rect(box.x0 - (cw - box.width) / 2,
                              box.y0 - (ch - box.height) / 2,
                              box.x1 + (cw - box.width) / 2,
                              box.y1 + (ch - box.height) / 2)
            keep = True
            page.set_cropbox(fitz.Rect(0, 0, pw, ph))
        else:
            place, keep = box, True
        page.insert_image(place, stream=data, keep_proportion=keep)
        if not one_file:
            made.append(save_pdf(target_doc, ctx.derive("pdf", ".pdf",
                                                        src=Path(path))))
            target_doc.close()

    if one_file:
        name = str(ctx.p["outname"] or "images.pdf")
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        made.append(save_pdf(doc, ctx.out(name)))
        doc.close()
    ctx.log(f"Converted {len(imgs)} image(s).")
    return ctx.done(*made)


# ------------------------------------------------------------ PDF -> images

RASTER_FORMATS = ("PNG", "JPEG", "WEBP", "TIFF", "BMP")


@tool(id="pdf_to_images", name="PDF to images", category="convert",
      summary="Render pages as PNG, JPG, WebP, TIFF or BMP files.",
      params=[P("format", "Image format", "choice", "PNG",
                choices=RASTER_FORMATS),
              P("dpi", "Resolution", "int", 200, lo=36, hi=900, suffix=" dpi"),
              P("quality", "Quality (JPEG/WebP)", "int", 92, lo=30, hi=100),
              P("gray", "Greyscale", "bool", False),
              P("transparent", "Transparent background (PNG)", "bool", False),
              P("annots", "Include annotations", "bool", True),
              P("zip", "Bundle the results as a ZIP", "bool", False),
              PAGES, PW])
def pdf_to_images(ctx):
    from pdfbuilder.core.images import EXT_OF, save_image
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    fmt = ctx.p["format"]
    made = []
    cs = fitz.csGRAY if ctx.p["gray"] else fitz.csRGB
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        pix = doc[i].get_pixmap(dpi=int(ctx.p["dpi"]), colorspace=cs,
                                alpha=bool(ctx.p["transparent"]) and fmt == "PNG",
                                annots=bool(ctx.p["annots"]))
        out = ctx.derive(f"page{i+1:04d}", EXT_OF[fmt])
        if fmt == "PNG":
            pix.save(str(out))
        else:
            from PIL import Image
            mode = "RGBA" if pix.alpha else ("L" if pix.n == 1 else "RGB")
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            save_image(img, out, quality=int(ctx.p["quality"]), fmt=fmt)
        made.append(out)
    doc.close()
    if ctx.p["zip"]:
        made.append(ctx.zip_up(made, ctx.src.stem + "-images"))
    return ctx.done(*made)


@tool(id="extract_images", name="Extract embedded images", category="convert",
      summary="Pull out the original pictures stored inside the PDF, without "
              "re-rendering them.",
      params=[P("min_size", "Ignore images smaller than", "int", 64, lo=0,
                hi=5000, suffix=" px"),
              P("format", "Save as", "choice", "original format",
                choices=("original format",) + RASTER_FORMATS),
              P("dedupe", "Skip repeated images", "bool", True),
              P("zip", "Bundle the results as a ZIP", "bool", False),
              PAGES, PW])
def extract_images(ctx):
    import hashlib
    import io

    from PIL import Image

    from pdfbuilder.core.images import EXT_OF, save_image
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    made, seen, count = [], set(), 0
    minimum = int(ctx.p["min_size"])
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        for info in doc.get_page_images(i, full=True):
            xref = info[0]
            try:
                raw = doc.extract_image(xref)
            except Exception:
                continue
            if not raw or not raw.get("image"):
                continue
            if ctx.p["dedupe"]:
                h = hashlib.sha1(raw["image"]).hexdigest()
                if h in seen:
                    continue
                seen.add(h)
            if max(raw.get("width", 0), raw.get("height", 0)) < minimum:
                continue
            count += 1
            if ctx.p["format"] == "original format":
                ext = "." + (raw.get("ext") or "png")
                out = ctx.derive(f"img{count:03d}-p{i+1}", ext)
                out.write_bytes(raw["image"])
            else:
                fmt = ctx.p["format"]
                out = ctx.derive(f"img{count:03d}-p{i+1}", EXT_OF[fmt])
                img = Image.open(io.BytesIO(raw["image"]))
                save_image(img, out, fmt=fmt)
            made.append(out)
    doc.close()
    if not made:
        ctx.log("No embedded images found (the pages may be vector or text only).")
    else:
        ctx.log(f"Extracted {len(made)} image(s).")
    if ctx.p["zip"] and made:
        made.append(ctx.zip_up(made, ctx.src.stem + "-embedded-images"))
    return ctx.done(*made)


# ------------------------------------------------------------------- text

@tool(id="pdf_to_text", name="PDF to plain text", category="convert",
      summary="Extract the text layer, keeping reading order.",
      params=[P("layout", "Style", "choice", "reading order",
                choices=("reading order", "preserve layout", "one line per "
                         "block", "JSON (with positions)")),
              P("page_breaks", "Mark page breaks", "bool", True),
              P("per_page", "One text file per page", "bool", False),
              PAGES, PW])
def pdf_to_text(ctx):
    import json
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    style = ctx.p["layout"]
    chunks, made = [], []
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        page = doc[i]
        if style == "JSON (with positions)":
            txt = json.dumps(page.get_text("dict"), indent=1, default=str)
        elif style == "preserve layout":
            txt = page.get_text("text", flags=fitz.TEXTFLAGS_TEXT
                                | fitz.TEXT_PRESERVE_WHITESPACE)
        elif style.startswith("one line"):
            txt = "\n".join(b[4].replace("\n", " ").strip()
                            for b in page.get_text("blocks") if b[4].strip())
        else:
            txt = page.get_text("text", sort=True)
        if ctx.p["per_page"]:
            out = ctx.derive(f"page{i+1:04d}", ".txt")
            out.write_text(txt, encoding="utf-8")
            made.append(out)
        else:
            if ctx.p["page_breaks"] and len(idxs) > 1:
                chunks.append(f"\n\n----- page {i+1} -----\n\n")
            chunks.append(txt)
    doc.close()
    if not ctx.p["per_page"]:
        ext = ".json" if style.startswith("JSON") else ".txt"
        out = ctx.derive("text", ext)
        out.write_text("".join(chunks), encoding="utf-8")
        made.append(out)
        words = len("".join(chunks).split())
        ctx.log(f"Extracted about {words:,} words.")
        if words == 0:
            ctx.log("This PDF has no text layer - run Scan & OCR first.")
    return ctx.done(*made)


def _story_to_pdf(html: str, out_path: Path, *, size="A4", margin_mm=18.0,
                  css: str = "", base: Path | None = None) -> Path:
    """Render HTML/CSS to a paginated PDF with PyMuPDF's Story engine."""
    w, h = PAGE_SIZES.get(size, PAGE_SIZES["A4"])
    m = margin_mm * MM
    area = fitz.Rect(0, 0, w, h) + (m, m, -m, -m)
    arch = fitz.Archive(str(base)) if base and Path(base).is_dir() else None
    try:
        story = fitz.Story(html=html, user_css=css or None, archive=arch)
    except Exception as e:
        raise ToolError(f"Could not lay out that document: {e}") from e
    writer = fitz.DocumentWriter(str(out_path))
    more, guard = True, 0
    while more and guard < 5000:
        dev = writer.begin_page(fitz.Rect(0, 0, w, h))
        more, _ = story.place(area)
        story.draw(dev)
        writer.end_page()
        guard += 1
    writer.close()
    return out_path


DEFAULT_CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.45; color: #111; }
h1 { font-size: 20pt; margin: 0 0 10pt; }
h2 { font-size: 15pt; margin: 14pt 0 6pt; }
h3 { font-size: 12.5pt; margin: 12pt 0 4pt; }
p { margin: 0 0 8pt; }
code, pre { font-family: monospace; font-size: 9.5pt; background: #f4f4f5; }
pre { padding: 6pt; }
table { border-collapse: collapse; }
td, th { border: 1px solid #bbb; padding: 3pt 5pt; font-size: 10pt; }
blockquote { margin: 0 0 8pt 12pt; color: #444; }
"""


@tool(id="text_to_pdf", name="Text file to PDF", category="convert",
      inputs="any+", batchable=False,
      summary="Turn .txt, .log, .csv or source files into a paginated PDF.",
      params=[P("size", "Page size", "choice", "A4", choices=tuple(PAGE_SIZES)),
              P("margin", "Margin", "float", 18, lo=0, hi=60, suffix=" mm"),
              P("font", "Style", "choice", "monospace",
                choices=("monospace", "sans-serif", "serif")),
              P("fontsize", "Text size", "float", 10, lo=5, hi=36,
                suffix=" pt"),
              P("wrap", "Wrap long lines", "bool", True),
              P("title", "Print the file name as a heading", "bool", True),
              P("one_pdf", "Combine all files into one PDF", "bool", False)])
def text_to_pdf(ctx):
    srcs = [p for p in ctx.inputs if p.suffix.lower() not in IMAGE_EXT
            and p.suffix.lower() != ".pdf"]
    if not srcs:
        raise ToolError("Select one or more text files.")
    made = []
    parts = []
    for n, path in enumerate(srcs, 1):
        ctx.progress(n / len(srcs), path.name)
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            raise ToolError(f"Could not read {path.name}: {e}")
        body = _html.escape(raw)
        css = (DEFAULT_CSS + f"\npre,body{{font-family:{ctx.p['font']};"
               f"font-size:{float(ctx.p['fontsize'])}pt;}}"
               + ("\npre{white-space:pre-wrap;}" if ctx.p["wrap"]
                  else "\npre{white-space:pre;}"))
        head = f"<h1>{_html.escape(path.name)}</h1>" if ctx.p["title"] else ""
        chunk = f"{head}<pre>{body}</pre>"
        if ctx.p["one_pdf"]:
            parts.append(chunk)
            continue
        out = ctx.derive("text", ".pdf", src=path)
        _story_to_pdf(f"<body>{chunk}</body>", out, size=ctx.p["size"],
                      margin_mm=float(ctx.p["margin"]), css=css)
        made.append(out)
    if ctx.p["one_pdf"] and parts:
        css = DEFAULT_CSS + f"\npre,body{{font-family:{ctx.p['font']};}}"
        out = ctx.out("text-documents.pdf")
        _story_to_pdf("<body>" + "<hr/>".join(parts) + "</body>", out,
                      size=ctx.p["size"], margin_mm=float(ctx.p["margin"]),
                      css=css)
        made.append(out)
    return ctx.done(*made)


@tool(id="html_to_pdf", name="HTML file to PDF", category="convert",
      inputs="any+", batchable=False,
      summary="Render a local .html file, including its own CSS and images.",
      params=[P("size", "Page size", "choice", "A4", choices=tuple(PAGE_SIZES)),
              P("margin", "Margin", "float", 15, lo=0, hi=60, suffix=" mm"),
              P("extra_css", "Extra CSS", "text", ""),
              P("use_default_css", "Apply readable default styling", "bool",
                True)])
def html_to_pdf(ctx):
    srcs = [p for p in ctx.inputs if p.suffix.lower() in (".html", ".htm",
                                                          ".xhtml")]
    if not srcs:
        raise ToolError("Select one or more .html files.")
    made = []
    for n, path in enumerate(srcs, 1):
        ctx.progress(n / len(srcs), path.name)
        html = path.read_text(encoding="utf-8", errors="replace")
        css = (DEFAULT_CSS if ctx.p["use_default_css"] else "") + \
            "\n" + str(ctx.p["extra_css"] or "")
        out = ctx.derive("html", ".pdf", src=path)
        _story_to_pdf(html, out, size=ctx.p["size"],
                      margin_mm=float(ctx.p["margin"]), css=css,
                      base=path.parent)
        made.append(out)
    ctx.log("Rendered with the built-in layout engine (no browser needed).")
    return ctx.done(*made)


@tool(id="md_to_pdf", name="Markdown to PDF", category="convert",
      inputs="any+", batchable=False,
      summary="Convert .md files, with tables, code blocks and headings.",
      params=[P("size", "Page size", "choice", "A4", choices=tuple(PAGE_SIZES)),
              P("margin", "Margin", "float", 20, lo=0, hi=60, suffix=" mm"),
              P("extra_css", "Extra CSS", "text", ""),
              P("one_pdf", "Combine all files into one PDF", "bool", False)])
def md_to_pdf(ctx):
    try:
        import markdown
    except ImportError:
        raise ToolError("The 'markdown' package is missing. Reinstall with "
                        "./install.sh")
    srcs = [p for p in ctx.inputs if p.suffix.lower() in (".md", ".markdown",
                                                          ".mdown", ".txt")]
    if not srcs:
        raise ToolError("Select one or more .md files.")
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc",
                                       "sane_lists"])
    css = DEFAULT_CSS + "\n" + str(ctx.p["extra_css"] or "")
    made, parts = [], []
    for n, path in enumerate(srcs, 1):
        ctx.progress(n / len(srcs), path.name)
        md.reset()
        body = md.convert(path.read_text(encoding="utf-8", errors="replace"))
        if ctx.p["one_pdf"]:
            parts.append(body)
            continue
        out = ctx.derive("md", ".pdf", src=path)
        _story_to_pdf(f"<body>{body}</body>", out, size=ctx.p["size"],
                      margin_mm=float(ctx.p["margin"]), css=css,
                      base=path.parent)
        made.append(out)
    if parts:
        out = ctx.out("markdown.pdf")
        _story_to_pdf("<body>" + "<hr/>".join(parts) + "</body>", out,
                      size=ctx.p["size"], margin_mm=float(ctx.p["margin"]),
                      css=css)
        made.append(out)
    return ctx.done(*made)


@tool(id="pdf_to_html", name="PDF to HTML", category="convert",
      summary="Export as HTML, either with absolute positioning (looks the "
              "same) or as reflowable text.",
      params=[P("style", "Style", "choice", "keep the visual layout",
                choices=("keep the visual layout", "simple reflowable text")),
              P("images", "Include images", "bool", True),
              P("single", "One HTML file for the whole document", "bool", True),
              PAGES, PW])
def pdf_to_html(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    made, parts = [], []
    exact = ctx.p["style"].startswith("keep")
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        page = doc[i]
        if exact:
            frag = page.get_text("html")
        else:
            blocks = [b[4].strip() for b in page.get_text("blocks")
                      if b[4].strip()]
            frag = "".join(f"<p>{_html.escape(b)}</p>"
                           for b in blocks)
        if not ctx.p["images"]:
            import re as _re
            frag = _re.sub(r"<img[^>]*>", "", frag)
        if ctx.p["single"]:
            parts.append(f'<section id="page-{i+1}">{frag}</section>')
        else:
            out = ctx.derive(f"page{i+1:04d}", ".html")
            out.write_text(_wrap_html(ctx.src.stem, frag), encoding="utf-8")
            made.append(out)
    doc.close()
    if ctx.p["single"]:
        out = ctx.derive("html", ".html")
        out.write_text(_wrap_html(ctx.src.stem, "\n".join(parts)),
                       encoding="utf-8")
        made.append(out)
    return ctx.done(*made)


def _wrap_html(title: str, body: str) -> str:
    return ("<!doctype html>\n<html><head><meta charset='utf-8'>"
            f"<title>{_html.escape(title)}</title>"
            "<style>body{margin:0 auto;max-width:900px;padding:24px;"
            "font-family:sans-serif;line-height:1.5}"
            "section{position:relative;margin-bottom:32px;"
            "border-bottom:1px solid #ddd;padding-bottom:24px}"
            "img{max-width:100%}</style></head><body>\n"
            + body + "\n</body></html>\n")


@tool(id="pdf_to_svg", name="PDF to SVG", category="convert",
      summary="Vector export - one SVG per page, text and shapes stay sharp.",
      params=[P("text_as_paths", "Convert text to outlines", "bool", False,
                help="On: looks identical anywhere. Off: text stays selectable"),
              P("zip", "Bundle the results as a ZIP", "bool", False),
              PAGES, PW])
def pdf_to_svg(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    made = []
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        svg = doc[i].get_svg_image(text_as_path=bool(ctx.p["text_as_paths"]))
        out = ctx.derive(f"page{i+1:04d}", ".svg")
        out.write_text(svg, encoding="utf-8")
        made.append(out)
    doc.close()
    if ctx.p["zip"]:
        made.append(ctx.zip_up(made, ctx.src.stem + "-svg"))
    return ctx.done(*made)


@tool(id="pdf_to_pdfa", name="PDF to PDF/A (archival)", category="convert",
      summary="Produce a self-contained archival PDF/A file.",
      params=[P("level", "Conformance", "choice", "PDF/A-2b",
                choices=("PDF/A-1b", "PDF/A-2b", "PDF/A-3b")),
              P("fallback", "Fall back to a cleaned PDF", "bool", True,
                help="Used when Ghostscript is not installed or refuses the "
                     "file: fonts are embedded and the file is made "
                     "self-contained"), PW])
def pdf_to_pdfa(ctx):
    from pdfbuilder import deps
    target = ctx.derive("pdfa")
    level = {"PDF/A-1b": "1", "PDF/A-2b": "2", "PDF/A-3b": "3"}[ctx.p["level"]]
    if deps.have("ghostscript"):
        gs = deps.find("ghostscript")
        defs = ctx.tmp / "pdfa.ps"
        defs.write_text(
            "[ /Title (converted) /DOCINFO pdfmark\n"
            "[/_objdef {icc_PDFA} /type /stream /OBJ pdfmark\n", encoding="utf-8")
        cmd = [gs, "-dPDFA=" + level, "-dBATCH", "-dNOPAUSE", "-dQUIET",
               "-sColorConversionStrategy=UseDeviceIndependentColor",
               "-sDEVICE=pdfwrite", "-dPDFACompatibilityPolicy=1",
               f"-sOutputFile={target}", str(ctx.src)]
        ctx.progress(0.4, "Converting with Ghostscript")
        try:
            deps.run(cmd, timeout=900)
            ctx.log(f"Wrote {ctx.p['level']} using Ghostscript.")
            return ctx.done(target)
        except ToolError as e:
            if not ctx.p["fallback"]:
                raise
            ctx.log(f"Ghostscript could not produce PDF/A ({e}); using the "
                    f"fallback path.")
    elif not ctx.p["fallback"]:
        deps.require("ghostscript")

    doc = open_pdf(ctx.src, ctx.p["password"])
    doc.set_metadata({**(doc.metadata or {}), "producer": "PDF Builder",
                      "creator": "PDF Builder"})
    save_pdf(doc, target, garbage=4, clean=True, deflate=True)
    doc.close()
    ctx.log("Saved a cleaned, self-contained PDF. Install ghostscript for "
            "full PDF/A validation.")
    return ctx.done(target)


@tool(id="pdf_to_zip", name="PDF to ZIP", category="convert", inputs="pdf+",
      batchable=False,
      summary="Package the PDFs - or their pages, text and images - into a "
              "single ZIP archive.",
      params=[P("contents", "Put in the archive", "choice", "the PDF files",
                choices=("the PDF files", "one PDF per page",
                         "page images (PNG)", "extracted text")),
              P("dpi", "Image resolution", "int", 150, lo=36, hi=600,
                suffix=" dpi", when=("contents", ("page images (PNG)",))),
              P("outname", "Archive name", "str", "pdf-archive.zip"), PW])
def pdf_to_zip(ctx):
    pdfs = [p for p in ctx.inputs if is_pdf(p)]
    if not pdfs:
        raise ToolError("Select at least one PDF.")
    name = str(ctx.p["outname"] or "pdf-archive.zip")
    if not name.lower().endswith(".zip"):
        name += ".zip"
    target = ctx.out(name)
    kind = ctx.p["contents"]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for n, path in enumerate(pdfs, 1):
            ctx.progress(n / len(pdfs), path.name)
            if kind == "the PDF files":
                z.write(path, path.name)
                continue
            doc = open_pdf(path, ctx.p["password"])
            stem = path.stem
            for i in range(doc.page_count):
                if kind == "one PDF per page":
                    part = fitz.open()
                    part.insert_pdf(doc, from_page=i, to_page=i)
                    tmp = ctx.tmp / f"{stem}-{i+1:04d}.pdf"
                    part.save(str(tmp))
                    part.close()
                    z.write(tmp, f"{stem}/page{i+1:04d}.pdf")
                elif kind == "page images (PNG)":
                    pix = doc[i].get_pixmap(dpi=int(ctx.p["dpi"]))
                    tmp = ctx.tmp / f"{stem}-{i+1:04d}.png"
                    pix.save(str(tmp))
                    z.write(tmp, f"{stem}/page{i+1:04d}.png")
                else:
                    z.writestr(f"{stem}/page{i+1:04d}.txt",
                               doc[i].get_text("text", sort=True))
            doc.close()
    ctx.log(f"Archive: {human_size(target.stat().st_size)}")
    return ctx.done(target)


@tool(id="zip_to_pdf", name="ZIP of images or documents to PDF",
      category="convert", inputs="any+", batchable=False,
      summary="Unpack an archive and convert everything inside that can "
              "become a PDF.",
      params=[P("mode", "Output", "choice", "one PDF per archive",
                choices=("one PDF per archive", "one PDF per file inside")),
              P("sort", "Order", "choice", "file name",
                choices=("file name", "archive order")),
              P("size", "Page size for images", "choice", "fit the image",
                choices=("fit the image",) + tuple(PAGE_SIZES)),
              P("quality", "Image quality", "int", 88, lo=30, hi=100)])
def zip_to_pdf(ctx):
    from pdfbuilder.core.images import load_image
    archives = [p for p in ctx.inputs if p.suffix.lower() in (".zip", ".cbz")]
    if not archives:
        raise ToolError("Select one or more .zip archives.")
    made = []
    for path in archives:
        work = ctx.tmp / path.stem
        work.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if not n.endswith("/")]
                if ctx.p["sort"] == "file name":
                    names.sort(key=str.lower)
                safe = []
                for n_i, member in enumerate(names, 1):
                    ctx.progress(n_i / max(1, len(names)), member)
                    dest = (work / member).resolve()
                    if not str(dest).startswith(str(work.resolve())):
                        continue        # refuse path traversal in the archive
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as fh, open(dest, "wb") as out:
                        shutil.copyfileobj(fh, out)
                    safe.append(dest)
        except zipfile.BadZipFile:
            raise ToolError(f"{path.name} is not a readable ZIP archive.")

        imgs = [p for p in safe if is_image(p)]
        pdfs = [p for p in safe if is_pdf(p)]
        others = [p for p in safe if p not in imgs and p not in pdfs
                  and p.suffix.lower() in (".txt", ".md", ".html", ".htm",
                                           ".csv", ".log")]
        if not (imgs or pdfs or others):
            raise ToolError(f"{path.name} contains nothing convertible "
                            f"(images, PDFs or text files).")
        doc = fitz.open()
        for img_path in imgs:
            img = load_image(img_path)
            import io
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG",
                                    quality=int(ctx.p["quality"]))
            if ctx.p["size"] == "fit the image":
                pw, ph = img.width * 0.75, img.height * 0.75
            else:
                w, h = PAGE_SIZES[ctx.p["size"]]
                pw, ph = ((max(w, h), min(w, h)) if img.width > img.height
                          else (min(w, h), max(w, h)))
            page = doc.new_page(width=pw, height=ph)
            page.insert_image(page.rect, stream=buf.getvalue(),
                              keep_proportion=True)
        for pdf_path in pdfs:
            try:
                sub = fitz.open(pdf_path)
                doc.insert_pdf(sub)
                sub.close()
            except Exception:
                continue
        for txt in others:
            tmp = ctx.tmp / (txt.stem + ".pdf")
            try:
                body = _html.escape(txt.read_text(encoding="utf-8",
                                                  errors="replace"))
                _story_to_pdf(f"<body><h2>{_html.escape(txt.name)}</h2>"
                              f"<pre>{body}</pre></body>", tmp, css=DEFAULT_CSS)
                sub = fitz.open(tmp)
                doc.insert_pdf(sub)
                sub.close()
            except Exception:
                continue
        if ctx.p["mode"] == "one PDF per file inside":
            for i in range(doc.page_count):
                part = fitz.open()
                part.insert_pdf(doc, from_page=i, to_page=i)
                made.append(save_pdf(part, ctx.derive(f"page{i+1:04d}", ".pdf",
                                                      src=path)))
                part.close()
        else:
            made.append(save_pdf(doc, ctx.derive("archive", ".pdf", src=path)))
        doc.close()
    return ctx.done(*made)
