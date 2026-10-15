"""Category 10 - document utilities."""
from __future__ import annotations

import datetime
from collections import Counter
from pathlib import Path

import pymupdf as fitz

from pdfbuilder import deps
from pdfbuilder.core.common import (human_size, open_pdf, parse_pages,
                                    save_pdf)
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Password (if protected)", "str", "")


def _fmt_date(raw: str) -> str:
    if not raw:
        return "-"
    s = str(raw).replace("D:", "")[:14]
    try:
        return datetime.datetime.strptime(s, "%Y%m%d%H%M%S").strftime(
            "%d %b %Y, %H:%M")
    except ValueError:
        return str(raw)


@tool(id="view_pdf", name="View PDF", category="utility", view="viewer",
      summary="Open the document: scroll, zoom, fit to page, search for "
              "text, print, and save single pages.")
def view_pdf(ctx):
    raise ToolError("This tool opens the viewer panel.")


@tool(id="search_text", name="Search for text", category="utility",
      inputs="pdf+", batchable=False,
      summary="Find a word or phrase across one or many PDFs and list every "
              "hit with its page number.",
      params=[P("query", "Search for", "str", ""),
              P("regex", "Regular expression", "bool", False),
              P("case", "Match case", "bool", False),
              P("whole", "Whole words only", "bool", False),
              P("context", "Characters of context", "int", 60, lo=0, hi=400),
              P("save", "Save the results as a text file", "bool", False),
              PW])
def search_text(ctx):
    import re
    query = str(ctx.p["query"] or "").strip()
    if not query:
        raise ToolError("Type something to search for.")
    flags = 0 if ctx.p["case"] else re.IGNORECASE
    if ctx.p["regex"]:
        try:
            pat = re.compile(query, flags)
        except re.error as e:
            raise ToolError(f"Invalid regular expression: {e}")
    else:
        body = re.escape(query)
        if ctx.p["whole"]:
            body = rf"\b{body}\b"
        pat = re.compile(body, flags)
    ctx_len = int(ctx.p["context"])
    lines, total = [], 0
    for path in ctx.inputs:
        doc = open_pdf(path, ctx.p["password"])
        for i in range(doc.page_count):
            ctx.progress((i + 1) / doc.page_count, f"{path.name} p{i+1}")
            text = doc[i].get_text("text")
            for m in pat.finditer(text):
                total += 1
                a = max(0, m.start() - ctx_len)
                b = min(len(text), m.end() + ctx_len)
                snippet = text[a:b].replace("\n", " ").strip()
                lines.append(f"{path.name}  p{i+1}:  ...{snippet}...")
        doc.close()
    if not total:
        ctx.log(f"No matches for {query!r}. If this is a scan, run OCR first.")
        return []
    ctx.log(f"{total} match(es).")
    ctx.summary = {f"{i+1}": l for i, l in enumerate(lines[:300])}
    made = []
    if ctx.p["save"]:
        out = ctx.out("search-results.txt")
        out.write_text(f"Search: {query}\n\n" + "\n".join(lines),
                       encoding="utf-8")
        made.append(out)
    return ctx.done(*made)


@tool(id="properties", name="View document properties", category="utility",
      inputs="pdf+", batchable=False,
      summary="Everything about the file: pages, size, metadata, encryption, "
              "page dimensions, fonts and images.",
      params=[P("save", "Save the report", "bool", False), PW])
