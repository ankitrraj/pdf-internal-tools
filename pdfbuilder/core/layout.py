"""Category 4 - page layout and formatting."""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from pdfbuilder.core.common import (FONT_CHOICES, MM, PAGE_SIZES,
                                    fade_image, open_pdf, parse_color,
                                    parse_pages, save_pdf)
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Password (if protected)", "str", "")
PAGES = P("pages", "Pages", "pages", "all")
FONT = P("font", "Font", "choice", "helv", choices=FONT_CHOICES)

POSITIONS = ("bottom-center", "bottom-right", "bottom-left", "top-center",
             "top-right", "top-left", "bottom-outer", "top-outer")


def _anchor(rect: fitz.Rect, pos: str, margin: float, pageno: int = 1):
    """Return (x, y, horizontal-align) for a named position."""
    left, right = rect.x0 + margin, rect.x1 - margin
    top, bottom = rect.y0 + margin, rect.y1 - margin
    if pos.endswith("outer"):
        side = "right" if pageno % 2 else "left"
        pos = pos.replace("outer", side)
    vert, horiz = pos.split("-")
    y = bottom if vert == "bottom" else top
    if horiz == "left":
        return left, y, 0
    if horiz == "right":
        return right, y, 2
    return (left + right) / 2, y, 1


@tool(id="crop", name="Crop pages", category="layout",
      summary="Trim a fixed amount off each edge, or crop to the visible "
              "content.",
      params=[P("mode", "Mode", "choice", "margins (mm)",
                choices=("margins (mm)", "percent of page",
                         "auto-detect content")),
              P("left", "Left", "float", 10, lo=0, hi=500,
                when=("mode", ("margins (mm)", "percent of page"))),
              P("right", "Right", "float", 10, lo=0, hi=500,
                when=("mode", ("margins (mm)", "percent of page"))),
              P("top", "Top", "float", 10, lo=0, hi=500,
                when=("mode", ("margins (mm)", "percent of page"))),
              P("bottom", "Bottom", "float", 10, lo=0, hi=500,
                when=("mode", ("margins (mm)", "percent of page"))),
              P("pad", "Keep a border around content", "float", 4, lo=0, hi=100,
                suffix=" mm", when=("mode", ("auto-detect content",))),
              PAGES, PW])
def crop(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    mode = ctx.p["mode"]
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        r = page.rect
        if mode == "auto-detect content":
            box = _content_box(page)
            pad = float(ctx.p["pad"]) * MM
            new = fitz.Rect(box.x0 - pad, box.y0 - pad,
                            box.x1 + pad, box.y1 + pad) & r
        elif mode == "percent of page":
            new = fitz.Rect(r.x0 + r.width * float(ctx.p["left"]) / 100,
                            r.y0 + r.height * float(ctx.p["top"]) / 100,
                            r.x1 - r.width * float(ctx.p["right"]) / 100,
                            r.y1 - r.height * float(ctx.p["bottom"]) / 100)
        else:
            new = fitz.Rect(r.x0 + float(ctx.p["left"]) * MM,
                            r.y0 + float(ctx.p["top"]) * MM,
                            r.x1 - float(ctx.p["right"]) * MM,
                            r.y1 - float(ctx.p["bottom"]) * MM)
        if new.width < 10 or new.height < 10:
            raise ToolError(f"Those crop values leave nothing on page {i+1}.")
        page.set_cropbox(new)
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("cropped"))
    doc.close()
    return ctx.done(target)


def _content_box(page) -> fitz.Rect:
    box = fitz.Rect()
    for blk in page.get_text("blocks"):
        box |= fitz.Rect(blk[:4])
    for d in page.get_drawings():
        box |= d["rect"]
    for info in page.get_images(full=True):
        try:
            for r in page.get_image_rects(info[0]):
                box |= r
        except Exception:
            pass
    return box if not box.is_empty else page.rect


@tool(id="margins", name="Adjust page margins", category="layout",
      summary="Add white space around the existing content, or pull it in, "
              "by scaling each page onto a new canvas.",
      params=[P("left", "Left", "float", 15, lo=-200, hi=200, suffix=" mm"),
              P("right", "Right", "float", 15, lo=-200, hi=200, suffix=" mm"),
              P("top", "Top", "float", 15, lo=-200, hi=200, suffix=" mm"),
              P("bottom", "Bottom", "float", 15, lo=-200, hi=200, suffix=" mm"),
              P("keep_size", "Keep the original page size", "bool", True,
                help="Off: the page grows by the margins instead"),
              PAGES, PW])
