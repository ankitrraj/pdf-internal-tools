"""Category 11 - image utilities (plus shared image loading)."""
from __future__ import annotations

from pathlib import Path

from pdfbuilder.core.common import human_size, require_images
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

_HEIF_READY = False


def _enable_heif():
    global _HEIF_READY
    if _HEIF_READY:
        return
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    _HEIF_READY = True


def load_image(path):
    """Open any supported image, normalising orientation and HEIC support."""
    from PIL import Image, ImageOps
    _enable_heif()
    try:
        img = Image.open(str(path))
        img.load()
    except Exception as e:
        raise ToolError(f"Could not read image {Path(path).name}: {e}") from e
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    return img


def save_image(img, path, *, quality=90, fmt=None):
    path = Path(path)
    fmt = fmt or {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG",
                  ".webp": "WEBP", ".tif": "TIFF", ".tiff": "TIFF",
                  ".bmp": "BMP"}.get(path.suffix.lower(), "PNG")
    if fmt in ("JPEG", "BMP") and img.mode in ("RGBA", "LA", "P"):
        bg = img.convert("RGBA")
        from PIL import Image
        flat = Image.new("RGB", bg.size, (255, 255, 255))
        flat.paste(bg, mask=bg.split()[-1])
        img = flat
    kw = {}
    if fmt == "JPEG":
        kw = dict(quality=int(quality), optimize=True, progressive=True)
    elif fmt == "WEBP":
        kw = dict(quality=int(quality), method=5)
    elif fmt == "PNG":
        kw = dict(optimize=True)
    img.save(str(path), fmt, **kw)
    return path


FMT_CHOICES = ("JPEG", "PNG", "WEBP", "TIFF", "BMP")
EXT_OF = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "TIFF": ".tif",
          "BMP": ".bmp"}


def _each(ctx, fn, tag, ext=None, quality=90):
    """Apply fn(PIL)->PIL over every selected image."""
    imgs = require_images(ctx)
    made = []
    for n, path in enumerate(imgs, 1):
        ctx.progress(n / len(imgs), Path(path).name)
        img = load_image(path)
        out = fn(img, path)
        if out is None:
            continue
        suffix = ext or Path(path).suffix or ".png"
        made.append(save_image(out, ctx.derive(tag, suffix, src=Path(path)),
                               quality=quality))
    return ctx.done(*made)


@tool(id="img_resize", name="Resize images", category="image", inputs="image+",
      batchable=False,
      summary="Scale by percentage, or fit within a width and height.",
      params=[P("mode", "Mode", "choice", "fit within box",
                choices=("fit within box", "percentage", "exact size",
                         "width only", "height only")),
              P("width", "Width", "int", 1920, lo=1, hi=30000, suffix=" px",
                when=("mode", ("fit within box", "exact size", "width only"))),
              P("height", "Height", "int", 1080, lo=1, hi=30000, suffix=" px",
                when=("mode", ("fit within box", "exact size", "height only"))),
              P("percent", "Scale", "float", 50, lo=1, hi=1000, suffix=" %",
                when=("mode", ("percentage",))),
              P("no_upscale", "Never enlarge", "bool", True),
              P("format", "Save as", "choice", "keep original",
                choices=("keep original",) + FMT_CHOICES),
              P("quality", "Quality", "int", 90, lo=20, hi=100)])
def img_resize(ctx):
    from PIL import Image
    mode = ctx.p["mode"]
    W, H = int(ctx.p["width"]), int(ctx.p["height"])

    def fn(img, path):
        w, h = img.size
        if mode == "percentage":
            s = float(ctx.p["percent"]) / 100
            nw, nh = max(1, int(w * s)), max(1, int(h * s))
        elif mode == "exact size":
            nw, nh = W, H
        elif mode == "width only":
            nw, nh = W, max(1, round(h * W / w))
        elif mode == "height only":
            nw, nh = max(1, round(w * H / h)), H
        else:
            s = min(W / w, H / h)
            if ctx.p["no_upscale"]:
                s = min(s, 1.0)
            nw, nh = max(1, int(w * s)), max(1, int(h * s))
        if ctx.p["no_upscale"] and mode != "exact size" and nw > w:
            nw, nh = w, h
        return img.resize((nw, nh), Image.LANCZOS)

    fmt = ctx.p["format"]
    ext = None if fmt == "keep original" else EXT_OF[fmt]
    return _each(ctx, fn, "resized", ext, int(ctx.p["quality"]))


