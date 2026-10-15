"""Line icons, drawn from SVG path data and recoloured for the active theme.

Everything is generated at runtime, so the app ships no image files and the
icons always match the current text colour.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6 import QtCore, QtGui, QtSvg

# 24x24 stroke-based paths. 'f:' prefix marks a filled sub-path.
P: dict[str, str] = {
    # --- files and navigation
    "file":        "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5",
    "files":       "M9 3h6l4 5v9a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z M5 7v12a2 2 0 0 0 2 2h8",
    "folder":      "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
    "download":    "M12 3v12 M7 11l5 5 5-5 M4 20h16",
    "upload":      "M12 21V9 M7 13l5-5 5 5 M4 4h16",
    "open":        "M4 6a2 2 0 0 1 2-2h5l2 2h5a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z M9 12h8 M14 9l3 3-3 3",
    "search":      "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z M16.5 16.5L21 21",
    "plus":        "M12 5v14 M5 12h14",
    "minus":       "M5 12h14",
    "close":       "M6 6l12 12 M18 6L6 18",
    "check":       "M5 13l4 4 10-10",
    "left":        "M15 5l-7 7 7 7",
    "right":       "M9 5l7 7-7 7",
    "up":          "M5 15l7-7 7 7",
    "down":        "M19 9l-7 7-7-7",
    "first":       "M17 5l-7 7 7 7 M7 5v14",
    "last":        "M7 5l7 7-7 7 M17 5v14",
    "menu":        "M4 7h16 M4 12h16 M4 17h16",
    "settings":    "M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1A1.6 1.6 0 0 0 7.5 19.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 14H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 7.5l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 10 3V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z",

    # --- page organisation
    "merge":       "M4 5h6v6H4z M14 13h6v6h-6z M10 8h2a2 2 0 0 1 2 2v6",
    "split":       "M9 4H4v16h5 M15 4h5v16h-5 M12 3v18",
    "extract":     "M5 4h8l4 4v4 M13 4v4h4 M14 17h7 M18 14l3 3-3 3",
    "trash":       "M4 7h16 M9 7V5h6v2 M6 7l1 13h10l1-13 M10 11v6 M14 11v6",
    "reorder":     "M4 7h10 M4 12h16 M4 17h7 M17 5l3 3-3 3",
    "rotate_cw":   "M20 11a8 8 0 1 1-2.4-5.7 M20 4v5h-5",
    "rotate_ccw":  "M4 11a8 8 0 1 0 2.4-5.7 M4 4v5h5",
    "rotate_180":  "M12 4a8 8 0 1 1-8 8 M12 1l3 3-3 3",
    "copy":        "M9 9h10v10H9z M5 15V5h10",
    "reverse":     "M7 7h11l-3-3 M17 17H6l3 3",
    "blank":       "M6 3h12v18H6z",
    "insert":      "M5 4h9l5 5v11H5z M14 4v5h5 M12 11v6 M9 14h6",
    "grid":        "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z",

    # --- compression and size
    "compress":    "M4 9V5h4 M20 9V5h-4 M4 15v4h4 M20 15v4h-4 M8 12h8",
    "gauge":       "M4 18a8 8 0 1 1 16 0 M12 14l4-4",
    "image_down":  "M4 5h16v10H4z M7 12l3-3 3 3 2-2 3 3 M12 18v4 M9 20l3 2 3-2",
    "broom":       "M14 3l7 7-5 2-4-4z M11 8l-7 7v5h5l7-7",
    "globe":       "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M3 12h18 M12 3c3 4 3 14 0 18 M12 3c-3 4-3 14 0 18",
    "scale":       "M6 20h12 M12 4v16 M4 10l4-6 4 6a4 4 0 0 1-8 0z M12 10l4-6 4 6a4 4 0 0 1-8 0z",

    # --- editing
    "pen":         "M4 20l4-1 11-11a2.1 2.1 0 0 0-3-3L5 16z M14 5l3 3",
    "text":        "M5 6V4h14v2 M12 4v16 M9 20h6",
    "image":       "M4 5h16v14H4z M8 11a1.6 1.6 0 1 0 0-3.2A1.6 1.6 0 0 0 8 11z M4 16l5-4 4 3 3-2 4 4",
    "shapes":      "M4 13h7v7H4z M15.5 4L20 12h-9z",
    "line":        "M5 19L19 5",
    "arrow":       "M5 19L19 5 M19 5h-6 M19 5v6",
    "ink":         "M4 17c3 0 3-8 6-8s3 8 6 8 4-4 4-4",
    "highlight":   "M5 19h14 M8 15l7-7 3 3-7 7z M8 15H5v-3l3 3z",
    "underline":   "M7 4v7a5 5 0 0 0 10 0V4 M5 20h14",
    "strike":      "M5 12h14 M8 7a4 3 0 0 1 8 0 M16 16a4 3 0 0 1-8 0",
    "note":        "M5 4h14v11l-5 5H5z M19 15h-5v5",
    "stamp":       "M6 20h12 M9 15V9a3 3 0 1 1 6 0v6 M5 17h14v-2H5z",
    "redact":      "M4 6h16v5H4z f:M4 13h11v4H4z",
    "undo":        "M9 10H4V5 M4 10a8 8 0 1 1 2 7",
    "redo":        "M15 10h5V5 M20 10a8 8 0 1 0-2 7",
    "eye":         "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "select":      "M5 3l14 7-6 2-2 6z",

    # --- layout
    "crop":        "M6 2v16h16 M2 6h16v16",
    "margins":     "M3 3h18v18H3z M7 7h10v10H7z",
    "resize":      "M4 4h7v7H4z M20 20v-7h-7 M11 11l9 9",
    "landscape":   "M3 7h18v10H3z",
    "numbers":     "M6 4v6 M4 6l2-2 M4 20h4 M6 14a2 2 0 1 1 2 2l-2 4 M13 8h8 M13 16h8",
    "watermark":   "M12 3c3 5 6 7 6 10a6 6 0 0 1-12 0c0-3 3-5 6-10z",
    "header":      "M4 5h16 M4 9h10 M4 15h16 M4 19h10",
    "border":      "M4 4h16v16H4z M8 8h8v8H8z",
    "nup":         "M3 5h8v14H3z M13 5h8v6h-8z M13 13h8v6h-8z",
    "halve":       "M4 4h16v16H4z M12 4v16",
    "layers":      "M12 3l9 5-9 5-9-5z M3 13l9 5 9-5 M3 17l9 5 9-5",

    # --- security
    "lock":        "M6 11h12v9H6z M9 11V8a3 3 0 0 1 6 0v3",
    "unlock":      "M6 11h12v9H6z M9 11V8a3 3 0 0 1 5.6-1.9",
    "shield":      "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M9 12l2 2 4-4",
    "key":         "M14 7a4 4 0 1 1 3 7l-1-1-2 2-2-2-2 2-2-2 6-6z",
    "eraser":      "M4 16l7-7 6 6-5 5H6z M13 20h7",
    "tag":         "M4 4h8l8 8-8 8-8-8z M8 8h.01",

    # --- conversion
    "convert":     "M4 8h13l-3-3 M20 16H7l3 3",
    "to_pdf":      "M6 3h8l4 4v14H6z M14 3v4h4 M9 17v-5h2a1.5 1.5 0 0 1 0 3H9",
    "picture":     "M4 5h16v14H4z M8 11a1.6 1.6 0 1 0 0-3.2A1.6 1.6 0 0 0 8 11z M4 16l5-4 4 3 3-2 4 4",
    "code":        "M9 7l-5 5 5 5 M15 7l5 5-5 5",
    "table":       "M3 5h18v14H3z M3 10h18 M3 15h18 M9 5v14 M15 5v14",
    "archive":     "M3 5h18v4H3z M5 9v11h14V9 M10 13h4",
    "word":        "M6 3h8l4 4v14H6z M14 3v4h4 M8 12l1.5 6L11 14l1.5 4L14 12",
    "excel":       "M6 3h8l4 4v14H6z M14 3v4h4 M9 12l5 6 M14 12l-5 6",
    "slides":      "M4 4h16v11H4z M12 15v4 M8 19h8",
    "book":        "M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z M8 20a3 3 0 0 1 0-6h10",

    # --- scanning
    "scan":        "M4 8V5h3 M20 8V5h-3 M4 16v3h3 M20 16v3h-3 M4 12h16",
    "camera":      "M4 8h3l2-2h6l2 2h3v11H4z M12 17a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z",
    "ocr":         "M4 8V5h4 M20 8V5h-4 M4 16v3h4 M20 16v3h-4 M8 15V9h2a2 2 0 0 1 0 4H8 M14 15V9 M14 9h3",
    "straighten":  "M3 17l18-6 M3 17l3 3 M21 11l-3-3",
    "contrast":    "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z f:M12 3v18a9 9 0 0 0 0-18z",
    "blank_page":  "M6 3h12v18H6z M9 12h6",

    # --- forms
    "form":        "M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h4",
    "checkbox":    "M4 5h16v14H4z M8 12l3 3 5-6",
    "dropdown":    "M4 7h16v10H4z M14 10l2 2 2-2",
    "calendar":    "M4 6h16v14H4z M4 10h16 M8 3v4 M16 3v4",
    "signature":   "M3 17c4 0 5-9 8-9s2 6 4 6 2-3 6-3 M3 21h18",
    "pen_field":   "M4 15h10 M4 19h16 M17 4l3 3-7 7-4 1 1-4z",
    "export":      "M5 15v4h14v-4 M12 3v12 M8 9l4-4 4 4",

    # --- utilities
    "info":        "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 11v6 M12 8h.01",
    "ruler":       "M3 9h18v6H3z M7 9v3 M11 9v3 M15 9v3 M19 9v3",
    "font":        "M4 20l6-14 6 14 M6.5 15h7 M17 20h4",
    "bookmark":    "M7 3h10v18l-5-4-5 4z",
    "list":        "M4 6h2 M4 12h2 M4 18h2 M9 6h11 M9 12h11 M9 18h11",
    "wrench":      "M14 5a4 4 0 0 1 5 5l-9 9-4 1 1-4z M14 5l5 5",
    "compare":     "M12 3v18 M4 7h5v10H4z M15 7h5v10h-5z",
    "printer":     "M7 9V4h10v5 M5 9h14v7h-3v4H8v-4H5z M9 16h6",
    "clock":       "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z M12 7v5l3 2",

    # --- images
    "crop_img":    "M6 2v16h16 M2 6h16v16",
    "palette":     "M12 3a9 9 0 0 0 0 18 2 2 0 0 0 2-2 2 2 0 0 1 2-2h2a3 3 0 0 0 3-3 9 9 0 0 0-9-11z M7.5 11a1 1 0 1 0 0-2 1 1 0 0 0 0 2z M12 8.5a1 1 0 1 0 0-2 1 1 0 0 0 0 2z M16 11a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
    "flip":        "M12 3v18 M9 7L4 12l5 5z M15 7l5 5-5 5z",
    "sun":         "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 2v2 M12 20v2 M2 12h2 M20 12h2 M5 5l1.5 1.5 M17.5 17.5L19 19 M19 5l-1.5 1.5 M6.5 17.5L5 19",
    "portrait":    "M7 3h10v18H7z M12 11a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z M8 18c1-2.5 7-2.5 8 0",
    "qr":          "M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h2v2h-2z M18 14h2v2h-2z M14 18h2v2h-2z M18 18h2v2h-2z M6.5 6.5h1v1h-1z M16.5 6.5h1v1h-1z M6.5 16.5h1v1h-1z",

    # --- batch
    "workflow":    "M4 5h5v4H4z M15 5h5v4h-5z M9.5 15h5v4h-5z M9 7h6 M6.5 9v3h11V9",
    "batch":       "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M15.5 13.5v6 M12.5 16.5h6",
    "star":        "M12 3l2.7 5.8 6.3.8-4.6 4.4 1.2 6.2L12 17.2 6.4 20.2l1.2-6.2L3 9.6l6.3-.8z",
    "play":        "f:M7 4l13 8-13 8z",
    "stop":        "M6 6h12v12H6z",
    "refresh":     "M20 11a8 8 0 1 0-2 6 M20 4v6h-6",
    "zip":         "M5 3h14v18H5z M11 3v3 M13 6v3 M11 9v3 M13 12v3 M11 15h2v4h-2z",
    "save":        "M5 3h11l3 3v15H5z M8 3v6h7V3 M8 14h8v7H8z",
}

ALIASES = {
    "run": "play", "cancel": "stop", "print": "printer", "help": "info",
    "delete": "trash", "add": "plus", "remove": "minus", "ok": "check",
}


def _svg(name: str, color: str, width: float = 1.9) -> bytes:
    path = P.get(ALIASES.get(name, name)) or P["file"]
    stroked, filled = [], []
    head, sep, tail = path.partition("f:")
    if head.strip():
        stroked.append(head.strip())
    while sep:
        chunk, sep, tail = tail.partition("f:")
        if chunk.strip():
            filled.append(chunk.strip())
    body = ""
    for d in stroked:
        body += (f'<path d="{d}" fill="none" stroke="{color}" '
                 f'stroke-width="{width}" stroke-linecap="round" '
                 f'stroke-linejoin="round"/>')
    for d in filled:
        body += f'<path d="{d}" fill="{color}" stroke="none"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
            f'{body}</svg>').encode()


@lru_cache(maxsize=1024)
def pixmap(name: str, size: int = 18, color: str = "#e8eaef",
           width: float = 1.9) -> QtGui.QPixmap:
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(_svg(name, color, width)))
    dpr = 2
    pm = QtGui.QPixmap(size * dpr, size * dpr)
    pm.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    # render at full device resolution, then mark the pixmap as high-DPI
    renderer.render(painter, QtCore.QRectF(0, 0, size * dpr, size * dpr))
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


@lru_cache(maxsize=1024)
def icon(name: str, size: int = 18, color: str = "#e8eaef",
         dim: str = "") -> QtGui.QIcon:
    ic = QtGui.QIcon()
    ic.addPixmap(pixmap(name, size, color), QtGui.QIcon.Normal)
    ic.addPixmap(pixmap(name, size, dim or color), QtGui.QIcon.Disabled)
    return ic


# ---------------------------------------------------------------- app icon

def app_icon(size: int = 256, dark: bool = True) -> QtGui.QIcon:
    """The window/taskbar icon: a document mark with the app's accent."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    r = QtCore.QRectF(0, 0, size, size)
    grad = QtGui.QLinearGradient(r.topLeft(), r.bottomRight())
    grad.setColorAt(0, QtGui.QColor("#4f8cff"))
    grad.setColorAt(1, QtGui.QColor("#2f5fd0"))
    p.setBrush(QtGui.QBrush(grad))
    p.setPen(QtCore.Qt.NoPen)
    p.drawRoundedRect(r.adjusted(size * .06, size * .06, -size * .06,
                                 -size * .06), size * .22, size * .22)
    s = size * 0.5
    doc = QtCore.QRectF((size - s * .78) / 2, (size - s) / 2, s * .78, s)
    p.setBrush(QtGui.QBrush(QtGui.QColor("white")))
    p.drawRoundedRect(doc, s * .08, s * .08)
    p.setBrush(QtGui.QBrush(QtGui.QColor("#2f5fd0")))
    fold = QtGui.QPolygonF([
        QtCore.QPointF(doc.right() - s * .26, doc.top()),
        QtCore.QPointF(doc.right(), doc.top() + s * .26),
        QtCore.QPointF(doc.right() - s * .26, doc.top() + s * .26)])
    p.drawPolygon(fold)
    pen = QtGui.QPen(QtGui.QColor("#2f5fd0"), size * .022,
                     QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
    p.setPen(pen)
    for k in range(3):
        y = doc.top() + s * (.46 + k * .16)
        p.drawLine(QtCore.QPointF(doc.left() + s * .14, y),
                   QtCore.QPointF(doc.right() - s * .14, y))
    p.end()
    return QtGui.QIcon(pm)


def write_app_icon(path, size: int = 256) -> None:
    app_icon(size).pixmap(size, size).save(str(path))


# ----------------------------------------------- per-tool and per-category

CATEGORY_ICONS = {
    "organize": "grid", "compress": "compress", "edit": "pen",
    "layout": "margins", "security": "lock", "convert": "convert",
    "office": "word", "ocr": "scan", "forms": "form", "utility": "wrench",
    "image": "picture", "batch": "batch",
}

TOOL_ICONS = {
    # organise
    "merge": "merge", "split_ranges": "split", "split_every": "split",
    "split_single": "split", "extract": "extract", "delete_pages": "trash",
    "reorder": "reorder", "rotate": "rotate_cw", "duplicate": "copy",
    "reverse": "reverse", "blank_pages": "blank", "insert_pdf": "insert",
    "organize_visual": "grid", "export_selection": "export",
    # compress
    "compress": "compress", "downsample": "image_down",
    "clean_objects": "broom", "linearize": "globe", "size_report": "scale",
    # edit
    "editor": "pen", "add_text": "text", "insert_image_tool": "image",
    "draw_shape": "shapes", "markup_text": "highlight",
    "sticky_note": "note", "stamp": "stamp", "freehand": "ink",
    "remove_annots": "eraser",
    # layout
    "crop": "crop", "margins": "margins", "page_size": "resize",
    "orientation": "landscape", "page_numbers": "numbers",
    "watermark_text": "watermark", "watermark_image": "watermark",
    "header_footer": "header", "borders": "border", "nup": "nup",
    "split_page": "halve", "flatten": "layers",
    # security
    "protect": "lock", "unprotect": "unlock", "encrypt_only": "key",
    "restrictions": "shield", "permissions": "shield",
    "strip_metadata": "eraser", "redact": "redact", "redact_boxes": "redact",
    # convert
    "images_to_pdf": "to_pdf", "pdf_to_images": "picture",
    "extract_images": "image", "pdf_to_text": "text",
    "text_to_pdf": "to_pdf", "html_to_pdf": "code", "md_to_pdf": "to_pdf",
    "pdf_to_html": "code", "pdf_to_svg": "shapes", "pdf_to_pdfa": "shield",
    "pdf_to_zip": "archive", "zip_to_pdf": "archive",
    # office
    "docx_to_pdf": "word", "xlsx_to_pdf": "excel", "pptx_to_pdf": "slides",
    "odt_to_pdf": "word", "ods_to_pdf": "excel", "odp_to_pdf": "slides",
    "rtf_to_pdf": "word", "epub_to_pdf": "book", "pdf_to_docx": "word",
    "pdf_to_xlsx": "excel", "pdf_to_pptx": "slides", "pdf_to_rtf": "word",
    "pdf_to_csv": "table", "pdf_to_xml": "code",
    # ocr
    "images_to_scan_pdf": "scan", "ocr_pdf": "ocr", "ocr_read": "ocr",
    "fix_orientation": "rotate_cw", "deskew_pdf": "straighten",
    "remove_blank": "blank_page", "enhance_pdf": "contrast",
    "camera_scan": "camera",
    # forms
    "form_inspect": "list", "form_fill": "form", "form_fill_data": "table",
    "form_reset": "refresh", "form_flatten": "layers",
    "form_create": "checkbox", "form_create_quick": "dropdown",
    "sign_pdf": "signature", "sign_image": "signature",
    "sign_fields": "pen_field", "form_export": "export",
    # utilities
    "view_pdf": "eye", "search_text": "search", "properties": "info",
    "page_info": "ruler", "font_info": "font", "edit_metadata": "tag",
    "bookmarks": "bookmark", "toc_page": "list", "repair": "wrench",
    "compare": "compare", "compare_report": "compare", "print_pdf": "printer",
    "save_pages": "download",
    # images
    "img_resize": "resize", "img_compress": "compress",
    "img_convert": "convert", "img_crop": "crop_img", "img_rotate": "flip",
    "img_gray": "contrast", "img_adjust": "sun", "img_passport": "portrait",
    "img_border": "border", "qr_code": "qr",
    # batch
    "chain": "workflow", "batch_run": "batch", "zip_outputs": "zip",
    "presets_manage": "star",
}


def for_tool(tool_id: str, category: str = "") -> str:
    return TOOL_ICONS.get(tool_id) or CATEGORY_ICONS.get(category, "file")


# ------------------------------------------------- live, theme-aware icons

_STATE = {"color": "#e8eaef", "dim": "#6b7382", "accent": "#4f8cff"}
_TRACKED: list = []        # (weakref to widget, icon name, size, role)


def set_theme(colors: dict) -> None:
    """Point the icon factory at the active palette and repaint every icon
    that was attached with `apply`."""
    _STATE.update({"color": colors.get("text", "#e8eaef"),
                   "dim": colors.get("faint", "#6b7382"),
                   "accent": colors.get("accent", "#4f8cff")})
    refresh()


def current(role: str = "color") -> str:
    return _STATE.get(role, _STATE["color"])


def ic(name: str, size: int = 18, role: str = "color") -> QtGui.QIcon:
    return icon(name, size, _STATE.get(role, _STATE["color"]), _STATE["dim"])


def apply(widget, name: str, size: int = 18, role: str = "color"):
    """Give a widget an icon and remember it across theme changes."""
    import weakref
    widget.setIcon(ic(name, size, role))
    if hasattr(widget, "setIconSize"):
        widget.setIconSize(QtCore.QSize(size, size))
    _TRACKED.append((weakref.ref(widget), name, size, role))
    return widget


def item_icon(item, name: str, size: int = 18, role: str = "color"):
    item.setIcon(ic(name, size, role))
    return item


def refresh() -> None:
    alive = []
    for ref, name, size, role in _TRACKED:
        w = ref()
        if w is None:
            continue
        try:
            w.setIcon(ic(name, size, role))
            alive.append((ref, name, size, role))
        except RuntimeError:          # the C++ object is gone
            continue
    _TRACKED[:] = alive
