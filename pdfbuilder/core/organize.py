"""Category 1 - page organisation."""
from __future__ import annotations

import pymupdf as fitz

from pdfbuilder.core.common import (PAGE_SIZES, fmt_pages, new_doc_from,
                                    open_pdf, parse_pages, require_pdfs,
                                    save_pdf)
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Password (if protected)", "str", "")
PAGES = P("pages", "Pages", "pages", "all",
          help="e.g. 1-3,7,9-  ·  all / odd / even / last")


@tool(id="merge", name="Merge PDFs into one", category="organize",
      inputs="pdf+", batchable=False,
      summary="Join every selected PDF, in list order, into a single document.",
      params=[P("outname", "Output file name", "str", "merged.pdf"),
              P("bookmarks", "Add a bookmark per source file", "bool", True),
              P("keep_toc", "Keep each file's own bookmarks", "bool", True),
              PW])
def merge(ctx):
    srcs = require_pdfs(ctx, 2)
    out = fitz.open()
    toc = []
    for n, path in enumerate(srcs, 1):
        ctx.progress(n / (len(srcs) + 1), f"Adding {path.name}")
        doc = open_pdf(path, ctx.p["password"])
        start = out.page_count + 1
        if ctx.p["keep_toc"]:
            for lvl, title, pg, *_ in doc.get_toc():
                toc.append([lvl + (1 if ctx.p["bookmarks"] else 0),
                            title, start + max(0, pg - 1)])
        out.insert_pdf(doc)
        if ctx.p["bookmarks"]:
            toc.append([1, path.stem, start])
        doc.close()
    toc.sort(key=lambda e: (e[2], e[0]))
    if toc:
        out.set_toc(toc)
    name = ctx.p["outname"].strip() or "merged.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    target = save_pdf(out, ctx.out(name))
    out.close()
    ctx.log(f"Merged {len(srcs)} files.")
    return ctx.done(target)


@tool(id="split_ranges", name="Split by page ranges", category="organize",
      summary="Each range becomes its own PDF. One range per line.",
      params=[P("ranges", "Ranges (one per line)", "text", "1-3\n4-6",
                help="Each line is a separate output file, e.g. '1-3'"),
              P("zip", "Also bundle the results as a ZIP", "bool", False),
              PW])