@tool(id="img_compress", name="Compress images", category="image",
      inputs="image+", batchable=False,
      summary="Reduce file size, optionally capping the longest edge.",
      params=[P("quality", "Quality", "int", 72, lo=20, hi=98),
              P("max_edge", "Longest edge limit", "int", 2000, lo=100,
                hi=20000, suffix=" px"),
              P("format", "Save as", "choice", "JPEG",
                choices=("keep original",) + FMT_CHOICES),
              P("strip_exif", "Remove EXIF data", "bool", True)])
def img_compress(ctx):
    from PIL import Image
    imgs = require_images(ctx)
    made, saved_total, before_total = [], 0, 0
    fmt = ctx.p["format"]
    for n, path in enumerate(imgs, 1):
        ctx.progress(n / len(imgs), Path(path).name)
        before = Path(path).stat().st_size
        img = load_image(path)
        cap = int(ctx.p["max_edge"])
        if max(img.size) > cap:
            s = cap / max(img.size)
            img = img.resize((max(1, int(img.width * s)),
                             max(1, int(img.height * s))), Image.LANCZOS)
        if ctx.p["strip_exif"]:
            clean = Image.new(img.mode, img.size)
            clean.putdata(list(img.getdata()))
            img = clean
        ext = Path(path).suffix if fmt == "keep original" else EXT_OF[fmt]
        out = save_image(img, ctx.derive("compressed", ext, src=Path(path)),
                         quality=int(ctx.p["quality"]))
        made.append(out)
        before_total += before
        saved_total += max(0, before - out.stat().st_size)
    if before_total:
        ctx.log(f"{human_size(before_total)} -> "
                f"{human_size(before_total - saved_total)} "
                f"({saved_total / before_total * 100:.1f}% smaller)")
    return ctx.done(*made)


@tool(id="img_convert", name="Convert image format", category="image",
      inputs="image+", batchable=False,
      summary="Convert between JPG, PNG, WebP, TIFF, BMP and HEIC input.",
      params=[P("format", "Convert to", "choice", "PNG", choices=FMT_CHOICES),
              P("quality", "Quality", "int", 92, lo=20, hi=100),
              P("background", "Background for transparency", "color",
                "#ffffff")])
def img_convert(ctx):
    fmt = ctx.p["format"]

    def fn(img, path):
        if fmt in ("JPEG", "BMP") and img.mode in ("RGBA", "LA", "P"):
            from PIL import Image
            from pdfbuilder.core.common import parse_color
            rgb = tuple(int(c * 255) for c in parse_color(ctx.p["background"],
                                                          (1, 1, 1)))
            base = Image.new("RGB", img.size, rgb)
            conv = img.convert("RGBA")
            base.paste(conv, mask=conv.split()[-1])
            return base
        return img

    return _each(ctx, fn, fmt.lower(), EXT_OF[fmt], int(ctx.p["quality"]))


@tool(id="img_crop", name="Crop images", category="image", inputs="image+",
      batchable=False,
      summary="Crop by edge amounts, to a ratio, or to the image's own "
              "borders.",
      params=[P("mode", "Mode", "choice", "edges (px)",
                choices=("edges (px)", "edges (%)", "aspect ratio",
                         "trim uniform border")),
              P("left", "Left", "float", 0, lo=0, hi=20000,
                when=("mode", ("edges (px)", "edges (%)"))),
              P("right", "Right", "float", 0, lo=0, hi=20000,
                when=("mode", ("edges (px)", "edges (%)"))),
              P("top", "Top", "float", 0, lo=0, hi=20000,
                when=("mode", ("edges (px)", "edges (%)"))),
              P("bottom", "Bottom", "float", 0, lo=0, hi=20000,
                when=("mode", ("edges (px)", "edges (%)"))),
              P("ratio", "Ratio", "choice", "1:1",
                choices=("1:1", "4:3", "3:2", "16:9", "2:3", "3:4", "9:16"),
                when=("mode", ("aspect ratio",))),
              P("tolerance", "Border tolerance", "int", 12, lo=0, hi=120,
                when=("mode", ("trim uniform border",))),
              P("quality", "Quality", "int", 92, lo=20, hi=100)])
