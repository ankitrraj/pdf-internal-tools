"""Category 2 - compression and optimisation."""
from __future__ import annotations

import io
from pathlib import Path

from pdfbuilder import deps
from pdfbuilder.core.common import human_size, open_pdf, save_pdf
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Password (if protected)", "str", "")

# level -> (jpeg quality, max image pixel edge, ghostscript preset)
LEVELS = {
    "low (best quality)":    (88, 2400, "/prepress"),
    "medium (recommended)": (72, 1600, "/ebook"),
    "high (smallest file)":  (55, 1000, "/screen"),
}


def _shrink_images(doc, quality: int, max_edge: int, ctx) -> int:
    """Recompress embedded raster images in place. Returns bytes saved."""
    from PIL import Image

    saved = 0
    xrefs = {}
    for pno in range(doc.page_count):
        for info in doc.get_page_images(pno, full=True):
            xrefs.setdefault(info[0], info)
    total = max(1, len(xrefs))
    for n, xref in enumerate(sorted(xrefs), 1):
        ctx.progress(0.1 + 0.6 * n / total, f"Image {n}/{total}")
        try:
            raw = doc.extract_image(xref)
        except Exception:
            continue
        if not raw or not raw.get("image"):
            continue
        before = len(raw["image"])
        if before < 12_000:
            continue
        try:
            img = Image.open(io.BytesIO(raw["image"]))
            img.load()
        except Exception:
            continue
        has_alpha = img.mode in ("RGBA", "LA", "P") and "transparency" in img.info
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGBA" if has_alpha else "RGB")
        w, h = img.size
        if max(w, h) > max_edge:
            s = max_edge / max(w, h)
            img = img.resize((max(1, int(w * s)), max(1, int(h * s))),
                             Image.LANCZOS)
        buf = io.BytesIO()
        if has_alpha:
            img.save(buf, "PNG", optimize=True)
        else:
            img.convert("RGB").save(buf, "JPEG", quality=quality,
                                    optimize=True, progressive=True)
        data = buf.getvalue()
        if len(data) < before * 0.92:
            try:
                _replace_image(doc, xref, data)
                saved += before - len(data)
            except Exception:
                continue
    return saved


def _replace_image(doc, xref, data):
    """Swap an image XObject's stream and matching filter/metadata."""
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    is_jpeg = (img.format == "JPEG")
    doc.xref_set_key(xref, "Width", str(img.width))
    doc.xref_set_key(xref, "Height", str(img.height))
    doc.xref_set_key(xref, "BitsPerComponent", "8")
    doc.xref_set_key(xref, "ColorSpace",
                     "/DeviceGray" if img.mode == "L" else "/DeviceRGB")
    for key in ("SMask", "Mask", "Decode", "DecodeParms", "Interpolate"):
        try:
            doc.xref_set_key(xref, key, "null")
        except Exception:
            pass
    if is_jpeg:
        doc.xref_set_key(xref, "Filter", "/DCTDecode")
        doc.update_stream(xref, data, new=True, compress=False)
    else:
        rgb = img.convert("RGBA" if img.mode in ("RGBA", "LA") else "RGB")
        doc.xref_set_key(xref, "Filter", "null")
        doc.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
        if rgb.mode == "RGBA":
            rgb = rgb.convert("RGB")
        doc.update_stream(xref, rgb.tobytes(), new=True, compress=True)


def _gs_compress(src: Path, dst: Path, preset: str, dpi: int, web: bool):
    gs = deps.require("ghostscript")
    cmd = [gs, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.7",
           f"-dPDFSETTINGS={preset}", "-dNOPAUSE", "-dQUIET", "-dBATCH",
           "-dDetectDuplicateImages=true", "-dCompressFonts=true",
           "-dSubsetFonts=true",
           "-dColorImageDownsampleType=/Bicubic", f"-dColorImageResolution={dpi}",
           "-dGrayImageDownsampleType=/Bicubic", f"-dGrayImageResolution={dpi}",
           "-dMonoImageDownsampleType=/Subsample",
           f"-dMonoImageResolution={max(dpi, 300)}"]
    if web:
        cmd.append("-dFastWebView=true")
    cmd += [f"-sOutputFile={dst}", str(src)]
    deps.run(cmd, timeout=900)


