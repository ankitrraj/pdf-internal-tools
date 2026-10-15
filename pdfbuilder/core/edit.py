"""Category 3 - editing and annotation.

The visual editor panel does the interactive work (draw, drag, resize, undo);
these tools are the scriptable equivalents and the shared primitives the
editor calls when it exports.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from pdfbuilder.core.common import (FONT_CHOICES, MM, fade_image, open_pdf,
                                    parse_color, parse_pages, save_pdf,
                                    search_text)
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Password (if protected)", "str", "")
PAGES = P("pages", "Pages", "pages", "all")

STAMPS = ("APPROVED", "NOT APPROVED", "DRAFT", "FINAL", "CONFIDENTIAL",
          "FOR REVIEW", "URGENT", "PAID", "COPY", "ORIGINAL", "VOID",
          "RECEIVED", "custom text")

STAMP_COLORS = {
    "APPROVED": "#1b7f37", "FINAL": "#1b7f37", "PAID": "#1b7f37",
    "NOT APPROVED": "#c00000", "VOID": "#c00000", "URGENT": "#c00000",
    "DRAFT": "#b45309", "FOR REVIEW": "#b45309",
    "CONFIDENTIAL": "#c00000", "COPY": "#475569", "ORIGINAL": "#1d4ed8",
    "RECEIVED": "#1d4ed8",
}


@tool(id="editor", name="Open the visual editor", category="edit",
      view="editor",
      summary="Add text, pictures, shapes, highlights, freehand drawing, "
              "sticky notes and stamps directly on the page. Move and "
              "resize anything, undo and redo, then preview before export.")
def editor(ctx):
    raise ToolError("This tool runs in the editor panel.")


@tool(id="add_text", name="Add text at a position", category="edit",
      summary="Place a block of text on chosen pages at exact coordinates.",
      params=[P("text", "Text", "text", "Your text here"),
              P("x", "Left", "float", 20, lo=-500, hi=2000, suffix=" mm"),
              P("y", "Top", "float", 20, lo=-500, hi=2000, suffix=" mm"),
              P("width", "Box width", "float", 120, lo=5, hi=2000,
                suffix=" mm"),
              P("font", "Font", "choice", "helv", choices=FONT_CHOICES),
              P("size", "Text size", "float", 12, lo=4, hi=200, suffix=" pt"),
              P("color", "Colour", "color", "#111111"),
              P("align", "Alignment", "choice", "left",
                choices=("left", "centre", "right", "justify")),
              P("rotate", "Rotation", "choice", "0",
                choices=("0", "90", "180", "270")),
              P("background", "Background", "color", ""),
              P("opacity", "Opacity", "float", 1.0, lo=0.05, hi=1, step=0.05),
              PAGES, PW])
def add_text(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    text = str(ctx.p["text"] or "")
    if not text.strip():
        raise ToolError("Enter the text to add.")
    align = {"left": 0, "centre": 1, "right": 2, "justify": 3}[ctx.p["align"]]
    color = parse_color(ctx.p["color"])
    size = float(ctx.p["size"])
    bg = str(ctx.p["background"] or "").strip()
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        x, y = float(ctx.p["x"]) * MM, float(ctx.p["y"]) * MM
        w = float(ctx.p["width"]) * MM
        lines = text.count("\n") + 1
        h = max(size * 1.45 * lines + 6, size * 2)
        box = fitz.Rect(x, y, x + w, y + h)
        if bg:
            page.draw_rect(box, color=None, fill=parse_color(bg),
                           fill_opacity=float(ctx.p["opacity"]))
        left = page.insert_textbox(box, text, fontsize=size,
                                   fontname=ctx.p["font"], color=color,
                                   align=align, rotate=int(ctx.p["rotate"]),
                                   fill_opacity=float(ctx.p["opacity"]))
        if left < 0:
            # grow the box until the text fits
            box = fitz.Rect(x, y, x + w, y + h + abs(left) + size * 2)
            page.insert_textbox(box, text, fontsize=size,
                                fontname=ctx.p["font"], color=color,
                                align=align, rotate=int(ctx.p["rotate"]))
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("text"))
    doc.close()
    return ctx.done(target)


@tool(id="insert_image_tool", name="Insert an image", category="edit",
      summary="Drop a picture onto chosen pages at a position and size.",
      params=[P("image", "Image file", "file", ""),
              P("x", "Left", "float", 20, lo=-500, hi=2000, suffix=" mm"),
              P("y", "Top", "float", 20, lo=-500, hi=2000, suffix=" mm"),
              P("width", "Width", "float", 60, lo=1, hi=2000, suffix=" mm"),
              P("keep_ratio", "Keep the aspect ratio", "bool", True),
              P("height", "Height", "float", 40, lo=1, hi=2000, suffix=" mm",
                when=("keep_ratio", (False,))),
              P("opacity", "Opacity", "float", 1.0, lo=0.05, hi=1, step=0.05),
              P("rotate", "Rotation", "choice", "0",
                choices=("0", "90", "180", "270")),
              P("behind", "Behind the page content", "bool", False),
              PAGES, PW])
def insert_image_tool(ctx):
    from pdfbuilder.core.images import load_image
    path = str(ctx.p["image"] or "")
    if not path or not Path(path).exists():
        raise ToolError("Choose an image file to insert.")
    img = fade_image(load_image(path), float(ctx.p["opacity"]))
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    w = float(ctx.p["width"]) * MM
    h = (w * img.height / img.width if ctx.p["keep_ratio"]
         else float(ctx.p["height"]) * MM)
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        x, y = float(ctx.p["x"]) * MM, float(ctx.p["y"]) * MM
        page.insert_image(fitz.Rect(x, y, x + w, y + h), stream=data,
                          keep_proportion=bool(ctx.p["keep_ratio"]),
                          rotate=int(ctx.p["rotate"]), alpha=-1,
                          overlay=not ctx.p["behind"])
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("image"))
    doc.close()
    return ctx.done(target)


SHAPES = ("rectangle", "rounded rectangle", "ellipse", "line", "arrow",
          "polyline", "star")


@tool(id="draw_shape", name="Draw a shape or line", category="edit",
      summary="Add rectangles, ellipses, lines, arrows and more.",
      params=[P("shape", "Shape", "choice", "rectangle", choices=SHAPES),
              P("x", "Left / start X", "float", 20, lo=-500, hi=2000,
                suffix=" mm"),
              P("y", "Top / start Y", "float", 20, lo=-500, hi=2000,
                suffix=" mm"),
              P("x2", "Right / end X", "float", 90, lo=-500, hi=2000,
                suffix=" mm"),
              P("y2", "Bottom / end Y", "float", 60, lo=-500, hi=2000,
                suffix=" mm"),
              P("stroke", "Line colour", "color", "#c00000"),
              P("width", "Line width", "float", 1.5, lo=0, hi=40,
                suffix=" pt"),
              P("fill", "Fill colour (blank for none)", "color", ""),
              P("opacity", "Opacity", "float", 1.0, lo=0.05, hi=1, step=0.05),
              P("dashed", "Dashed line", "bool", False),
              PAGES, PW])
def draw_shape(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    stroke = parse_color(ctx.p["stroke"])
    fill_raw = str(ctx.p["fill"] or "").strip()
    fill = parse_color(fill_raw) if fill_raw else None
    width = float(ctx.p["width"])
    op = float(ctx.p["opacity"])
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        x, y = float(ctx.p["x"]) * MM, float(ctx.p["y"]) * MM
        x2, y2 = float(ctx.p["x2"]) * MM, float(ctx.p["y2"]) * MM
        rect = fitz.Rect(min(x, x2), min(y, y2), max(x, x2), max(y, y2))
        shape = page.new_shape()
        kind = ctx.p["shape"]
        if kind == "rectangle":
            shape.draw_rect(rect)
        elif kind == "rounded rectangle":
            shape.draw_rect(rect, radius=0.14)
        elif kind == "ellipse":
            shape.draw_oval(rect)
        elif kind == "line":
            shape.draw_line((x, y), (x2, y2))
        elif kind == "arrow":
            shape.draw_line((x, y), (x2, y2))
            _arrow_head(shape, (x, y), (x2, y2), width)
        elif kind == "polyline":
            shape.draw_polyline([(x, y), ((x + x2) / 2, y2), (x2, y)])
        else:
            _star(shape, rect)
        shape.finish(color=stroke if width > 0 else None, fill=fill,
                     width=width, dashes="[3 3] 0" if ctx.p["dashed"] else None,
                     stroke_opacity=op, fill_opacity=op,
                     closePath=kind not in ("line", "arrow", "polyline"))
        shape.commit()
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("shape"))
    doc.close()
    return ctx.done(target)


def _arrow_head(shape, start, end, width):
    import math
    (x1, y1), (x2, y2) = start, end
    ang = math.atan2(y2 - y1, x2 - x1)
    size = max(6.0, width * 4)
    for side in (-1, 1):
        a = ang + side * math.radians(150)
        shape.draw_line((x2, y2),
                        (x2 + size * math.cos(a), y2 + size * math.sin(a)))


def _star(shape, rect, points: int = 5):
    import math
    cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
    R = min(rect.width, rect.height) / 2
    pts = []
    for k in range(points * 2):
        r = R if k % 2 == 0 else R * 0.42
        a = -math.pi / 2 + k * math.pi / points
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    shape.draw_polyline(pts + [pts[0]])


MARKUPS = {
    "highlight": "add_highlight_annot",
    "underline": "add_underline_annot",
    "strike through": "add_strikeout_annot",
    "squiggly underline": "add_squiggly_annot",
}


@tool(id="markup_text", name="Highlight, underline or strike through text",
      category="edit",
      summary="Find words or phrases and mark them up. Works on any PDF with "
              "a text layer.",
      params=[P("style", "Markup", "choice", "highlight",
                choices=tuple(MARKUPS)),
              P("terms", "Words or phrases (one per line)", "text", ""),
              P("color", "Colour", "color", "#ffe14d"),
              P("case", "Match case", "bool", False),
              P("first_only", "Only the first match on each page", "bool",
                False),
              P("opacity", "Opacity", "float", 0.45, lo=0.05, hi=1,
                step=0.05),
              P("note", "Add a comment to each mark", "str", ""),
              PAGES, PW])
def markup_text(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    terms = [t for t in str(ctx.p["terms"] or "").splitlines() if t.strip()]
    if not terms:
        raise ToolError("Enter at least one word or phrase to mark up.")
    method = MARKUPS[ctx.p["style"]]
    color = parse_color(ctx.p["color"])
    hits = 0
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        for term in terms:
            found = search_text(page, term, case=bool(ctx.p["case"]))
            if ctx.p["first_only"]:
                found = found[:1]
            for rect in found:
                annot = getattr(page, method)(rect)
                annot.set_colors(stroke=color)
                annot.set_opacity(float(ctx.p["opacity"]))
                if str(ctx.p["note"] or "").strip():
                    annot.set_info(content=str(ctx.p["note"]))
                annot.update()
                hits += 1
        ctx.progress(n / len(idxs))
    if hits == 0:
        doc.close()
        raise ToolError("No matches found. If this is a scan, run OCR first "
                        "so the words become searchable.")
    target = save_pdf(doc, ctx.derive(ctx.p["style"].split()[0]))
    doc.close()
    ctx.log(f"Marked up {hits} occurrence(s).")
    return ctx.done(target)


@tool(id="sticky_note", name="Add a sticky-note comment", category="edit",
      summary="Attach a pop-up comment to a position, or to every match of "
              "a search term.",
      params=[P("text", "Comment", "text", ""),
              P("author", "Author", "str", ""),
              P("anchor", "Place", "choice", "at a position",
                choices=("at a position", "on each match of a term")),
              P("term", "Search term", "str", "",
                when=("anchor", ("on each match of a term",))),
              P("x", "Left", "float", 20, lo=0, hi=2000, suffix=" mm",
                when=("anchor", ("at a position",))),
              P("y", "Top", "float", 20, lo=0, hi=2000, suffix=" mm",
                when=("anchor", ("at a position",))),
              P("icon", "Icon", "choice", "Comment",
                choices=("Comment", "Note", "Help", "Insert", "Key",
                         "NewParagraph", "Paragraph")),
              P("color", "Icon colour", "color", "#ffd000"),
              P("open", "Show the note expanded", "bool", False),
              PAGES, PW])
def sticky_note(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    body = str(ctx.p["text"] or "").strip()
    if not body:
        raise ToolError("Type the comment text.")
    color = parse_color(ctx.p["color"])
    added = 0
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        spots = []
        if ctx.p["anchor"] == "at a position":
            spots = [fitz.Point(float(ctx.p["x"]) * MM,
                                float(ctx.p["y"]) * MM)]
        else:
            term = str(ctx.p["term"] or "").strip()
            if not term:
                raise ToolError("Enter the search term to attach notes to.")
            for rect in search_text(page, term):
                spots.append(fitz.Point(rect.x1 + 4, rect.y0))
        for pt in spots:
            annot = page.add_text_annot(pt, body, icon=ctx.p["icon"])
            annot.set_colors(stroke=color)
            info = annot.info
            if str(ctx.p["author"] or "").strip():
                info["title"] = str(ctx.p["author"])
            annot.set_info(info)
            if ctx.p["open"]:
                annot.set_open(True)
            annot.update()
            added += 1
        ctx.progress(n / len(idxs))
    if not added:
        doc.close()
        raise ToolError("Nothing to attach the note to - no matches found.")
    target = save_pdf(doc, ctx.derive("commented"))
    doc.close()
    ctx.log(f"Added {added} comment(s).")
    return ctx.done(target)


@tool(id="stamp", name="Add a stamp", category="edit",
      summary="Apply a classic rubber stamp such as APPROVED, DRAFT or PAID.",
      params=[P("kind", "Stamp", "choice", "APPROVED", choices=STAMPS),
              P("text", "Custom text", "str", "",
                when=("kind", ("custom text",))),
              P("position", "Position", "choice", "top-right",
                choices=("top-right", "top-left", "top-center", "centre",
                         "bottom-right", "bottom-left", "bottom-center")),
              P("size", "Text size", "float", 22, lo=6, hi=120, suffix=" pt"),
              P("color", "Colour", "color", ""),
              P("rotate", "Rotation", "float", 0, lo=-180, hi=180,
                suffix=" deg"),
              P("opacity", "Opacity", "float", 0.85, lo=0.05, hi=1,
                step=0.05),
              P("frame", "Draw a frame", "bool", True),
              P("date", "Include today's date", "bool", False),
              P("margin", "Margin", "float", 14, lo=0, hi=120, suffix=" mm"),
              PAGES, PW])
def stamp(ctx):
    import datetime
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    kind = ctx.p["kind"]
    label = (str(ctx.p["text"] or "").strip() if kind == "custom text"
             else kind)
    if not label:
        raise ToolError("Enter the stamp text.")
    chosen = str(ctx.p["color"] or "").strip()
    color = parse_color(chosen or STAMP_COLORS.get(kind, "#c00000"))
    size = float(ctx.p["size"])
    pad = size * 0.55
    m = float(ctx.p["margin"]) * MM
    sub = datetime.date.today().strftime("%d %b %Y") if ctx.p["date"] else ""
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        r = page.rect
        tw = fitz.get_text_length(label, "hebo", size)
        sw = fitz.get_text_length(sub, "helv", size * 0.5) if sub else 0
        bw = max(tw, sw) + pad * 2
        bh = size * (2.0 if sub else 1.5) + pad * 0.5
        pos = ctx.p["position"]
        if pos == "centre":
            x, y = (r.width - bw) / 2, (r.height - bh) / 2
        else:
            vert, horiz = pos.split("-")
            y = r.y0 + m if vert == "top" else r.y1 - m - bh
            x = {"left": r.x0 + m, "right": r.x1 - m - bw,
                 "center": (r.width - bw) / 2}[horiz]
        box = fitz.Rect(x, y, x + bw, y + bh)
        rot = float(ctx.p["rotate"])
        # a morph rotates everything about the stamp's own centre
        morph = ((fitz.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2),
                  fitz.Matrix(rot)) if rot else None)
        shape = page.new_shape()
        if ctx.p["frame"]:
            shape.draw_rect(box, radius=0.12)
            shape.finish(color=color, width=max(1.2, size / 14),
                         stroke_opacity=float(ctx.p["opacity"]), morph=morph)
        shape.insert_textbox(box + (pad * 0.5, pad * 0.3, -pad * 0.5, 0),
                             label, fontname="hebo", fontsize=size,
                             color=color, align=1, morph=morph,
                             fill_opacity=float(ctx.p["opacity"]))
        if sub:
            shape.insert_textbox(
                fitz.Rect(box.x0, box.y0 + size * 1.35, box.x1, box.y1),
                sub, fontname="helv", fontsize=size * 0.5, color=color,
                align=1, morph=morph, fill_opacity=float(ctx.p["opacity"]))
        shape.commit()
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("stamped"))
    doc.close()
    return ctx.done(target)


@tool(id="freehand", name="Freehand ink from a path", category="edit",
      summary="Draw ink strokes from coordinates - the editor panel writes "
              "these for you when you draw with the mouse.",
      params=[P("points", "Points (x,y per line, blank line = new stroke)",
                "text", "20,20\n40,30\n60,20"),
              P("units", "Coordinates are in", "choice", "mm",
                choices=("mm", "points")),
              P("color", "Ink colour", "color", "#1d4ed8"),
              P("width", "Line width", "float", 2.0, lo=0.2, hi=30,
                suffix=" pt"),
              P("opacity", "Opacity", "float", 1.0, lo=0.05, hi=1, step=0.05),
              PAGES, PW])
def freehand(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    scale = MM if ctx.p["units"] == "mm" else 1.0
    strokes, current = [], []
    for line in str(ctx.p["points"] or "").splitlines():
        line = line.strip()
        if not line:
            if current:
                strokes.append(current)
                current = []
            continue
        parts = line.replace(";", ",").split(",")
        if len(parts) < 2:
            continue
        try:
            current.append(fitz.Point(float(parts[0]) * scale,
                                      float(parts[1]) * scale))  # noqa: E501
        except ValueError:
            raise ToolError(f"Could not read the coordinate: {line!r}")
    if current:
        strokes.append(current)
    strokes = [s for s in strokes if len(s) >= 2]
    if not strokes:
        raise ToolError("Give at least two points, as 'x,y' on each line.")
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        annot = page.add_ink_annot([[(p.x, p.y) for p in s] for s in strokes])
        annot.set_colors(stroke=parse_color(ctx.p["color"]))
        annot.set_border(width=float(ctx.p["width"]))
        annot.set_opacity(float(ctx.p["opacity"]))
        annot.update()
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("ink"))
    doc.close()
    ctx.log(f"Drew {len(strokes)} stroke(s).")
    return ctx.done(target)


@tool(id="remove_annots", name="Remove annotations", category="edit",
      summary="Delete highlights, comments, ink and stamps - all of them or "
              "just one kind.",
      params=[P("kind", "Remove", "choice", "every annotation",
                choices=("every annotation", "highlights", "comments",
                         "ink drawings", "stamps", "links")),
              P("by_author", "Only from this author", "str", ""),
              PAGES, PW])
def remove_annots(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    wanted = {
        "highlights": {fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE,
                       fitz.PDF_ANNOT_STRIKE_OUT, fitz.PDF_ANNOT_SQUIGGLY},
        "comments": {fitz.PDF_ANNOT_TEXT, fitz.PDF_ANNOT_FREE_TEXT,
                     fitz.PDF_ANNOT_POPUP},
        "ink drawings": {fitz.PDF_ANNOT_INK, fitz.PDF_ANNOT_POLY_LINE},
        "stamps": {fitz.PDF_ANNOT_STAMP},
    }.get(ctx.p["kind"])
    author = str(ctx.p["by_author"] or "").strip().lower()
    removed = 0
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        if ctx.p["kind"] == "links":
            for link in page.get_links():
                page.delete_link(link)
                removed += 1
            continue
        for annot in list(page.annots() or []):
            if wanted is not None and annot.type[0] not in wanted:
                continue
            if author and author not in str(annot.info.get("title", "")).lower():
                continue
            page.delete_annot(annot)
            removed += 1
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("clean"), garbage=3)
    doc.close()
    ctx.log(f"Removed {removed} item(s).")
    return ctx.done(target)