def img_crop(ctx):
    from PIL import Image, ImageChops
    mode = ctx.p["mode"]

    def fn(img, path):
        w, h = img.size
        if mode == "trim uniform border":
            ref = Image.new(img.mode, img.size, img.getpixel((0, 0)))
            diff = ImageChops.difference(img.convert("RGB"),
                                         ref.convert("RGB"))
            bbox = diff.point(lambda v: 255 if v > int(ctx.p["tolerance"])
                              else 0).convert("L").getbbox()
            return img.crop(bbox) if bbox else img
        if mode == "aspect ratio":
            rw, rh = (float(x) for x in ctx.p["ratio"].split(":"))
            target = rw / rh
            cur = w / h
            if cur > target:
                nw = int(h * target)
                x = (w - nw) // 2
                return img.crop((x, 0, x + nw, h))
            nh = int(w / target)
            y = (h - nh) // 2
            return img.crop((0, y, w, y + nh))
        vals = [float(ctx.p[k]) for k in ("left", "top", "right", "bottom")]
        if mode == "edges (%)":
            vals = [vals[0] * w / 100, vals[1] * h / 100,
                    vals[2] * w / 100, vals[3] * h / 100]
        box = (int(vals[0]), int(vals[1]), int(w - vals[2]), int(h - vals[3]))
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ToolError("Those crop values leave nothing of the image.")
        return img.crop(box)

    return _each(ctx, fn, "cropped", None, int(ctx.p["quality"]))


@tool(id="img_rotate", name="Rotate and flip images", category="image",
      inputs="image+", batchable=False,
      summary="Rotate by any angle and mirror horizontally or vertically.",
      params=[P("angle", "Rotate", "choice", "90",
                choices=("90", "180", "270", "custom")),
              P("custom", "Custom angle", "float", 0, lo=-360, hi=360,
                suffix=" deg", when=("angle", ("custom",))),
              P("flip_h", "Flip horizontally", "bool", False),
              P("flip_v", "Flip vertically", "bool", False),
              P("expand", "Expand canvas to fit", "bool", True),
              P("background", "Fill colour", "color", "#ffffff"),
              P("quality", "Quality", "int", 92, lo=20, hi=100)])
def img_rotate(ctx):
    from PIL import Image
    from pdfbuilder.core.common import parse_color

    def fn(img, path):
        if ctx.p["angle"] == "custom":
            ang = float(ctx.p["custom"])
            if ang:
                rgb = tuple(int(c * 255) for c in
                            parse_color(ctx.p["background"], (1, 1, 1)))
                img = img.convert("RGB").rotate(
                    -ang, resample=Image.BICUBIC,
                    expand=bool(ctx.p["expand"]), fillcolor=rgb)
        else:
            img = img.rotate(-int(ctx.p["angle"]), expand=True)
        if ctx.p["flip_h"]:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if ctx.p["flip_v"]:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        return img

    return _each(ctx, fn, "rotated", None, int(ctx.p["quality"]))


@tool(id="img_gray", name="Convert images to greyscale", category="image",
      inputs="image+", batchable=False,
      summary="Black-and-white conversion, with optional high-contrast "
              "document mode.",
      params=[P("mode", "Style", "choice", "greyscale",
                choices=("greyscale", "black & white (threshold)", "sepia")),
              P("threshold", "Threshold", "int", 160, lo=1, hi=254,
                when=("mode", ("black & white (threshold)",))),
              P("quality", "Quality", "int", 92, lo=20, hi=100)])
def img_gray(ctx):
    def fn(img, path):
        g = img.convert("L")
        if ctx.p["mode"] == "black & white (threshold)":
            t = int(ctx.p["threshold"])
            return g.point(lambda v: 255 if v > t else 0, mode="1").convert("L")
        if ctx.p["mode"] == "sepia":
            rgb = g.convert("RGB")
            px = rgb.load()
            for y in range(rgb.height):
                for x in range(rgb.width):
                    v = px[x, y][0]
                    px[x, y] = (min(255, int(v * 1.07)), int(v * 0.93),
                                int(v * 0.72))
            return rgb
        return g

    return _each(ctx, fn, "grey", None, int(ctx.p["quality"]))


@tool(id="img_adjust", name="Adjust brightness and contrast",
      category="image", inputs="image+", batchable=False,
      summary="Fine-tune exposure, contrast, saturation and sharpness.",
      params=[P("brightness", "Brightness", "float", 1.0, lo=0.1, hi=3,
                step=0.05),
              P("contrast", "Contrast", "float", 1.0, lo=0.1, hi=3, step=0.05),
              P("saturation", "Saturation", "float", 1.0, lo=0, hi=3,
                step=0.05),
              P("sharpness", "Sharpness", "float", 1.0, lo=0, hi=4, step=0.1),
              P("autolevel", "Auto-level first", "bool", False),
              P("quality", "Quality", "int", 92, lo=20, hi=100)])