def split_ranges(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    lines = [l.strip() for l in str(ctx.p["ranges"]).splitlines() if l.strip()]
    if not lines:
        raise ToolError("Enter at least one page range.")
    made = []
    for n, line in enumerate(lines, 1):
        ctx.progress(n / len(lines), f"Range {line}")
        idxs = parse_pages(line, doc.page_count)
        part = new_doc_from(doc, idxs)
        made.append(save_pdf(part, ctx.derive(f"p{fmt_pages(idxs)}")))
        part.close()
    doc.close()
    if ctx.p["zip"]:
        made.append(ctx.zip_up(made, ctx.src.stem + "-split"))
    return ctx.done(*made)


@tool(id="split_every", name="Split into equal page groups", category="organize",
      summary="Cut the document into chunks of N pages each.",
      params=[P("size", "Pages per file", "int", 1, lo=1, hi=5000),
              P("zip", "Bundle the results as a ZIP", "bool", False), PW])
def split_every(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    size = max(1, int(ctx.p["size"]))
    made = []
    groups = list(range(0, doc.page_count, size))
    for n, start in enumerate(groups, 1):
        ctx.progress(n / len(groups), f"Part {n}/{len(groups)}")
        idxs = list(range(start, min(start + size, doc.page_count)))
        part = new_doc_from(doc, idxs)
        made.append(save_pdf(part, ctx.derive(f"part{n:03d}")))
        part.close()
    doc.close()
    if ctx.p["zip"]:
        made.append(ctx.zip_up(made, ctx.src.stem + "-parts"))
    ctx.log(f"Created {len(groups)} files of up to {size} page(s).")
    return ctx.done(*made)


@tool(id="split_single", name="Split into one file per page", category="organize",
      summary="Every page is saved as its own PDF.",
      params=[P("zip", "Bundle the results as a ZIP", "bool", True), PW])
def split_single(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    made = []
    for i in range(doc.page_count):
        ctx.progress((i + 1) / doc.page_count, f"Page {i+1}")
        part = new_doc_from(doc, [i])
        made.append(save_pdf(part, ctx.derive(f"page{i+1:04d}")))
        part.close()
    doc.close()
    if ctx.p["zip"]:
        made.append(ctx.zip_up(made, ctx.src.stem + "-pages"))
    return ctx.done(*made)


@tool(id="extract", name="Extract selected pages", category="organize",
      summary="Keep only the pages you list, as one new PDF.",
      params=[PAGES,
              P("separate", "One file per extracted page", "bool", False), PW])
def extract(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count, default_all=False)
    made = []
    if ctx.p["separate"]:
        for i in idxs:
            part = new_doc_from(doc, [i])
            made.append(save_pdf(part, ctx.derive(f"page{i+1:04d}")))
            part.close()
    else:
        part = new_doc_from(doc, idxs)
        made.append(save_pdf(part, ctx.derive(f"pages-{fmt_pages(idxs)}")))
        part.close()
    doc.close()
    ctx.log(f"Extracted page(s) {fmt_pages(idxs)}.")
    return ctx.done(*made)


@tool(id="delete_pages", name="Delete selected pages", category="organize",
      summary="Remove the listed pages and keep everything else.",
      params=[P("pages", "Pages to delete", "pages", "1"), PW])
def delete_pages(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count, default_all=False)
    keep = [i for i in range(doc.page_count) if i not in set(idxs)]
    if not keep:
        raise ToolError("That would delete every page.")
    out = new_doc_from(doc, keep)
    target = save_pdf(out, ctx.derive("trimmed"))
    out.close(); doc.close()
    ctx.log(f"Deleted page(s) {fmt_pages(idxs)}; {len(keep)} remain.")
    return ctx.done(target)


@tool(id="reorder", name="Reorder pages", category="organize",
      summary="Give the new page order explicitly, e.g. '3,1,2,4-'.",
      params=[P("order", "New order", "pages", "",
                help="Pages not listed are appended in their current order "
                     "unless 'drop the rest' is ticked."),
              P("drop", "Drop pages not listed", "bool", False), PW])
def reorder(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    order = parse_pages(ctx.p["order"], doc.page_count, default_all=False)
    if not ctx.p["drop"]:
        order += [i for i in range(doc.page_count) if i not in set(order)]
    out = new_doc_from(doc, order)
    target = save_pdf(out, ctx.derive("reordered"))
    out.close(); doc.close()
    return ctx.done(target)


@tool(id="rotate", name="Rotate pages", category="organize",
      summary="Rotate every page, or only the ones you list.",
      params=[P("angle", "Rotation", "choice", "90",
                choices=("90", "180", "270", "-90")),
              P("pages", "Pages", "pages", "all"),
              P("absolute", "Set an absolute angle", "bool", False,
                help="Ignore each page's current rotation"), PW])
def rotate(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    ang = int(ctx.p["angle"])
    for n, i in enumerate(idxs, 1):
        pg = doc[i]
        pg.set_rotation(ang % 360 if ctx.p["absolute"]
                        else (pg.rotation + ang) % 360)
        ctx.progress(n / len(idxs))
    target = save_pdf(doc, ctx.derive("rotated"))
    doc.close()
    ctx.log(f"Rotated {len(idxs)} page(s) by {ang}deg.")
    return ctx.done(target)


@tool(id="duplicate", name="Duplicate pages", category="organize",
      summary="Repeat the chosen pages a number of times.",
      params=[PAGES, P("times", "Copies of each page", "int", 1, lo=1, hi=100),
              P("where", "Place copies", "choice", "after each page",
                choices=("after each page", "at the end", "at the start")), PW])
def duplicate(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = set(parse_pages(ctx.p["pages"], doc.page_count))
    times, where = int(ctx.p["times"]), ctx.p["where"]
    order = []
    extra = []
    for i in range(doc.page_count):
        order.append(i)
        if i in idxs:
            if where == "after each page":
                order.extend([i] * times)
            else:
                extra.extend([i] * times)
    order = extra + order if where == "at the start" else order + extra
    out = new_doc_from(doc, order)
    target = save_pdf(out, ctx.derive("duplicated"))
    out.close(); doc.close()
    return ctx.done(target)


@tool(id="reverse", name="Reverse page order", category="organize",
      summary="Last page first.", params=[PW])
def reverse(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    out = new_doc_from(doc, range(doc.page_count - 1, -1, -1))
    target = save_pdf(out, ctx.derive("reversed"))
    out.close(); doc.close()
    return ctx.done(target)


@tool(id="blank_pages", name="Add blank pages", category="organize",
      summary="Insert empty pages, matching the document size by default.",
      params=[P("count", "How many", "int", 1, lo=1, hi=1000),
              P("at", "Insert", "choice", "at the end",
                choices=("at the end", "at the start", "after page",
                         "after every page")),
              P("after", "After page number", "int", 1, lo=1,
                when=("at", ("after page",))),
              P("size", "Page size", "choice", "match document",
                choices=("match document",) + tuple(PAGE_SIZES)),
              P("landscape", "Landscape", "bool", False,
                when=("size", tuple(PAGE_SIZES))), PW])
def blank_pages(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    count, at = int(ctx.p["count"]), ctx.p["at"]

    def dims(ref_i):
        if ctx.p["size"] in PAGE_SIZES:
            w, h = PAGE_SIZES[ctx.p["size"]]
            return (h, w) if ctx.p["landscape"] else (w, h)
        r = doc[max(0, min(ref_i, doc.page_count - 1))].rect
        return r.width, r.height

    if at == "after every page":
        targets = list(range(doc.page_count - 1, -1, -1))
        for i in targets:
            w, h = dims(i)
            for _ in range(count):
                doc.new_page(pno=i + 1, width=w, height=h)
    else:
        pos = {"at the end": doc.page_count, "at the start": 0,
               "after page": int(ctx.p["after"])}[at]
        pos = max(0, min(pos, doc.page_count))
        w, h = dims(pos - 1 if pos else 0)
        for _ in range(count):
            doc.new_page(pno=pos, width=w, height=h)
    target = save_pdf(doc, ctx.derive("with-blanks"))
    doc.close()
    return ctx.done(target)


@tool(id="insert_pdf", name="Insert pages from another PDF", category="organize",
      summary="Splice pages of a second PDF into this one.",
      params=[P("other", "PDF to insert", "file", "",
                help="Choose the document whose pages you want to insert"),
              P("other_pages", "Pages from that file", "pages", "all"),
              P("at", "Insert", "choice", "at the end",
                choices=("at the end", "at the start", "after page")),
              P("after", "After page number", "int", 1, lo=1,
                when=("at", ("after page",))),
              P("other_password", "That file's password", "str", ""), PW])
def insert_pdf(ctx):
    other_path = str(ctx.p["other"] or "").strip()
    if not other_path:
        raise ToolError("Choose the PDF whose pages should be inserted.")
    doc = open_pdf(ctx.src, ctx.p["password"])
    src = open_pdf(other_path, ctx.p["other_password"])
    idxs = parse_pages(ctx.p["other_pages"], src.page_count)
    at = ctx.p["at"]
    pos = {"at the end": doc.page_count, "at the start": 0,
           "after page": int(ctx.p["after"])}[at]
    pos = max(0, min(pos, doc.page_count))
    for n, i in enumerate(idxs):
        doc.insert_pdf(src, from_page=i, to_page=i, start_at=pos + n)
        ctx.progress((n + 1) / len(idxs))
    target = save_pdf(doc, ctx.derive("combined"))
    doc.close(); src.close()
    ctx.log(f"Inserted {len(idxs)} page(s) at position {pos+1}.")
    return ctx.done(target)


@tool(id="organize_visual", name="Organize with page thumbnails",
      category="organize", view="organizer",
      summary="Drag to reorder, rotate, duplicate or delete pages visually, "
              "then export the result.")
def organize_visual(ctx):
    raise ToolError("This tool runs in its own visual panel.")


@tool(id="export_selection", name="Export chosen pages as new PDF",
      category="organize", view="organizer",
      summary="Pick pages in the thumbnail grid and export just those.")
def export_selection(ctx):
    raise ToolError("This tool runs in its own visual panel.")