@tool(id="compress", name="Compress PDF", category="compress",
      summary="Shrink the file. Reports the before/after size and how much "
              "was saved.",
      params=[P("level", "Compression level", "choice", "medium (recommended)",
                choices=tuple(LEVELS)),
              P("engine", "Engine", "choice", "automatic",
                choices=("automatic", "Ghostscript (strongest)",
                         "built-in (no extra software)")),
              P("dpi", "Image resolution limit", "int", 150, lo=36, hi=600,
                suffix=" dpi"),
              P("web", "Optimise for web viewing (linearise)", "bool", True),
              P("drop_unused", "Remove unused objects", "bool", True),
              P("dedupe", "Merge duplicate resources", "bool", True),
              P("keep_quality", "Never grow the file", "bool", True,
                help="If compression would not help, the original is kept"),
              PW])
def compress(ctx):
    src = ctx.src
    before = src.stat().st_size
    quality, max_edge, preset = LEVELS[ctx.p["level"]]
    engine = ctx.p["engine"]
    target = ctx.derive("compressed")
    dpi = int(ctx.p["dpi"])
    max_edge = int(max_edge * dpi / 150) or max_edge

    use_gs = engine.startswith("Ghostscript") or (
        engine == "automatic" and deps.have("ghostscript"))
    ctx.progress(0.05, "Reading")

    cands: list[Path] = []
    if use_gs:
        try:
            gs_out = ctx.tmp / "gs.pdf"
            _gs_compress(src, gs_out, preset, dpi, bool(ctx.p["web"]))
            cands.append(gs_out)
            ctx.progress(0.55, "Ghostscript pass complete")
        except ToolError as e:
            if engine.startswith("Ghostscript"):
                raise
            ctx.log(f"Ghostscript unavailable, using built-in engine. ({e})")

    if not cands or engine == "built-in (no extra software)":
        doc = open_pdf(src, ctx.p["password"])
        _shrink_images(doc, quality, max_edge, ctx)
        ctx.progress(0.8, "Rebuilding file")
        own = ctx.tmp / "own.pdf"
        save_pdf(doc, own,
                 garbage=4 if ctx.p["drop_unused"] else 1,
                 clean=True, deflate=True,
                 deflate_images=True, deflate_fonts=True,
                 linear=bool(ctx.p["web"]))
        doc.close()
        cands.append(own)

    best = min(cands, key=lambda p: p.stat().st_size)
    after = best.stat().st_size
    if ctx.p["keep_quality"] and after >= before:
        ctx.log("Compression would not reduce this file; kept the original.")
        best, after = src, before
    target.write_bytes(Path(best).read_bytes())

    pct = (1 - after / before) * 100 if before else 0
    ctx.log(f"Original: {human_size(before)}   "
            f"Compressed: {human_size(after)}   "
            f"Saved: {pct:.1f}%")
    ctx.summary = {"Original size": human_size(before),
                   "New size": human_size(after),
                   "Reduction": f"{pct:.1f}%"}
    return ctx.done(target)


@tool(id="downsample", name="Reduce embedded image resolution",
      category="compress",
      summary="Resample pictures inside the PDF without touching the text.",
      params=[P("dpi", "Target resolution", "int", 120, lo=36, hi=600,
                suffix=" dpi"),
              P("quality", "JPEG quality", "int", 70, lo=20, hi=98),
              P("gray", "Convert images to greyscale", "bool", False), PW])