def properties(ctx):
    report = {}
    for path in ctx.inputs:
        doc = open_pdf(path, ctx.p["password"])
        meta = doc.metadata or {}
        sizes = Counter()
        for i in range(doc.page_count):
            r = doc[i].rect
            sizes[(round(r.width), round(r.height))] += 1
        dims = ", ".join(
            f"{w}x{h} pt ({w*25.4/72:.0f}x{h*25.4/72:.0f} mm) x{c}"
            for (w, h), c in sizes.most_common(4))
        fonts, images = set(), 0
        for i in range(doc.page_count):
            for f in doc.get_page_fonts(i):
                fonts.add(f[3])
            images += len(doc.get_page_images(i))
        prefix = f"{path.name} · " if len(ctx.inputs) > 1 else ""
        report.update({
            f"{prefix}File": str(path),
            f"{prefix}Size on disk": human_size(path.stat().st_size),
            f"{prefix}Pages": str(doc.page_count),
            f"{prefix}Page sizes": dims,
            f"{prefix}Title": meta.get("title") or "-",
            f"{prefix}Author": meta.get("author") or "-",
            f"{prefix}Subject": meta.get("subject") or "-",
            f"{prefix}Keywords": meta.get("keywords") or "-",
            f"{prefix}Creator": meta.get("creator") or "-",
            f"{prefix}Producer": meta.get("producer") or "-",
            f"{prefix}Created": _fmt_date(meta.get("creationDate")),
            f"{prefix}Modified": _fmt_date(meta.get("modDate")),
            f"{prefix}PDF version": meta.get("format") or "-",
            f"{prefix}Encrypted": "yes" if doc.needs_pass or doc.is_encrypted
                                  else "no",
            f"{prefix}Fonts": f"{len(fonts)} ({', '.join(sorted(fonts)[:6])})"
                              if fonts else "none embedded",
            f"{prefix}Images": str(images),
            f"{prefix}Bookmarks": str(len(doc.get_toc())),
            f"{prefix}Form fields": str(sum(len(list(doc[i].widgets() or []))
                                            for i in range(doc.page_count))),
            f"{prefix}Tagged / linearised": f"{doc.is_pdf and 'PDF'}"
                                            f"{', fast web view' if getattr(doc, 'is_fast_webaccess', False) else ''}",
        })
        doc.close()
    ctx.summary = report
    for k, v in report.items():
        ctx.log(f"{k}: {v}")
    made = []
    if ctx.p["save"]:
        out = ctx.out("properties.txt")
        out.write_text("\n".join(f"{k}: {v}" for k, v in report.items()),
                       encoding="utf-8")
        made.append(out)
    return ctx.done(*made)


@tool(id="page_info", name="Page count, size and dimensions",
      category="utility", inputs="pdf+", batchable=False,
      summary="A quick per-page table of dimensions, rotation, text and "
              "image counts.",
      params=[P("save", "Save as CSV", "bool", False), PW])