def margins(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = set(parse_pages(ctx.p["pages"], doc.page_count))
    L, R, T, B = (float(ctx.p[k]) * MM for k in ("left", "right", "top", "bottom"))
    out = fitz.open()
    for i in range(doc.page_count):
        src = doc[i]
        r = src.rect
        if i not in idxs:
            out.insert_pdf(doc, from_page=i, to_page=i)
            continue
        if ctx.p["keep_size"]:
            pw, ph = r.width, r.height
            inner = fitz.Rect(L, T, pw - R, ph - B)
        else:
            pw, ph = r.width + L + R, r.height + T + B
            inner = fitz.Rect(L, T, L + r.width, T + r.height)
        if inner.width <= 5 or inner.height <= 5:
            raise ToolError("Those margins leave no room for the content.")
        page = out.new_page(width=pw, height=ph)
        page.show_pdf_page(inner, doc, i, rotate=0)
        ctx.progress((i + 1) / doc.page_count)
    target = save_pdf(out, ctx.derive("margins"))
    out.close(); doc.close()
    return ctx.done(target)


@tool(id="page_size", name="Change page size", category="layout",
      summary="Rescale every page onto a standard paper size.",
      params=[P("size", "Paper size", "choice", "A4", choices=tuple(PAGE_SIZES)),
              P("orient", "Orientation", "choice", "keep",
                choices=("keep", "portrait", "landscape")),
              P("fit", "Content fit", "choice", "fit inside (no cropping)",
                choices=("fit inside (no cropping)", "fill (may crop edges)",
                         "stretch to fill")),
              P("center", "Centre the content", "bool", True), PAGES, PW])
def page_size(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = set(parse_pages(ctx.p["pages"], doc.page_count))
    w, h = PAGE_SIZES[ctx.p["size"]]
    out = fitz.open()
    for i in range(doc.page_count):
        src = doc[i]
        sr = src.rect
        if i not in idxs:
            out.insert_pdf(doc, from_page=i, to_page=i)
            continue
        pw, ph = w, h
        want = ctx.p["orient"]
        landscape = sr.width > sr.height if want == "keep" else want == "landscape"
        if landscape:
            pw, ph = max(w, h), min(w, h)
        else:
            pw, ph = min(w, h), max(w, h)
        page = out.new_page(width=pw, height=ph)
        mode = ctx.p["fit"]
        if mode == "stretch to fill":
            box = page.rect
        else:
            sx, sy = pw / sr.width, ph / sr.height
            s = min(sx, sy) if mode.startswith("fit") else max(sx, sy)
            cw, ch = sr.width * s, sr.height * s
            if ctx.p["center"]:
                x0, y0 = (pw - cw) / 2, (ph - ch) / 2
            else:
                x0 = y0 = 0
            box = fitz.Rect(x0, y0, x0 + cw, y0 + ch)
        page.show_pdf_page(box, doc, i)
        ctx.progress((i + 1) / doc.page_count)
    target = save_pdf(out, ctx.derive(ctx.p["size"].lower()))
    out.close(); doc.close()
    return ctx.done(target)


@tool(id="orientation", name="Portrait / landscape", category="layout",
      summary="Force pages to portrait or landscape, rotating or re-laying "
              "out as needed.",
      params=[P("to", "Make pages", "choice", "landscape",
                choices=("landscape", "portrait", "swap")),
              P("how", "Method", "choice", "rotate (keep content size)",
                choices=("rotate (keep content size)",
                         "re-fit content onto new page")),
              PAGES, PW])
def orientation(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    want = ctx.p["to"]

    def needs(page):
        wide = page.rect.width > page.rect.height
        if want == "swap":
            return True
        return (want == "landscape" and not wide) or \
               (want == "portrait" and wide)

    if ctx.p["how"].startswith("rotate"):
        for i in idxs:
            if needs(doc[i]):
                doc[i].set_rotation((doc[i].rotation + 90) % 360)
        target = save_pdf(doc, ctx.derive(want))
        doc.close()
        return ctx.done(target)

    out = fitz.open()
    sel = set(idxs)
    for i in range(doc.page_count):
        src = doc[i]
        if i not in sel or not needs(src):
            out.insert_pdf(doc, from_page=i, to_page=i)
            continue
        r = src.rect
        page = out.new_page(width=r.height, height=r.width)
        s = min(page.rect.width / r.width, page.rect.height / r.height)
        cw, ch = r.width * s, r.height * s
        box = fitz.Rect((page.rect.width - cw) / 2, (page.rect.height - ch) / 2,
                        (page.rect.width + cw) / 2, (page.rect.height + ch) / 2)
        page.show_pdf_page(box, doc, i)
    target = save_pdf(out, ctx.derive(want))
    out.close(); doc.close()
    return ctx.done(target)


NUM_FORMATS = ("1", "Page 1", "Page 1 of N", "1 / N", "- 1 -", "[1]",
               "i, ii, iii", "I, II, III", "a, b, c", "A, B, C")


def _roman(n: int, upper=True) -> str:
    vals = ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"),
            (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"),
            (5, "v"), (4, "iv"), (1, "i"))
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out.upper() if upper else out


def _letters(n: int, upper=False) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(97 + r) + s
    return s.upper() if upper else s


def _label(fmt: str, num: int, total: int, prefix: str, suffix: str) -> str:
    if fmt == "i, ii, iii":
        body = _roman(num, False)
    elif fmt == "I, II, III":
        body = _roman(num, True)
    elif fmt == "a, b, c":
        body = _letters(num, False)
    elif fmt == "A, B, C":
        body = _letters(num, True)
    else:
        body = fmt.replace("N", str(total)).replace("1", str(num))
    return f"{prefix}{body}{suffix}"


@tool(id="page_numbers", name="Add page numbers", category="layout",
      summary="Stamp numbers with a choice of format, position and style.",
      params=[P("format", "Format", "choice", "1", choices=NUM_FORMATS),
              P("position", "Position", "choice", "bottom-center",
                choices=POSITIONS),
              P("start", "Start counting at", "int", 1, lo=-9999, hi=99999),
              P("first_page", "First numbered page", "int", 1, lo=1),
              P("prefix", "Prefix", "str", ""),
              P("suffix", "Suffix", "str", ""),
              FONT, P("size", "Text size", "float", 10, lo=4, hi=96,
                      suffix=" pt"),
              P("color", "Colour", "color", "#333333"),
              P("margin", "Margin", "float", 12, lo=0, hi=200, suffix=" mm"),
              P("skip_first", "Skip the first page", "bool", False),
              PAGES, PW])
def page_numbers(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    if ctx.p["skip_first"]:
        idxs = [i for i in idxs if i != 0]
    first = int(ctx.p["first_page"]) - 1
    idxs = [i for i in idxs if i >= first]
    color = parse_color(ctx.p["color"])
    size = float(ctx.p["size"])
    margin = float(ctx.p["margin"]) * MM
    total = len(idxs)
    for n, i in enumerate(idxs):
        page = doc[i]
        num = int(ctx.p["start"]) + n
        text = _label(ctx.p["format"], num, total, ctx.p["prefix"],
                      ctx.p["suffix"])
        x, y, align = _anchor(page.rect, ctx.p["position"], margin, num)
        tw = fitz.get_text_length(text, ctx.p["font"], size)
        if align == 1:
            x -= tw / 2
        elif align == 2:
            x -= tw
        if y < page.rect.y0 + size * 2:
            y += size
        page.insert_text((x, y), text, fontname=ctx.p["font"], fontsize=size,
                         color=color, rotate=0)
        ctx.progress((n + 1) / max(1, total))
    target = save_pdf(doc, ctx.derive("numbered"))
    doc.close()
    ctx.log(f"Numbered {total} page(s).")
    return ctx.done(target)


@tool(id="watermark_text", name="Add text watermark", category="layout",
      summary="Overlay or underlay repeated text with full control of "
              "opacity, rotation and colour.",
      params=[P("text", "Watermark text", "str", "CONFIDENTIAL"),
              FONT,
              P("size", "Text size", "float", 54, lo=6, hi=400, suffix=" pt"),
              P("color", "Colour", "color", "#d00000"),
              P("opacity", "Opacity", "float", 0.18, lo=0.02, hi=1, step=0.02),
              P("rotate", "Rotation", "float", 45, lo=-180, hi=180,
                suffix=" deg"),
              P("layout", "Placement", "choice", "centred",
                choices=("centred", "tiled across the page") + POSITIONS),
              P("gap", "Tile spacing", "float", 40, lo=5, hi=400,
                when=("layout", ("tiled across the page",))),
              P("behind", "Place behind the content", "bool", False),
              P("outline", "Outline only", "bool", False),
              PAGES, PW])
def watermark_text(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    text = str(ctx.p["text"])
    if not text.strip():
        raise ToolError("Enter some watermark text.")
    color = parse_color(ctx.p["color"])
    size = float(ctx.p["size"])
    opacity = float(ctx.p["opacity"])
    rot = float(ctx.p["rotate"])
    font = ctx.p["font"]
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        r = page.rect
        tw = fitz.get_text_length(text, font, size)
        spots = []
        if ctx.p["layout"] == "centred":
            spots = [(r.width / 2 - tw / 2, r.height / 2)]
        elif ctx.p["layout"] == "tiled across the page":
            gap = float(ctx.p["gap"])
            step_x, step_y = tw + gap, size + gap
            y = r.y0 - step_y
            row = 0
            while y < r.y1 + step_y:
                x = r.x0 - step_x + (step_x / 2 if row % 2 else 0)
                while x < r.x1 + step_x:
                    spots.append((x, y))
                    x += step_x
                y += step_y
                row += 1
        else:
            x, y, align = _anchor(r, ctx.p["layout"], 20, i + 1)
            if align == 1:
                x -= tw / 2
            elif align == 2:
                x -= tw
            spots = [(x, y)]
        shape = page.new_shape()
        for x, y in spots:
            shape.insert_text((x, y), text, fontname=font, fontsize=size,
                              rotate=0, color=color,
                              fill_opacity=0 if ctx.p["outline"] else opacity,
                              stroke_opacity=opacity,
                              render_mode=1 if ctx.p["outline"] else 0,
                              border_width=0.6,
                              morph=(fitz.Point(x, y),
                                     fitz.Matrix(rot)) if rot else None)
        shape.commit(overlay=not ctx.p["behind"])
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("watermarked"))
    doc.close()
    return ctx.done(target)


@tool(id="watermark_image", name="Add image or logo watermark",
      category="layout",
      summary="Stamp a logo or picture, with opacity, scale and rotation.",
      params=[P("image", "Image file", "file", "",
                help="PNG with transparency works best"),
              P("scale", "Width relative to page", "float", 0.35,
                lo=0.02, hi=3, step=0.05),
              P("opacity", "Opacity", "float", 0.25, lo=0.02, hi=1, step=0.02),
              P("rotate", "Rotation", "float", 0, lo=-180, hi=180,
                suffix=" deg"),
              P("position", "Position", "choice", "centre",
                choices=("centre", "tiled across the page") + POSITIONS),
              P("gap", "Tile spacing", "float", 30, lo=0, hi=400,
                when=("position", ("tiled across the page",))),
              P("margin", "Margin", "float", 10, lo=0, hi=200, suffix=" mm"),
              P("behind", "Place behind the content", "bool", False),
              PAGES, PW])
def watermark_image(ctx):
    img_path = str(ctx.p["image"] or "").strip()
    if not img_path or not Path(img_path).exists():
        raise ToolError("Choose an image file for the watermark.")
    from pdfbuilder.core.images import load_image
    pil = load_image(img_path)
    iw, ih = pil.size
    # opacity has to be baked into the pixels: insert_image cannot fade
    pil = fade_image(pil, float(ctx.p["opacity"]))
    buf = ctx.tmp / "wm.png"
    pil.save(buf, "PNG")
    data = buf.read_bytes()

    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    rot = float(ctx.p["rotate"])
    margin = float(ctx.p["margin"]) * MM
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        r = page.rect
        w = r.width * float(ctx.p["scale"])
        h = w * ih / iw
        boxes = []
        if ctx.p["position"] == "centre":
            boxes = [fitz.Rect(0, 0, w, h) + ((r.width - w) / 2,
                                              (r.height - h) / 2,
                                              (r.width - w) / 2,
                                              (r.height - h) / 2)]
        elif ctx.p["position"] == "tiled across the page":
            gap = float(ctx.p["gap"])
            y = r.y0
            while y < r.y1:
                x = r.x0
                while x < r.x1:
                    boxes.append(fitz.Rect(x, y, x + w, y + h))
                    x += w + gap
                y += h + gap
        else:
            x, y, align = _anchor(r, ctx.p["position"], margin, i + 1)
            if align == 1:
                x -= w / 2
            elif align == 2:
                x -= w
            if ctx.p["position"].startswith("bottom"):
                y -= h
            boxes.append(fitz.Rect(x, y, x + w, y + h))
        for box in boxes:
            page.insert_image(box, stream=data, rotate=int(rot) // 90 * 90,
                              overlay=not ctx.p["behind"],
                              keep_proportion=True, alpha=-1)
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("logo"))
    doc.close()
    return ctx.done(target)


@tool(id="header_footer", name="Add headers and footers", category="layout",
      summary="Running text at the top and bottom. Use {page}, {pages}, "
              "{file} and {date} as placeholders.",
      params=[P("header_left", "Header left", "str", ""),
              P("header_center", "Header centre", "str", ""),
              P("header_right", "Header right", "str", ""),
              P("footer_left", "Footer left", "str", ""),
              P("footer_center", "Footer centre", "str", "{page} / {pages}"),
              P("footer_right", "Footer right", "str", ""),
              FONT, P("size", "Text size", "float", 9, lo=4, hi=48,
                      suffix=" pt"),
              P("color", "Colour", "color", "#444444"),
              P("margin", "Distance from edge", "float", 10, lo=0, hi=100,
                suffix=" mm"),
              P("rule", "Draw a separator line", "bool", False),
              PAGES, PW])
def header_footer(ctx):
    import datetime
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    color = parse_color(ctx.p["color"])
    size = float(ctx.p["size"])
    m = float(ctx.p["margin"]) * MM
    font = ctx.p["font"]
    today = datetime.date.today().isoformat()
    slots = [("header_left", "top", 0), ("header_center", "top", 1),
             ("header_right", "top", 2), ("footer_left", "bottom", 0),
             ("footer_center", "bottom", 1), ("footer_right", "bottom", 2)]
    if not any(str(ctx.p[k]).strip() for k, _, _ in slots):
        raise ToolError("Fill in at least one header or footer field.")
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        r = page.rect
        for key, band, align in slots:
            raw = str(ctx.p[key] or "")
            if not raw.strip():
                continue
            text = (raw.replace("{page}", str(i + 1))
                       .replace("{pages}", str(doc.page_count))
                       .replace("{file}", ctx.src.stem)
                       .replace("{date}", today))
            tw = fitz.get_text_length(text, font, size)
            x = {0: r.x0 + m, 1: (r.x0 + r.x1) / 2 - tw / 2,
                 2: r.x1 - m - tw}[align]
            y = r.y0 + m + size if band == "top" else r.y1 - m
            page.insert_text((x, y), text, fontname=font, fontsize=size,
                             color=color)
        if ctx.p["rule"]:
            for band in ("top", "bottom"):
                has = any(str(ctx.p[k]).strip() for k, b, _ in slots if b == band)
                if not has:
                    continue
                y = r.y0 + m + size * 1.5 if band == "top" else r.y1 - m - size
                page.draw_line((r.x0 + m, y), (r.x1 - m, y), color=color,
                               width=0.5)
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("header-footer"))
    doc.close()
    return ctx.done(target)


@tool(id="borders", name="Add page borders", category="layout",
      summary="Draw a frame around each page.",
      params=[P("inset", "Distance from edge", "float", 8, lo=0, hi=100,
                suffix=" mm"),
              P("width", "Line width", "float", 1.2, lo=0.1, hi=20,
                suffix=" pt"),
              P("color", "Colour", "color", "#222222"),
              P("double", "Double line", "bool", False),
              P("radius", "Corner rounding", "float", 0, lo=0, hi=60,
                suffix=" pt"),
              PAGES, PW])
def borders(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    inset = float(ctx.p["inset"]) * MM
    w = float(ctx.p["width"])
    color = parse_color(ctx.p["color"])
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        r = page.rect + (inset, inset, -inset, -inset)
        shape = page.new_shape()
        rad = float(ctx.p["radius"])
        if rad > 0:
            shape.draw_rect(r, radius=min(0.5, rad / max(1, min(r.width,
                                                                r.height))))
        else:
            shape.draw_rect(r)
        if ctx.p["double"]:
            inner = r + (w * 2.5, w * 2.5, -w * 2.5, -w * 2.5)
            if inner.width > 5 and inner.height > 5:
                shape.draw_rect(inner)
        shape.finish(color=color, width=w)
        shape.commit()
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("bordered"))
    doc.close()
    return ctx.done(target)


@tool(id="nup", name="Combine pages onto one sheet", category="layout",
      summary="N-up printing: place 2, 4, 6, 8, 9 or 16 pages per sheet.",
      params=[P("per", "Pages per sheet", "choice", "2",
                choices=("2", "4", "6", "8", "9", "16")),
              P("order", "Order", "choice", "across then down",
                choices=("across then down", "down then across")),
              P("size", "Sheet size", "choice", "match first page",
                choices=("match first page",) + tuple(PAGE_SIZES)),
              P("landscape", "Landscape sheet", "bool", True),
              P("gap", "Gap between pages", "float", 6, lo=0, hi=60,
                suffix=" pt"),
              P("frame", "Draw a frame around each page", "bool", False),
              P("margin", "Sheet margin", "float", 8, lo=0, hi=100,
                suffix=" mm"),
              PW])
def nup(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    per = int(ctx.p["per"])
    grids = {2: (1, 2), 4: (2, 2), 6: (2, 3), 8: (2, 4), 9: (3, 3),
             16: (4, 4)}
    cols, rows = grids[per]
    if ctx.p["landscape"]:
        cols, rows = max(cols, rows), min(cols, rows)
    if ctx.p["size"] == "match first page":
        base = doc[0].rect
        sw, sh = base.width, base.height
        if ctx.p["landscape"] and sw < sh:
            sw, sh = sh, sw
    else:
        w, h = PAGE_SIZES[ctx.p["size"]]
        sw, sh = (max(w, h), min(w, h)) if ctx.p["landscape"] else (w, h)

    out = fitz.open()
    gap = float(ctx.p["gap"])
    m = float(ctx.p["margin"]) * MM
    cw = (sw - 2 * m - gap * (cols - 1)) / cols
    ch = (sh - 2 * m - gap * (rows - 1)) / rows
    if cw < 10 or ch < 10:
        raise ToolError("Too many pages per sheet for that margin.")
    sheet = None
    for i in range(doc.page_count):
        slot = i % per
        if slot == 0:
            sheet = out.new_page(width=sw, height=sh)
        if ctx.p["order"] == "across then down":
            c, rw = slot % cols, slot // cols
        else:
            rw, c = slot % rows, slot // rows
        cell = fitz.Rect(m + c * (cw + gap), m + rw * (ch + gap),
                         m + c * (cw + gap) + cw, m + rw * (ch + gap) + ch)
        src = doc[i].rect
        s = min(cell.width / src.width, cell.height / src.height)
        w2, h2 = src.width * s, src.height * s
        box = fitz.Rect(cell.x0 + (cell.width - w2) / 2,
                        cell.y0 + (cell.height - h2) / 2,
                        cell.x0 + (cell.width + w2) / 2,
                        cell.y0 + (cell.height + h2) / 2)
        sheet.show_pdf_page(box, doc, i)
        if ctx.p["frame"]:
            sheet.draw_rect(box, color=(.7, .7, .7), width=0.5)
        ctx.progress((i + 1) / doc.page_count)
    target = save_pdf(out, ctx.derive(f"{per}up"))
    out.close(); doc.close()
    return ctx.done(target)


@tool(id="split_page", name="Split each page in half", category="layout",
      summary="Cut scanned spreads into single pages.",
      params=[P("direction", "Cut", "choice", "vertically (left | right)",
                choices=("vertically (left | right)",
                         "horizontally (top / bottom)", "into quarters")),
              P("overlap", "Overlap at the cut", "float", 0, lo=0, hi=50,
                suffix=" pt"),
              P("swap", "Right half first (right-to-left books)", "bool", False),
              PAGES, PW])
def split_page(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = set(parse_pages(ctx.p["pages"], doc.page_count))
    out = fitz.open()
    ov = float(ctx.p["overlap"])
    for i in range(doc.page_count):
        src = doc[i]
        r = src.rect
        if i not in idxs:
            out.insert_pdf(doc, from_page=i, to_page=i)
            continue
        if ctx.p["direction"].startswith("vertically"):
            halves = [fitz.Rect(r.x0, r.y0, r.x0 + r.width / 2 + ov, r.y1),
                      fitz.Rect(r.x0 + r.width / 2 - ov, r.y0, r.x1, r.y1)]
            if ctx.p["swap"]:
                halves.reverse()
        elif ctx.p["direction"].startswith("horizontally"):
            halves = [fitz.Rect(r.x0, r.y0, r.x1, r.y0 + r.height / 2 + ov),
                      fitz.Rect(r.x0, r.y0 + r.height / 2 - ov, r.x1, r.y1)]
        else:
            mx, my = r.x0 + r.width / 2, r.y0 + r.height / 2
            halves = [fitz.Rect(r.x0, r.y0, mx, my), fitz.Rect(mx, r.y0, r.x1, my),
                      fitz.Rect(r.x0, my, mx, r.y1), fitz.Rect(mx, my, r.x1, r.y1)]
        for box in halves:
            page = out.new_page(width=box.width, height=box.height)
            page.show_pdf_page(page.rect, doc, i, clip=box)
        ctx.progress((i + 1) / doc.page_count)
    target = save_pdf(out, ctx.derive("split-pages"))
    out.close(); doc.close()
    return ctx.done(target)


@tool(id="flatten", name="Flatten annotations and form fields",
      category="layout",
      summary="Burn annotations, highlights and filled form fields into the "
              "page so they can no longer be edited.",
      params=[P("annots", "Flatten annotations", "bool", True),
              P("forms", "Flatten form fields", "bool", True),
              P("dpi", "Fallback raster resolution", "int", 200, lo=72, hi=600,
                suffix=" dpi",
                help="Used only for pages that cannot be flattened losslessly"),
              P("force_raster", "Rasterise every page (guaranteed flat)",
                "bool", False),
              PAGES, PW])
def flatten(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    if ctx.p["force_raster"]:
        out = fitz.open()
        dpi = int(ctx.p["dpi"])
        for n, i in enumerate(idxs, 1):
            pix = doc[i].get_pixmap(dpi=dpi, annots=True)
            page = out.new_page(width=doc[i].rect.width,
                                height=doc[i].rect.height)
            page.insert_image(page.rect, pixmap=pix)
            ctx.progress(n / len(idxs))
        target = save_pdf(out, ctx.derive("flattened"))
        out.close(); doc.close()
        return ctx.done(target)

    if ctx.p["forms"]:
        for i in idxs:
            page = doc[i]
            for w in list(page.widgets() or []):
                _burn_widget(page, w)
    if ctx.p["annots"]:
        for i in idxs:
            page = doc[i]
            for a in list(page.annots() or []):
                try:
                    pix = a.get_pixmap(dpi=int(ctx.p["dpi"]), alpha=True)
                    page.insert_image(a.rect, pixmap=pix, overlay=True)
                    page.delete_annot(a)
                except Exception:
                    try:
                        page.delete_annot(a)
                    except Exception:
                        pass
    target = save_pdf(doc, ctx.derive("flattened"), garbage=3)
    doc.close()
    ctx.log("Annotations and fields are now part of the page content.")
    return ctx.done(target)


def _burn_widget(page, w):
    """Draw a form field's current value as plain page content, then drop it."""
    try:
        val = w.field_value
        rect = w.rect
        ftype = w.field_type
        txt = ""
        if ftype == fitz.PDF_WIDGET_TYPE_CHECKBOX:
            txt = "X" if val in (True, "Yes", "On", "on", 1) else ""
        elif ftype == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
            txt = "•" if val in (True, "Yes", "On", 1) else ""
        elif val not in (None, ""):
            txt = str(val)
        if txt:
            size = w.text_fontsize or 0
            if not size:
                size = max(6, min(12, rect.height * 0.62))
            page.insert_textbox(rect + (1, 0, -1, 0), txt, fontsize=size,
                                fontname="helv", color=(0, 0, 0),
                                align=fitz.TEXT_ALIGN_LEFT)
        page.delete_widget(w)
    except Exception:
        pass