def downsample(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    before = ctx.src.stat().st_size
    edge = int(ctx.p["dpi"] * 11)      # ~letter page long edge in pixels
    if ctx.p["gray"]:
        _grayscale_images(doc, ctx)
    _shrink_images(doc, int(ctx.p["quality"]), edge, ctx)
    target = save_pdf(doc, ctx.derive("downsampled"), garbage=4,
                      deflate_images=True)
    doc.close()
    ctx.log(f"{human_size(before)} -> {human_size(target.stat().st_size)}")
    return ctx.done(target)


def _grayscale_images(doc, ctx):
    from PIL import Image
    seen = set()
    for pno in range(doc.page_count):
        for info in doc.get_page_images(pno, full=True):
            xref = info[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                raw = doc.extract_image(xref)
                img = Image.open(io.BytesIO(raw["image"])).convert("L")
                buf = io.BytesIO()
                img.save(buf, "JPEG", quality=80, optimize=True)
                _replace_image(doc, xref, buf.getvalue())
            except Exception:
                continue


@tool(id="clean_objects", name="Remove unused & duplicate objects",
      category="compress",
      summary="Garbage-collect orphaned objects and merge identical "
              "resources such as repeated fonts or logos.",
      params=[P("dedupe", "Merge duplicate resources", "bool", True),
              P("drop_unused", "Remove unused objects", "bool", True),
              P("flate", "Recompress all streams", "bool", True), PW])
def clean_objects(ctx):
    before = ctx.src.stat().st_size
    doc = open_pdf(ctx.src, ctx.p["password"])
    ctx.progress(0.4, "Collecting")
    garbage = 4 if (ctx.p["dedupe"] and ctx.p["drop_unused"]) else \
              3 if ctx.p["drop_unused"] else 1
    target = save_pdf(doc, ctx.derive("cleaned"), garbage=garbage, clean=True,
                      deflate=bool(ctx.p["flate"]),
                      deflate_images=bool(ctx.p["flate"]),
                      deflate_fonts=bool(ctx.p["flate"]))
    doc.close()
    after = target.stat().st_size
    ctx.log(f"{human_size(before)} -> {human_size(after)} "
            f"({(1-after/before)*100:.1f}% smaller)" if before else "")
    return ctx.done(target)


@tool(id="linearize", name="Optimise for web viewing", category="compress",
      summary="Linearise the file so a browser can show page 1 before the "
              "whole document has downloaded.",
      params=[P("compress_streams", "Recompress streams too", "bool", True),
              PW])
def linearize(ctx):
    import pikepdf
    target = ctx.derive("web")
    try:
        with pikepdf.open(str(ctx.src), password=ctx.p["password"] or "") as pdf:
            ctx.progress(0.5, "Linearising")
            pdf.save(str(target), linearize=True,
                     compress_streams=bool(ctx.p["compress_streams"]),
                     object_stream_mode=pikepdf.ObjectStreamMode.generate)
    except Exception:
        doc = open_pdf(ctx.src, ctx.p["password"])
        save_pdf(doc, target, garbage=3, linear=True)
        doc.close()
    ctx.log("Saved as a linearised (fast web view) PDF.")
    return ctx.done(target)


@tool(id="size_report", name="Compare file sizes", category="compress",
      inputs="pdf+", batchable=False,
      summary="Show the size, page count and estimated savings for every "
              "selected PDF without changing anything.",
      params=[PW])
def size_report(ctx):
    rows = []
    for p in ctx.inputs:
        try:
            doc = open_pdf(p, ctx.p["password"])
            pages = doc.page_count
            imgs = sum(len(doc.get_page_images(i)) for i in range(pages))
            doc.close()
        except ToolError:
            pages = imgs = 0
        size = Path(p).stat().st_size
        rows.append((Path(p).name, size, pages, imgs))
    ctx.summary = {n: f"{human_size(s)}  ·  {pg} page(s)  ·  {im} image(s)"
                   for n, s, pg, im in rows}
    total = sum(r[1] for r in rows)
    ctx.log(f"{len(rows)} file(s), {human_size(total)} in total.")
    return []
