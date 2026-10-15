"""Category 7 - office document conversions.

LibreOffice (`soffice`) is used when present because it is by far the most
faithful converter on Linux. Every tool also has a pure-Python fallback so
the app stays useful without it.
"""
from __future__ import annotations

import html as _html
import shutil
from pathlib import Path

import pymupdf as fitz

from pdfbuilder import deps
from pdfbuilder.core.common import open_pdf, parse_pages, save_pdf
from pdfbuilder.core.convert import DEFAULT_CSS, _story_to_pdf
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Password (if protected)", "str", "")

TO_PDF_EXT = {
    "docx": (".docx", ".doc", ".docm"),
    "xlsx": (".xlsx", ".xls", ".xlsm", ".csv"),
    "pptx": (".pptx", ".ppt", ".pptm"),
    "odt": (".odt",), "ods": (".ods",), "odp": (".odp",),
    "rtf": (".rtf",), "epub": (".epub",),
}


def soffice_convert(src: Path, outdir: Path, target: str, ctx,
                    filter_name: str = "") -> Path:
    """Convert with LibreOffice headless. Returns the produced file."""
    exe = deps.require("soffice")
    profile = ctx.tmp / "lo-profile"
    conv = f"{target}:{filter_name}" if filter_name else target
    cmd = [exe, "--headless", "--norestore", "--invisible",
           f"-env:UserInstallation=file://{profile}",
           "--convert-to", conv, "--outdir", str(outdir), str(src)]
    ctx.progress(0.3, f"LibreOffice: {src.name}")
    deps.run(cmd, timeout=600)
    want = outdir / (src.stem + "." + target.split(":")[0])
    if want.exists():
        return want
    cands = sorted(outdir.glob(src.stem + ".*"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    cands = [c for c in cands if c.suffix.lower() != src.suffix.lower()]
    if not cands:
        raise ToolError(f"LibreOffice did not produce an output file for "
                        f"{src.name}.")
    return cands[0]


def _pick(ctx, exts) -> list[Path]:
    got = [p for p in ctx.inputs if p.suffix.lower() in exts]
    if not got:
        raise ToolError("Select file(s) of type: " + ", ".join(sorted(exts)))
    return got


def _office_to_pdf(ctx, exts, tag, fallback):
    srcs = _pick(ctx, exts)
    made = []
    for n, path in enumerate(srcs, 1):
        ctx.progress(n / (len(srcs) + 1), path.name)
        out = ctx.derive(tag, ".pdf", src=path)
        if deps.have("soffice"):
            produced = soffice_convert(path, ctx.tmp, "pdf", ctx)
            shutil.move(str(produced), str(out))
        else:
            ctx.log("LibreOffice is not installed - using the built-in "
                    "converter, which keeps the text but simplifies layout.")
            fallback(ctx, path, out)
        made.append(out)
    return ctx.done(*made)


# --------------------------------------------------------- fallback writers

def _docx_fallback(ctx, path: Path, out: Path):
    try:
        import docx
    except ImportError:
        raise ToolError("Install libreoffice for DOCX conversion.")
    d = docx.Document(str(path))
    parts = []
    for para in d.paragraphs:
        text = _html.escape(para.text)
        style = (para.style.name or "").lower()
        if not text.strip():
            parts.append("<p>&nbsp;</p>")
        elif style.startswith("heading 1") or style == "title":
            parts.append(f"<h1>{text}</h1>")
        elif style.startswith("heading 2"):
            parts.append(f"<h2>{text}</h2>")
        elif style.startswith("heading"):
            parts.append(f"<h3>{text}</h3>")
        elif style.startswith("list"):
            parts.append(f"<p>&bull; {text}</p>")
        else:
            parts.append(f"<p>{text}</p>")
    for table in d.tables:
        rows = []
        for row in table.rows:
            cells = "".join(f"<td>{_html.escape(c.text)}</td>"
                            for c in row.cells)
            rows.append(f"<tr>{cells}</tr>")
        parts.append("<table>" + "".join(rows) + "</table>")
    _story_to_pdf(f"<body>{''.join(parts)}</body>", out, css=DEFAULT_CSS)


def _xlsx_fallback(ctx, path: Path, out: Path):
    import csv
    rows_html = []
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            for row in csv.reader(fh):
                rows_html.append("<tr>" + "".join(
                    f"<td>{_html.escape(str(c))}</td>" for c in row) + "</tr>")
        tables = [("Sheet", rows_html)]
    else:
        try:
            import openpyxl
        except ImportError:
            raise ToolError("Install libreoffice for spreadsheet conversion.")
        wb = openpyxl.load_workbook(str(path), data_only=True)
        tables = []
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                if all(c is None for c in row):
                    continue
                rows.append("<tr>" + "".join(
                    f"<td>{_html.escape('' if c is None else str(c))}</td>"
                    for c in row) + "</tr>")
            tables.append((ws.title, rows))
    body = "".join(f"<h2>{_html.escape(t)}</h2><table>{''.join(r)}</table>"
                   for t, r in tables if r)
    _story_to_pdf(f"<body>{body}</body>", out,
                  css=DEFAULT_CSS + "\ntd{font-size:8.5pt}", size="A4")


def _pptx_fallback(ctx, path: Path, out: Path):
    try:
        from pptx import Presentation
    except ImportError:
        raise ToolError("Install libreoffice for PowerPoint conversion.")
    prs = Presentation(str(path))
    doc = fitz.open()
    w = prs.slide_width / 12700.0   # EMU -> points
    h = prs.slide_height / 12700.0
    for idx, slide in enumerate(prs.slides, 1):
        page = doc.new_page(width=w, height=h)
        page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
        y = 48
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            for para in shape.text_frame.paragraphs:
                text = "".join(r.text for r in para.runs) or para.text
                if not text.strip():
                    continue
                size = 11
                try:
                    if para.runs and para.runs[0].font.size:
                        size = para.runs[0].font.size.pt
                except Exception:
                    pass
                size = max(8, min(34, size))
                page.insert_textbox(fitz.Rect(40, y, w - 40, y + size * 2.4),
                                    text, fontsize=size, fontname="helv",
                                    color=(0.1, 0.1, 0.1))
                y += size * 1.6
                if y > h - 40:
                    break
        page.insert_text((w - 60, h - 20), str(idx), fontsize=9,
                         color=(.5, .5, .5))
    save_pdf(doc, out)
    doc.close()


def _rtf_fallback(ctx, path: Path, out: Path):
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        raise ToolError("Install libreoffice for RTF conversion.")
    text = rtf_to_text(path.read_text(encoding="utf-8", errors="replace"),
                       errors="ignore")
    body = "".join(f"<p>{_html.escape(l)}</p>" if l.strip() else "<p>&nbsp;</p>"
                   for l in text.splitlines())
    _story_to_pdf(f"<body>{body}</body>", out, css=DEFAULT_CSS)


def _epub_fallback(ctx, path: Path, out: Path):
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError:
        raise ToolError("Install libreoffice for EPUB conversion.")
    book = epub.read_epub(str(path))
    parts = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            parts.append(item.get_content().decode("utf-8", "replace"))
    if not parts:
        raise ToolError("No readable chapters found in that EPUB.")
    _story_to_pdf("<body>" + "<hr/>".join(parts) + "</body>", out,
                  css=DEFAULT_CSS)


def _odt_fallback(ctx, path: Path, out: Path):
    import re
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("content.xml").decode("utf-8", "replace")
    except Exception as e:
        raise ToolError(f"Could not read {path.name}: {e}")
    xml = re.sub(r"</text:[ph][^>]*>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    body = "".join(f"<p>{_html.escape(l)}</p>"
                   for l in text.splitlines() if l.strip())
    _story_to_pdf(f"<body>{body}</body>", out, css=DEFAULT_CSS)


# ---------------------------------------------------------- X -> PDF tools

@tool(id="docx_to_pdf", name="Word (DOCX) to PDF", category="office",
      inputs="any+", batchable=False, summary="Convert .docx/.doc to PDF.",
      params=[P("quality", "Fidelity", "choice", "best available",
                choices=("best available", "built-in converter"))])
def docx_to_pdf(ctx):
    return _office_to_pdf(ctx, TO_PDF_EXT["docx"], "pdf", _docx_fallback)


@tool(id="xlsx_to_pdf", name="Excel (XLSX) to PDF", category="office",
      inputs="any+", batchable=False,
      summary="Convert .xlsx/.xls/.csv spreadsheets to PDF.", params=[])
def xlsx_to_pdf(ctx):
    return _office_to_pdf(ctx, TO_PDF_EXT["xlsx"], "pdf", _xlsx_fallback)


@tool(id="pptx_to_pdf", name="PowerPoint (PPTX) to PDF", category="office",
      inputs="any+", batchable=False, summary="Convert slides to PDF.",
      params=[])
def pptx_to_pdf(ctx):
    return _office_to_pdf(ctx, TO_PDF_EXT["pptx"], "pdf", _pptx_fallback)


@tool(id="odt_to_pdf", name="ODT to PDF", category="office", inputs="any+",
      batchable=False, summary="OpenDocument text to PDF.", params=[])
def odt_to_pdf(ctx):
    return _office_to_pdf(ctx, TO_PDF_EXT["odt"], "pdf", _odt_fallback)


@tool(id="ods_to_pdf", name="ODS to PDF", category="office", inputs="any+",
      batchable=False, summary="OpenDocument spreadsheet to PDF.", params=[])
def ods_to_pdf(ctx):
    return _office_to_pdf(ctx, TO_PDF_EXT["ods"], "pdf", _odt_fallback)


@tool(id="odp_to_pdf", name="ODP to PDF", category="office", inputs="any+",
      batchable=False, summary="OpenDocument presentation to PDF.", params=[])
def odp_to_pdf(ctx):
    return _office_to_pdf(ctx, TO_PDF_EXT["odp"], "pdf", _odt_fallback)


@tool(id="rtf_to_pdf", name="RTF to PDF", category="office", inputs="any+",
      batchable=False, summary="Rich Text Format to PDF.", params=[])
def rtf_to_pdf(ctx):
    return _office_to_pdf(ctx, TO_PDF_EXT["rtf"], "pdf", _rtf_fallback)


@tool(id="epub_to_pdf", name="EPUB to PDF", category="office", inputs="any+",
      batchable=False, summary="E-book to PDF, chapter by chapter.", params=[])
def epub_to_pdf(ctx):
    return _office_to_pdf(ctx, TO_PDF_EXT["epub"], "pdf", _epub_fallback)


# ---------------------------------------------------------- PDF -> X tools

@tool(id="pdf_to_docx", name="PDF to Word (DOCX)", category="office",
      summary="Rebuild an editable Word document, keeping layout, tables "
              "and images.",
      params=[P("engine", "Engine", "choice", "layout-aware (recommended)",
                choices=("layout-aware (recommended)", "LibreOffice",
                         "plain text only")),
              P("pages", "Pages", "pages", "all"), PW])
def pdf_to_docx(ctx):
    out = ctx.derive("docx", ".docx")
    engine = ctx.p["engine"]
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    doc.close()

    if engine == "LibreOffice":
        produced = soffice_convert(ctx.src, ctx.tmp, "docx",
                                   ctx, "MS Word 2007 XML")
        shutil.move(str(produced), str(out))
        return ctx.done(out)

    if engine == "layout-aware (recommended)":
        try:
            import logging
            import warnings
            # pdf2docx installs its own root handler and narrates every page;
            # keep that out of the app's activity log
            warnings.filterwarnings("ignore", message=".*fitz.*")
            _before = list(logging.root.handlers)
            from pdf2docx import Converter
            for h in logging.root.handlers:
                if h not in _before:
                    logging.root.removeHandler(h)
            logging.root.setLevel(max(logging.WARNING, logging.root.level))
            ctx.progress(0.2, "Analysing layout")
            import contextlib
            import io as _io
            cv = Converter(str(ctx.src), password=ctx.p["password"] or None)
            with contextlib.redirect_stdout(_io.StringIO()):
                cv.convert(str(out), start=min(idxs), end=max(idxs) + 1)
            cv.close()
            ctx.progress(0.95, "Saved")
            if out.exists():
                return ctx.done(out)
        except Exception as e:
            ctx.log(f"Layout-aware conversion failed ({e}); falling back to "
                    f"plain text.")

    import docx
    d = docx.Document()
    src = open_pdf(ctx.src, ctx.p["password"])
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        for block in src[i].get_text("blocks"):
            text = block[4].strip()
            if text:
                d.add_paragraph(text)
        if n < len(idxs):
            d.add_page_break()
    src.close()
    d.save(str(out))
    return ctx.done(out)


@tool(id="pdf_to_xlsx", name="PDF to Excel (XLSX)", category="office",
      summary="Detect tables and write them into a spreadsheet, one sheet "
              "per page.",
      params=[P("strategy", "Table detection", "choice", "lines and text",
                choices=("lines and text", "ruling lines only",
                         "text alignment only")),
              P("merge", "Put every table on one sheet", "bool", False),
              P("pages", "Pages", "pages", "all"), PW])
def pdf_to_xlsx(ctx):
    try:
        import openpyxl
        import pdfplumber
    except ImportError:
        raise ToolError("pdfplumber/openpyxl are missing. Reinstall with "
                        "./install.sh")
    out = ctx.derive("xlsx", ".xlsx")
    settings = {
        "lines and text": {"vertical_strategy": "lines",
                           "horizontal_strategy": "lines"},
        "ruling lines only": {"vertical_strategy": "lines",
                              "horizontal_strategy": "lines",
                              "snap_tolerance": 4},
        "text alignment only": {"vertical_strategy": "text",
                                "horizontal_strategy": "text"},
    }[ctx.p["strategy"]]
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    found = 0
    merged = wb.create_sheet("All tables") if ctx.p["merge"] else None
    row_cursor = 1
    with pdfplumber.open(str(ctx.src),
                         password=ctx.p["password"] or "") as pdf:
        idxs = parse_pages(ctx.p["pages"], len(pdf.pages))
        for n, i in enumerate(idxs, 1):
            ctx.progress(n / len(idxs), f"Page {i+1}")
            page = pdf.pages[i]
            tables = page.extract_tables(settings) or []
            if not tables and ctx.p["strategy"] != "text alignment only":
                tables = page.extract_tables(
                    {"vertical_strategy": "text",
                     "horizontal_strategy": "text"}) or []
            for t_i, table in enumerate(tables, 1):
                found += 1
                ws = merged or wb.create_sheet(f"p{i+1}_t{t_i}"[:31])
                if merged:
                    ws.cell(row=row_cursor, column=1,
                            value=f"Page {i+1} table {t_i}")
                    row_cursor += 1
                for row in table:
                    for c_i, val in enumerate(row, 1):
                        ws.cell(row=row_cursor, column=c_i,
                                value=("" if val is None else str(val)))
                    row_cursor += 1
                if merged:
                    row_cursor += 2
                else:
                    row_cursor = 1
            if not tables:
                ws = merged or wb.create_sheet(f"p{i+1} text"[:31])
                for line in (page.extract_text() or "").splitlines():
                    ws.cell(row=row_cursor, column=1, value=line)
                    row_cursor += 1
                if not merged:
                    row_cursor = 1
    if not wb.sheetnames:
        wb.create_sheet("Empty")
    wb.save(str(out))
    ctx.log(f"Found {found} table(s)." if found
            else "No tables detected; the page text was written instead.")
    return ctx.done(out)


@tool(id="pdf_to_pptx", name="PDF to PowerPoint (PPTX)", category="office",
      summary="One slide per page. Choose a picture-perfect image slide or "
              "an editable text slide.",
      params=[P("style", "Slide content", "choice", "page image (exact look)",
                choices=("page image (exact look)", "editable text")),
              P("dpi", "Image resolution", "int", 150, lo=72, hi=400,
                suffix=" dpi", when=("style", ("page image (exact look)",))),
              P("pages", "Pages", "pages", "all"), PW])
def pdf_to_pptx(ctx):
    try:
        from pptx import Presentation
        from pptx.util import Emu, Pt
    except ImportError:
        raise ToolError("python-pptx is missing. Reinstall with ./install.sh")
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    prs = Presentation()
    r0 = doc[idxs[0]].rect
    prs.slide_width = Emu(int(r0.width * 12700))
    prs.slide_height = Emu(int(r0.height * 12700))
    blank = prs.slide_layouts[6]
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        slide = prs.slides.add_slide(blank)
        if ctx.p["style"].startswith("page image"):
            pix = doc[i].get_pixmap(dpi=int(ctx.p["dpi"]))
            tmp = ctx.tmp / f"p{i}.png"
            pix.save(str(tmp))
            slide.shapes.add_picture(str(tmp), 0, 0, prs.slide_width,
                                     prs.slide_height)
        else:
            for blk in doc[i].get_text("blocks"):
                text = blk[4].strip()
                if not text:
                    continue
                box = slide.shapes.add_textbox(
                    Emu(int(blk[0] * 12700)), Emu(int(blk[1] * 12700)),
                    Emu(int(max(20, blk[2] - blk[0]) * 12700)),
                    Emu(int(max(12, blk[3] - blk[1]) * 12700)))
                tf = box.text_frame
                tf.word_wrap = True
                tf.text = text
                for para in tf.paragraphs:
                    for run in para.runs:
                        run.font.size = Pt(11)
    doc.close()
    out = ctx.derive("pptx", ".pptx")
    prs.save(str(out))
    return ctx.done(out)


@tool(id="pdf_to_rtf", name="PDF to RTF", category="office",
      summary="Rich Text output that any word processor can open.",
      params=[P("engine", "Engine", "choice", "automatic",
                choices=("automatic", "LibreOffice", "built-in")),
              P("pages", "Pages", "pages", "all"), PW])
def pdf_to_rtf(ctx):
    out = ctx.derive("rtf", ".rtf")
    if ctx.p["engine"] in ("automatic", "LibreOffice") and deps.have("soffice"):
        try:
            produced = soffice_convert(ctx.src, ctx.tmp, "rtf", ctx,
                                       "Rich Text Format")
            shutil.move(str(produced), str(out))
            return ctx.done(out)
        except ToolError:
            if ctx.p["engine"] == "LibreOffice":
                raise
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    parts = [r"{\rtf1\ansi\deff0{\fonttbl{\f0 Helvetica;}}\fs22", ""]
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        for blk in doc[i].get_text("blocks"):
            text = blk[4].strip()
            if not text:
                continue
            esc = (text.replace("\\", r"\\").replace("{", r"\{")
                   .replace("}", r"\}"))
            esc = "".join(ch if ord(ch) < 128 else rf"\u{ord(ch)}?"
                          for ch in esc)
            parts.append(esc.replace("\n", r"\line ") + r"\par ")
        if n < len(idxs):
            parts.append(r"\page ")
    doc.close()
    parts.append("}")
    out.write_text("\n".join(parts), encoding="ascii", errors="replace")
    return ctx.done(out)


@tool(id="pdf_to_csv", name="PDF to CSV", category="office",
      summary="Write detected tables to CSV - one file per table, or all "
              "rows in one.",
      params=[P("strategy", "Table detection", "choice", "lines and text",
                choices=("lines and text", "ruling lines only",
                         "text alignment only")),
              P("one_file", "All tables in one CSV", "bool", False),
              P("delimiter", "Delimiter", "choice", "comma",
                choices=("comma", "semicolon", "tab", "pipe")),
              P("zip", "Bundle as ZIP", "bool", False),
              P("pages", "Pages", "pages", "all"), PW])
def pdf_to_csv(ctx):
    import csv
    try:
        import pdfplumber
    except ImportError:
        raise ToolError("pdfplumber is missing. Reinstall with ./install.sh")
    delim = {"comma": ",", "semicolon": ";", "tab": "\t", "pipe": "|"}[
        ctx.p["delimiter"]]
    settings = {
        "lines and text": {"vertical_strategy": "lines",
                           "horizontal_strategy": "lines"},
        "ruling lines only": {"vertical_strategy": "lines",
                              "horizontal_strategy": "lines"},
        "text alignment only": {"vertical_strategy": "text",
                                "horizontal_strategy": "text"},
    }[ctx.p["strategy"]]
    made, all_rows, count = [], [], 0
    with pdfplumber.open(str(ctx.src),
                         password=ctx.p["password"] or "") as pdf:
        idxs = parse_pages(ctx.p["pages"], len(pdf.pages))
        for n, i in enumerate(idxs, 1):
            ctx.progress(n / len(idxs), f"Page {i+1}")
            tables = pdf.pages[i].extract_tables(settings) or []
            if not tables:
                tables = pdf.pages[i].extract_tables(
                    {"vertical_strategy": "text",
                     "horizontal_strategy": "text"}) or []
            for table in tables:
                count += 1
                rows = [["" if c is None else str(c).replace("\n", " ")
                         for c in row] for row in table]
                if ctx.p["one_file"]:
                    all_rows.append([f"# page {i+1} table {count}"])
                    all_rows.extend(rows)
                else:
                    out = ctx.derive(f"p{i+1}-table{count}", ".csv")
                    with open(out, "w", newline="", encoding="utf-8") as fh:
                        csv.writer(fh, delimiter=delim).writerows(rows)
                    made.append(out)
    if ctx.p["one_file"] and all_rows:
        out = ctx.derive("tables", ".csv")
        with open(out, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh, delimiter=delim).writerows(all_rows)
        made.append(out)
    if not made:
        raise ToolError("No tables were detected. Try 'text alignment only', "
                        "or run OCR first if this is a scan.")
    if ctx.p["zip"]:
        made.append(ctx.zip_up(made, ctx.src.stem + "-csv"))
    ctx.log(f"Exported {count} table(s).")
    return ctx.done(*made)


@tool(id="pdf_to_xml", name="PDF to XML", category="office",
      summary="Structured XML with pages, blocks, lines and coordinates.",
      params=[P("detail", "Detail", "choice", "blocks and lines",
                choices=("blocks and lines", "words with positions",
                         "raw PyMuPDF XML")),
              P("pages", "Pages", "pages", "all"), PW])
def pdf_to_xml(ctx):
    from xml.sax.saxutils import escape
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    out = ctx.derive("xml", ".xml")
    if ctx.p["detail"] == "raw PyMuPDF XML":
        chunks = ['<?xml version="1.0" encoding="UTF-8"?>\n<document>']
        for n, i in enumerate(idxs, 1):
            ctx.progress(n / len(idxs))
            chunks.append(doc[i].get_text("xml"))
        chunks.append("</document>")
        out.write_text("\n".join(chunks), encoding="utf-8")
        doc.close()
        return ctx.done(out)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<document source="{escape(ctx.src.name)}" '
             f'pages="{doc.page_count}">']
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        page = doc[i]
        r = page.rect
        lines.append(f'  <page number="{i+1}" width="{r.width:.1f}" '
                     f'height="{r.height:.1f}">')
        if ctx.p["detail"].startswith("words"):
            for w in page.get_text("words"):
                lines.append(f'    <word x="{w[0]:.1f}" y="{w[1]:.1f}" '
                             f'x2="{w[2]:.1f}" y2="{w[3]:.1f}">'
                             f'{escape(w[4])}</word>')
        else:
            for b_i, blk in enumerate(page.get_text("blocks"), 1):
                if not blk[4].strip():
                    continue
                lines.append(f'    <block id="{b_i}" x="{blk[0]:.1f}" '
                             f'y="{blk[1]:.1f}" x2="{blk[2]:.1f}" '
                             f'y2="{blk[3]:.1f}">')
                for ln in blk[4].splitlines():
                    if ln.strip():
                        lines.append(f'      <line>{escape(ln)}</line>')
                lines.append("    </block>")
        lines.append("  </page>")
    lines.append("</document>")
    doc.close()
    out.write_text("\n".join(lines), encoding="utf-8")
    return ctx.done(out)