def page_info(ctx):
    import csv
    rows = []
    for path in ctx.inputs:
        doc = open_pdf(path, ctx.p["password"])
        for i in range(doc.page_count):
            ctx.progress((i + 1) / doc.page_count)
            page = doc[i]
            r = page.rect
            rows.append({
                "file": path.name, "page": i + 1,
                "width_pt": round(r.width, 1), "height_pt": round(r.height, 1),
                "width_mm": round(r.width * 25.4 / 72, 1),
                "height_mm": round(r.height * 25.4 / 72, 1),
                "orientation": "landscape" if r.width > r.height else "portrait",
                "rotation": page.rotation,
                "characters": len(page.get_text("text")),
                "images": len(page.get_images()),
                "annotations": len(list(page.annots() or [])),
            })
        doc.close()
    ctx.summary = {
        f"{r['file']} p{r['page']}":
        f"{r['width_mm']}x{r['height_mm']} mm · {r['orientation']} · "
        f"rot {r['rotation']}deg · {r['characters']} chars · "
        f"{r['images']} image(s)" for r in rows[:400]}
    ctx.log(f"{len(rows)} page(s) across {len(ctx.inputs)} file(s).")
    made = []
    if ctx.p["save"]:
        out = ctx.out("page-info.csv")
        with open(out, "w", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        made.append(out)
    return ctx.done(*made)


@tool(id="font_info", name="Font and image information", category="utility",
      summary="List every font and image the document uses, with sizes and "
              "whether fonts are embedded.",
      params=[P("save", "Save as CSV", "bool", False), PW])
def font_info(ctx):
    import csv
    doc = open_pdf(ctx.src, ctx.p["password"])
    fonts, images = {}, {}
    for i in range(doc.page_count):
        ctx.progress((i + 1) / doc.page_count, f"Page {i+1}")
        for xref, ext, ftype, name, *_ in doc.get_page_fonts(i):
            rec = fonts.setdefault(name, {"type": ftype, "embedded": ext != "n/a",
                                          "pages": set()})
            rec["pages"].add(i + 1)
        for info in doc.get_page_images(i, full=True):
            xref, _, w, h = info[0], info[1], info[2], info[3]
            rec = images.setdefault(xref, {"w": w, "h": h, "pages": set(),
                                           "bytes": 0})
            rec["pages"].add(i + 1)
            if not rec["bytes"]:
                try:
                    rec["bytes"] = len(doc.extract_image(xref)["image"])
                except Exception:
                    pass
    doc.close()
    summary = {}
    for name, rec in sorted(fonts.items()):
        pages = sorted(rec["pages"])
        summary[f"Font: {name}"] = (
            f"{rec['type']} · "
            f"{'embedded' if rec['embedded'] else 'NOT embedded'} · "
            f"pages {pages[0]}-{pages[-1]} ({len(pages)})")
    for xref, rec in sorted(images.items()):
        pages = sorted(rec["pages"])
        summary[f"Image xref {xref}"] = (
            f"{rec['w']}x{rec['h']} px · {human_size(rec['bytes'])} · "
            f"page(s) {', '.join(str(p) for p in pages[:6])}")
    if not summary:
        summary["Result"] = "No fonts or images are referenced by this PDF."
    ctx.summary = summary
    ctx.log(f"{len(fonts)} font(s), {len(images)} image(s).")
    made = []
    if ctx.p["save"]:
        out = ctx.derive("fonts-images", ".csv")
        with open(out, "w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh)
            wr.writerow(["kind", "name", "detail"])
            for k, v in summary.items():
                wr.writerow([k.split(":")[0], k.split(":", 1)[-1].strip(), v])
        made.append(out)
    return ctx.done(*made)


@tool(id="edit_metadata", name="Edit title, author and subject",
      category="utility",
      summary="Set the document information fields.",
      params=[P("title", "Title", "str", ""),
              P("author", "Author", "str", ""),
              P("subject", "Subject", "str", ""),
              P("keywords", "Keywords", "str", ""),
              P("creator", "Creator application", "str", ""),
              P("blank_means", "Empty boxes", "choice", "keep the current value",
                choices=("keep the current value", "clear the field")),
              P("load_current", "Pre-fill from the file (shown in the log)",
                "bool", True), PW])
def edit_metadata(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    meta = dict(doc.metadata or {})
    if ctx.p["load_current"]:
        for k in ("title", "author", "subject", "keywords", "creator"):
            ctx.log(f"current {k}: {meta.get(k) or '-'}")
    keep = ctx.p["blank_means"].startswith("keep")
    for key in ("title", "author", "subject", "keywords", "creator"):
        new = str(ctx.p[key] or "")
        if new.strip():
            meta[key] = new
        elif not keep:
            meta[key] = ""
    meta["producer"] = meta.get("producer") or "PDF Builder"
    doc.set_metadata(meta)
    target = save_pdf(doc, ctx.derive("metadata"))
    doc.close()
    ctx.log("Document information updated.")
    return ctx.done(target)


@tool(id="bookmarks", name="Add and edit bookmarks", category="utility",
      summary="Replace or extend the outline. One bookmark per line - indent "
              "with two spaces for sub-levels, and end with ' @ 12' for the "
              "page number.",
      params=[P("outline", "Bookmarks", "text",
                "Introduction @ 1\n  Background @ 2\nResults @ 5"),
              P("mode", "Apply", "choice", "replace the existing outline",
                choices=("replace the existing outline", "append",
                         "remove all bookmarks")),
              P("show_current", "Print the current outline to the log",
                "bool", True), PW])
def bookmarks(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    current = doc.get_toc()
    if ctx.p["show_current"]:
        if current:
            for lvl, title, pg in [(e[0], e[1], e[2]) for e in current]:
                ctx.log("  " * (lvl - 1) + f"{title} @ {pg}")
        else:
            ctx.log("This document has no bookmarks yet.")
    if ctx.p["mode"] == "remove all bookmarks":
        doc.set_toc([])
        target = save_pdf(doc, ctx.derive("no-bookmarks"))
        doc.close()
        ctx.log("Removed every bookmark.")
        return ctx.done(target)

    toc = [[e[0], e[1], e[2]] for e in current] if ctx.p["mode"] == "append" else []
    for raw in str(ctx.p["outline"] or "").splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        level = indent // 2 + 1
        body = raw.strip()
        page = 1
        if "@" in body:
            body, _, pg = body.rpartition("@")
            body = body.strip()
            try:
                page = max(1, min(doc.page_count, int(pg.strip())))
            except ValueError:
                raise ToolError(f"Could not read the page number in: {raw!r}")
        if not body:
            continue
        toc.append([level, body, page])
    if not toc:
        raise ToolError("No bookmarks were entered.")
    # levels must not jump by more than one
    fixed, last = [], 0
    for lvl, title, page in toc:
        lvl = min(lvl, last + 1) if last else 1
        fixed.append([lvl, title, page])
        last = lvl
    doc.set_toc(fixed)
    target = save_pdf(doc, ctx.derive("bookmarks"))
    doc.close()
    ctx.log(f"Wrote {len(fixed)} bookmark(s).")
    return ctx.done(target)


@tool(id="toc_page", name="Create a table of contents page",
      category="utility",
      summary="Build a contents page from the bookmarks - or from detected "
              "headings if there are none - and put it at the front.",
      params=[P("source", "Build from", "choice", "bookmarks",
                choices=("bookmarks", "largest text on each page",
                         "page numbers only")),
              P("title", "Heading", "str", "Contents"),
              P("dots", "Dot leaders", "bool", True),
              P("links", "Make the entries clickable", "bool", True),
              P("where", "Place", "choice", "at the front",
                choices=("at the front", "at the end")),
              P("size", "Entry text size", "float", 11, lo=6, hi=24,
                suffix=" pt"),
              P("renumber", "Also add page numbers to the document", "bool",
                False), PW])
def toc_page(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    entries: list[tuple[int, str, int]] = []
    if ctx.p["source"] == "bookmarks":
        entries = [(e[0], e[1], e[2]) for e in doc.get_toc()]
        if not entries:
            ctx.log("No bookmarks found - falling back to detected headings.")
    if not entries and ctx.p["source"] != "page numbers only":
        for i in range(doc.page_count):
            best, best_size = "", 0
            for blk in doc[i].get_text("dict").get("blocks", []):
                for line in blk.get("lines", []):
                    for span in line.get("spans", []):
                        text = span["text"].strip()
                        if len(text) < 3 or span["size"] <= best_size:
                            continue
                        best, best_size = text[:90], span["size"]
            if best:
                entries.append((1, best, i + 1))
    if not entries:
        entries = [(1, f"Page {i+1}", i + 1) for i in range(doc.page_count)]

    w, h = doc[0].rect.width, doc[0].rect.height
    toc_doc = fitz.open()
    margin = 56
    y = margin
    page = toc_doc.new_page(width=w, height=h)
    page.insert_text((margin, y), str(ctx.p["title"] or "Contents"),
                     fontsize=20, fontname="hebo", color=(0.1, 0.1, 0.1))
    y += 34
    size = float(ctx.p["size"])
    links = []
    for lvl, title, pno in entries:
        if y > h - margin:
            page = toc_doc.new_page(width=w, height=h)
            y = margin
        indent = margin + (lvl - 1) * 16
        label = title if len(title) < 95 else title[:92] + "..."
        num = str(pno)
        tw = fitz.get_text_length(label, "helv", size)
        nw = fitz.get_text_length(num, "helv", size)
        page.insert_text((indent, y), label, fontsize=size, fontname="helv",
                         color=(0.1, 0.1, 0.1))
        page.insert_text((w - margin - nw, y), num, fontsize=size,
                         fontname="helv", color=(0.1, 0.1, 0.1))
        if ctx.p["dots"]:
            x0 = indent + tw + 6
            x1 = w - margin - nw - 6
            if x1 > x0:
                page.draw_line((x0, y - 3), (x1, y - 3), color=(0.65, 0.65, 0.65),
                               width=0.5, dashes="[0.6 2.4] 0")
        links.append((toc_doc.page_count - 1,
                      fitz.Rect(indent, y - size, w - margin, y + 4), pno))
        y += size * 1.85
    toc_pages = toc_doc.page_count
    out = fitz.open()
    if ctx.p["where"] == "at the front":
        out.insert_pdf(toc_doc)
        out.insert_pdf(doc)
        offset = toc_pages
    else:
        out.insert_pdf(doc)
        out.insert_pdf(toc_doc)
        offset = 0
    if ctx.p["links"]:
        base = 0 if ctx.p["where"] == "at the front" else doc.page_count
        for pidx, rect, target_page in links:
            dest = target_page - 1 + offset
            if 0 <= dest < out.page_count:
                out[base + pidx].insert_link({
                    "kind": fitz.LINK_GOTO, "from": rect, "page": dest})
    shifted = [[lvl, title, pno + offset] for lvl, title, pno in
               [(e[0], e[1], e[2]) for e in doc.get_toc()]]
    if shifted:
        out.set_toc(shifted)
    target = save_pdf(out, ctx.derive("with-contents"))
    out.close(); toc_doc.close(); doc.close()
    ctx.log(f"Contents page lists {len(entries)} entr(ies).")
    return ctx.done(target)


@tool(id="repair", name="Repair a damaged PDF", category="utility",
      summary="Rebuild the file structure to recover what can be read. "
              "Tries several strategies and keeps the best result.",
      params=[P("aggressive", "Try harder (rebuild page by page)", "bool",
                True),
              P("rasterise", "Last resort: rebuild pages as images", "bool",
                False),
              P("dpi", "Raster resolution", "int", 150, lo=72, hi=400,
                suffix=" dpi", when=("rasterise", (True,))), PW])
def repair(ctx):
    target = ctx.derive("repaired")
    tried = []

    # 1. qpdf, if available, is the best structural repairer
    if deps.have("qpdf"):
        try:
            tmp = ctx.tmp / "qpdf.pdf"
            deps.run([deps.find("qpdf"), "--decrypt",
                      "--object-streams=generate",
                      str(ctx.src), str(tmp)], timeout=300)
            if tmp.exists() and tmp.stat().st_size > 0:
                tried.append(("qpdf", tmp))
        except ToolError as e:
            ctx.log(f"qpdf could not fix it: {e}")
    ctx.progress(0.3, "Rebuilding")

    # 2. PyMuPDF's own clean/garbage-collect pass
    try:
        doc = fitz.open(ctx.src)
        if doc.needs_pass:
            doc.authenticate(ctx.p["password"] or "")
        tmp = ctx.tmp / "mupdf.pdf"
        doc.save(str(tmp), garbage=4, clean=True, deflate=True)
        pages = doc.page_count
        doc.close()
        tried.append(("built-in rebuild", tmp))
        ctx.log(f"Built-in rebuild read {pages} page(s).")
    except Exception as e:
        ctx.log(f"Built-in rebuild failed: {e}")

    # 3. page-by-page salvage
    if ctx.p["aggressive"]:
        ctx.progress(0.6, "Salvaging pages one by one")
        try:
            src = fitz.open(ctx.src)
            if src.needs_pass:
                src.authenticate(ctx.p["password"] or "")
            out = fitz.open()
            good = 0
            for i in range(src.page_count):
                try:
                    out.insert_pdf(src, from_page=i, to_page=i)
                    good += 1
                except Exception:
                    continue
            if good:
                tmp = ctx.tmp / "salvage.pdf"
                out.save(str(tmp), garbage=4, clean=True)
                tried.append((f"page salvage ({good} pages)", tmp))
            out.close(); src.close()
        except Exception as e:
            ctx.log(f"Page salvage failed: {e}")

    if ctx.p["rasterise"]:
        ctx.progress(0.8, "Rasterising")
        try:
            src = fitz.open(ctx.src)
            if src.needs_pass:
                src.authenticate(ctx.p["password"] or "")
            out = fitz.open()
            for i in range(src.page_count):
                try:
                    pix = src[i].get_pixmap(dpi=int(ctx.p["dpi"]))
                    page = out.new_page(width=src[i].rect.width,
                                        height=src[i].rect.height)
                    page.insert_image(page.rect, pixmap=pix)
                except Exception:
                    continue
            if out.page_count:
                tmp = ctx.tmp / "raster.pdf"
                out.save(str(tmp))
                tried.append(("rasterised", tmp))
            out.close(); src.close()
        except Exception as e:
            ctx.log(f"Rasterising failed: {e}")

    if not tried:
        raise ToolError("This file could not be recovered - no readable page "
                        "data was found.")

    def score(item):
        label, path = item
        try:
            d = fitz.open(path)
            n = d.page_count
            chars = sum(len(d[i].get_text("text")) for i in range(min(n, 25)))
            d.close()
            return (n, chars)
        except Exception:
            return (0, 0)

    best_label, best_path = max(tried, key=score)
    target.write_bytes(Path(best_path).read_bytes())
    pages, chars = score((best_label, best_path))
    ctx.log(f"Best result: {best_label} - {pages} page(s), {chars} characters "
            f"of text recovered.")
    return ctx.done(target)


@tool(id="compare", name="Compare two PDFs", category="utility", inputs="pdf+",
      batchable=False, view="compare",
      summary="Side-by-side visual comparison with differences highlighted, "
              "plus a text-level diff.")
def compare(ctx):
    raise ToolError("This tool runs in the comparison panel.")


@tool(id="compare_report", name="Compare two PDFs (report)",
      category="utility", inputs="pdf+", batchable=False,
      summary="Generate a PDF showing both documents page by page with the "
              "changed areas highlighted.",
      params=[P("dpi", "Comparison resolution", "int", 120, lo=72, hi=300,
                suffix=" dpi"),
              P("sensitivity", "Sensitivity", "int", 24, lo=1, hi=120,
                help="Lower values flag smaller differences"),
              P("layout", "Report layout", "choice", "side by side",
                choices=("side by side", "overlay", "difference only")),
              P("text_diff", "Also write a text diff", "bool", True), PW])
def compare_report(ctx):
    import difflib

    import numpy as np
    from PIL import Image, ImageChops
    if len(ctx.inputs) < 2:
        raise ToolError("Select exactly two PDFs to compare.")
    a_path, b_path = ctx.inputs[0], ctx.inputs[1]
    a = open_pdf(a_path, ctx.p["password"])
    b = open_pdf(b_path, ctx.p["password"])
    dpi = int(ctx.p["dpi"])
    thresh = int(ctx.p["sensitivity"])
    n = max(a.page_count, b.page_count)
    out = fitz.open()
    changed_pages = []

    def render(doc, i):
        if i >= doc.page_count:
            return None
        pix = doc[i].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB" if pix.n >= 3 else "L",
                               (pix.width, pix.height), pix.samples).convert("RGB")

    for i in range(n):
        ctx.progress((i + 1) / n, f"Page {i+1} of {n}")
        ia, ib = render(a, i), render(b, i)
        if ia is None or ib is None:
            changed_pages.append(i + 1)
        if ia is None:
            ia = Image.new("RGB", ib.size, (245, 245, 245))
        if ib is None:
            ib = Image.new("RGB", ia.size, (245, 245, 245))
        if ia.size != ib.size:
            ib = ib.resize(ia.size)
        diff = ImageChops.difference(ia, ib).convert("L")
        mask = np.array(diff) > thresh
        if mask.any():
            changed_pages.append(i + 1)
        marked_a, marked_b = ia.copy(), ib.copy()
        if mask.any():
            overlay = np.array(marked_b)
            overlay[mask] = (0.45 * overlay[mask] +
                             0.55 * np.array([255, 60, 60])).astype("uint8")
            marked_b = Image.fromarray(overlay)
            overlay_a = np.array(marked_a)
            overlay_a[mask] = (0.45 * overlay_a[mask] +
                               0.55 * np.array([60, 140, 255])).astype("uint8")
            marked_a = Image.fromarray(overlay_a)

        if ctx.p["layout"] == "difference only":
            sheet = Image.fromarray(
                (255 - np.array(diff.convert("L"))).astype("uint8")).convert("RGB")
        elif ctx.p["layout"] == "overlay":
            sheet = Image.blend(marked_a, marked_b, 0.5)
        else:
            gap = 24
            sheet = Image.new("RGB", (ia.width * 2 + gap,
                                      max(ia.height, ib.height) + 40),
                              (255, 255, 255))
            sheet.paste(marked_a, (0, 40))
            sheet.paste(marked_b, (ia.width + gap, 40))
        import io
        buf = io.BytesIO()
        sheet.save(buf, "JPEG", quality=85)
        pw = sheet.width * 72 / dpi
        ph = sheet.height * 72 / dpi
        page = out.new_page(width=pw, height=ph)
        page.insert_image(page.rect, stream=buf.getvalue())
        head = (f"Page {i+1}   left: {a_path.name}   right: {b_path.name}"
                if ctx.p["layout"] == "side by side"
                else f"Page {i+1}   {a_path.name} vs {b_path.name}")
        page.insert_text((12, 20), head, fontsize=9, fontname="helv",
                         color=(0.2, 0.2, 0.2))
    made = []
    target = save_pdf(out, ctx.out(f"compare-{a_path.stem}-vs-{b_path.stem}.pdf"))
    made.append(target)
    out.close()

    if ctx.p["text_diff"]:
        ta = [a[i].get_text("text") for i in range(a.page_count)]
        tb = [b[i].get_text("text") for i in range(b.page_count)]
        diff_lines = list(difflib.unified_diff(
            "\n".join(ta).splitlines(), "\n".join(tb).splitlines(),
            fromfile=a_path.name, tofile=b_path.name, lineterm="", n=2))
        tp = ctx.out("compare-text-diff.txt")
        tp.write_text("\n".join(diff_lines) or "The text content is identical.",
                      encoding="utf-8")
        made.append(tp)
    a.close(); b.close()
    uniq = sorted(set(changed_pages))
    ctx.log(f"{len(uniq)} page(s) differ: "
            f"{', '.join(map(str, uniq[:25]))}" if uniq
            else "The two documents render identically.")
    return ctx.done(*made)


@tool(id="print_pdf", name="Print", category="utility",
      summary="Send the document to a printer using the system print dialog.",
      params=[P("note", "How it works", "str",
                "Opens your desktop print dialog", help="")])
def print_pdf(ctx):
    raise ToolError("Use the Print button in the viewer panel, or the Print "
                    "action on a finished file.")


@tool(id="save_pages", name="Download individual pages", category="utility",
      summary="Save chosen pages as separate files, as PDFs or images.",
      params=[P("pages", "Pages", "pages", "1"),
              P("as", "Save as", "choice", "PDF",
                choices=("PDF", "PNG", "JPEG")),
              P("dpi", "Resolution", "int", 200, lo=72, hi=600, suffix=" dpi",
                when=("as", ("PNG", "JPEG"))),
              P("zip", "Bundle as ZIP", "bool", False), PW])
def save_pages(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count, default_all=False)
    made = []
    for n, i in enumerate(idxs, 1):
        ctx.progress(n / len(idxs), f"Page {i+1}")
        if ctx.p["as"] == "PDF":
            part = fitz.open()
            part.insert_pdf(doc, from_page=i, to_page=i)
            made.append(save_pdf(part, ctx.derive(f"page{i+1:04d}")))
            part.close()
        else:
            pix = doc[i].get_pixmap(dpi=int(ctx.p["dpi"]))
            ext = ".png" if ctx.p["as"] == "PNG" else ".jpg"
            out = ctx.derive(f"page{i+1:04d}", ext)
            if ext == ".png":
                pix.save(str(out))
            else:
                from PIL import Image
                Image.frombytes("RGB" if pix.n >= 3 else "L",
                                (pix.width, pix.height),
                                pix.samples).save(str(out), "JPEG", quality=92)
            made.append(out)
    doc.close()
    if ctx.p["zip"]:
        made.append(ctx.zip_up(made, ctx.src.stem + "-pages"))
    return ctx.done(*made)