def img_adjust(ctx):
    from PIL import ImageEnhance, ImageOps

    def fn(img, path):
        if ctx.p["autolevel"]:
            img = ImageOps.autocontrast(img.convert("RGB"), cutoff=1)
        for cls, key in ((ImageEnhance.Brightness, "brightness"),
                         (ImageEnhance.Contrast, "contrast"),
                         (ImageEnhance.Color, "saturation"),
                         (ImageEnhance.Sharpness, "sharpness")):
            v = float(ctx.p[key])
            if abs(v - 1.0) > 1e-6:
                img = cls(img.convert("RGB") if img.mode == "P" else img).enhance(v)
        return img

    return _each(ctx, fn, "adjusted", None, int(ctx.p["quality"]))


PASSPORT = {
    "India / UK 35x45 mm": (35, 45),
    "US 2x2 in (51x51 mm)": (50.8, 50.8),
    "Schengen 35x45 mm": (35, 45),
    "Canada 50x70 mm": (50, 70),
    "China 33x48 mm": (33, 48),
    "Custom": (35, 45),
}


@tool(id="img_passport", name="Create passport-size photos", category="image",
      inputs="image+", batchable=False,
      summary="Crop to an official size and lay out a printable sheet.",
      params=[P("spec", "Photo size", "choice", "India / UK 35x45 mm",
                choices=tuple(PASSPORT)),
              P("cw", "Custom width", "float", 35, lo=10, hi=200, suffix=" mm",
                when=("spec", ("Custom",))),
              P("chh", "Custom height", "float", 45, lo=10, hi=200,
                suffix=" mm", when=("spec", ("Custom",))),
              P("dpi", "Print resolution", "int", 300, lo=150, hi=1200,
                suffix=" dpi"),
              P("sheet", "Also build a print sheet", "choice", "4x6 inch",
                choices=("none", "4x6 inch", "A4")),
              P("copies", "Photos on the sheet", "int", 8, lo=1, hi=60),
              P("gap", "Gap between photos", "float", 2, lo=0, hi=20,
                suffix=" mm"),
              P("border", "White border around each photo", "float", 1, lo=0,
                hi=10, suffix=" mm"),
              P("pdf", "Save the sheet as PDF too", "bool", True)])
def img_passport(ctx):
    from PIL import Image
    imgs = require_images(ctx)
    dpi = int(ctx.p["dpi"])
    if ctx.p["spec"] == "Custom":
        mm_w, mm_h = float(ctx.p["cw"]), float(ctx.p["chh"])
    else:
        mm_w, mm_h = PASSPORT[ctx.p["spec"]]
    px = lambda mm: max(1, int(round(mm / 25.4 * dpi)))
    tw, th = px(mm_w), px(mm_h)
    bord = px(float(ctx.p["border"]))
    made = []
    for n, path in enumerate(imgs, 1):
        ctx.progress(n / len(imgs), Path(path).name)
        img = load_image(path).convert("RGB")
        s = max(tw / img.width, th / img.height)
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))),
                         Image.LANCZOS)
        x = (img.width - tw) // 2
        y = int((img.height - th) * 0.35)   # bias up: keep the head in frame
        y = max(0, min(y, img.height - th))
        one = img.crop((x, y, x + tw, y + th))
        if bord:
            framed = Image.new("RGB", (tw + 2 * bord, th + 2 * bord),
                               (255, 255, 255))
            framed.paste(one, (bord, bord))
            one = framed
        made.append(save_image(one, ctx.derive("passport", ".jpg",
                                               src=Path(path)), quality=96))
        if ctx.p["sheet"] != "none":
            sheet_mm = (152.4, 101.6) if ctx.p["sheet"] == "4x6 inch" else (210, 297)
            sw, sh = px(sheet_mm[0]), px(sheet_mm[1])
            gap = px(float(ctx.p["gap"]))
            sheet = Image.new("RGB", (sw, sh), (255, 255, 255))
            cols = max(1, (sw + gap) // (one.width + gap))
            rows = max(1, (sh + gap) // (one.height + gap))
            placed = 0
            for r in range(int(rows)):
                for c in range(int(cols)):
                    if placed >= int(ctx.p["copies"]):
                        break
                    sheet.paste(one, (int(c * (one.width + gap)),
                                      int(r * (one.height + gap))))
                    placed += 1
            sp = save_image(sheet, ctx.derive("passport-sheet", ".jpg",
                                              src=Path(path)), quality=96)
            made.append(sp)
            if ctx.p["pdf"]:
                pdf_path = ctx.derive("passport-sheet", ".pdf", src=Path(path))
                sheet.save(str(pdf_path), "PDF", resolution=dpi)
                made.append(pdf_path)
    ctx.log(f"Photo size {mm_w}x{mm_h} mm at {dpi} dpi.")
    return ctx.done(*made)


@tool(id="img_border", name="Add image borders", category="image",
      inputs="image+", batchable=False,
      summary="Add a solid border, and optionally rounded corners or a "
              "drop shadow.",
      params=[P("width", "Border width", "int", 20, lo=0, hi=500, suffix=" px"),
              P("color", "Border colour", "color", "#ffffff"),
              P("inner", "Inner hairline", "int", 0, lo=0, hi=50, suffix=" px"),
              P("inner_color", "Hairline colour", "color", "#222222"),
              P("radius", "Corner radius", "int", 0, lo=0, hi=400,
                suffix=" px"),
              P("quality", "Quality", "int", 92, lo=20, hi=100)])
def img_border(ctx):
    from PIL import Image, ImageDraw, ImageOps
    from pdfbuilder.core.common import parse_color
    rgb = lambda k: tuple(int(c * 255) for c in parse_color(ctx.p[k]))

    def fn(img, path):
        im = img.convert("RGB")
        if int(ctx.p["inner"]):
            im = ImageOps.expand(im, int(ctx.p["inner"]), rgb("inner_color"))
        w = int(ctx.p["width"])
        if w:
            im = ImageOps.expand(im, w, rgb("color"))
        r = int(ctx.p["radius"])
        if r:
            mask = Image.new("L", im.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, im.width - 1, im.height - 1], radius=r, fill=255)
            out = Image.new("RGBA", im.size, (0, 0, 0, 0))
            out.paste(im, mask=mask)
            return out
        return im

    ext = ".png" if int(ctx.p["radius"]) else None
    return _each(ctx, fn, "bordered", ext, int(ctx.p["quality"]))


@tool(id="qr_code", name="Generate a QR code", category="image",
      inputs="none", batchable=False,
      summary="Make a QR code to save as PNG, or stamp straight onto a PDF.",
      params=[P("data", "Text, URL or contact details", "text",
                "https://example.com"),
              P("size", "Image size", "int", 600, lo=80, hi=4000, suffix=" px"),
              P("ec", "Error correction", "choice", "medium (15%)",
                choices=("low (7%)", "medium (15%)", "quartile (25%)",
                         "high (30%)")),
              P("fg", "Foreground", "color", "#000000"),
              P("bg", "Background", "color", "#ffffff"),
              P("quiet", "Quiet border", "int", 4, lo=0, hi=20,
                suffix=" modules"),
              P("label", "Caption underneath", "str", ""),
              P("pdf", "Also save as PDF", "bool", False)])
def qr_code(ctx):
    try:
        import qrcode
        from qrcode.constants import (ERROR_CORRECT_H, ERROR_CORRECT_L,
                                      ERROR_CORRECT_M, ERROR_CORRECT_Q)
    except ImportError:
        raise ToolError("The 'qrcode' package is missing from the "
                        "environment. Reinstall with ./install.sh")
    from PIL import Image, ImageDraw
    from pdfbuilder.core.common import parse_color
    data = str(ctx.p["data"] or "").strip()
    if not data:
        raise ToolError("Enter the text or URL to encode.")
    ec = {"low (7%)": ERROR_CORRECT_L, "medium (15%)": ERROR_CORRECT_M,
          "quartile (25%)": ERROR_CORRECT_Q, "high (30%)": ERROR_CORRECT_H}[ctx.p["ec"]]
    rgb = lambda k: tuple(int(c * 255) for c in parse_color(ctx.p[k]))
    qr = qrcode.QRCode(error_correction=ec, box_size=10,
                       border=int(ctx.p["quiet"]))
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=rgb("fg"), back_color=rgb("bg")).convert("RGB")
    size = int(ctx.p["size"])
    img = img.resize((size, size), Image.NEAREST)
    label = str(ctx.p["label"] or "").strip()
    if label:
        pad = max(24, size // 10)
        canvas = Image.new("RGB", (size, size + pad), rgb("bg"))
        canvas.paste(img, (0, 0))
        d = ImageDraw.Draw(canvas)
        try:
            from PIL import ImageFont
            font = ImageFont.load_default(size=max(12, pad // 2))
        except Exception:
            font = None
        tw = d.textlength(label, font=font)
        d.text(((size - tw) / 2, size + pad * 0.15), label, fill=rgb("fg"),
               font=font)
        img = canvas
    made = [save_image(img, ctx.out("qr-code.png"))]
    if ctx.p["pdf"]:
        p = ctx.out("qr-code.pdf")
        img.save(str(p), "PDF", resolution=300)
        made.append(p)
    ctx.log(f"Encoded {len(data)} characters.")
    return ctx.done(*made)
