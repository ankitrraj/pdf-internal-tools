"""Visual editor: add text, images, shapes, ink, highlights, notes, stamps
and redaction boxes; move and resize them; undo, redo, preview, export."""
from __future__ import annotations

import copy
from pathlib import Path

import pymupdf as fitz
from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.core.common import (FONT_CHOICES, FONT_LABELS, parse_color,
                                    save_pdf, to_hex)
from pdfbuilder.ui.views.common import (FilePicker, PageCanvas, ToolBarRow,
                                        open_with_prompt)
from pdfbuilder.ui import icons
from pdfbuilder.ui.widgets import (ColorButton, icon_label, open_externally,
                                   reveal_in_files)

Qt = QtCore.Qt

TOOLS = [
    ("select", "Select / move", "Click an item to move or resize it",
     "select"),
    ("text", "Text", "Click where the text should start", "text"),
    ("image", "Image", "Drag a box, then choose a picture", "image"),
    ("rect", "Rectangle", "Drag to draw", "border"),
    ("ellipse", "Ellipse", "Drag to draw", "shapes"),
    ("line", "Line", "Drag from start to end", "line"),
    ("arrow", "Arrow", "Drag from tail to head", "arrow"),
    ("ink", "Freehand", "Hold the left button and draw", "ink"),
    ("highlight", "Highlight", "Drag across the words to highlight",
     "highlight"),
    ("underline", "Underline", "Drag across the words", "underline"),
    ("strike", "Strike through", "Drag across the words", "strike"),
    ("note", "Sticky note", "Click to drop a comment", "note"),
    ("stamp", "Stamp", "Click to place a stamp", "stamp"),
    ("redact", "Redact", "Drag over anything to delete permanently",
     "redact"),
]

STAMP_TEXTS = ("APPROVED", "DRAFT", "FINAL", "CONFIDENTIAL", "PAID", "VOID",
               "FOR REVIEW", "COPY", "RECEIVED")


class Item:
    """One pending edit, stored in PDF coordinates."""

    def __init__(self, kind, page, rect, **kw):
        self.kind = kind
        self.page = page
        self.rect = list(rect)           # x0,y0,x1,y1 in points
        self.props = dict(kw)

    def clone(self):
        it = Item(self.kind, self.page, list(self.rect))
        it.props = copy.deepcopy(self.props)
        return it


class Editor(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.tool = tool
        self.doc: fitz.Document | None = None
        self.path: Path | None = None
        self.index = 0
        self.items: list[Item] = []
        self.undo_stack: list[list[Item]] = []
        self.redo_stack: list[list[Item]] = []
        self.mode = "redact" if tool.id == "redact_boxes" else "select"
        self.selected: Item | None = None
        self._draft = None
        self._ink: list[list[tuple[float, float]]] = []
        self._drag_mode = None
        self._drag_start = None
        self._orig_rect = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(icon_label(tool.name, "h1"))
        head.addStretch(1)
        root.addLayout(head)
        root.addWidget(self._wrap(icon_label(tool.summary, "dim")))

        top = ToolBarRow(wrap=True)
        self.picker = FilePicker("Document")
        self.picker.file_chosen.connect(self.open_path)
        top.add(self.picker)
        top.sep()
        top.button("‹", lambda: self.goto(self.index - 1), tip="Previous page", icon="left")
        self.page_label = top.label("- / -")
        top.button("›", lambda: self.goto(self.index + 1), tip="Next page", icon="right")
        top.sep()
        top.button("−", lambda: self.scale(1 / 1.2), tip="Zoom out", icon="minus")
        self.zoom_label = top.label("100%")
        top.button("+", lambda: self.scale(1.2), tip="Zoom in", icon="plus")
        top.button("Fit", lambda: self.fit(), icon="margins")
        top.stretch()
        top.button("Undo", self.do_undo, shortcut="Ctrl+Z")
        top.button("Redo", self.do_redo, shortcut="Ctrl+Shift+Z")
        top.button("Preview changes", self.preview, icon="eye")
        self.btn_apply = top.button("Save PDF", self.export, kind="primary",
                                    shortcut="Ctrl+S", icon="save")
        root.addWidget(top)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(10)

        # --- tool palette -------------------------------------------------
        palette = QtWidgets.QFrame()
        palette.setObjectName("Card")
        palette.setFixedWidth(176)
        pv = QtWidgets.QVBoxLayout(palette)
        pv.setContentsMargins(8, 8, 8, 8)
        pv.setSpacing(3)
        pv.addWidget(icon_label("Tools", "h2"))
        self.mode_buttons = {}
        for key, label, tip, icon_name in TOOLS:
            b = QtWidgets.QPushButton(label)
            icons.apply(b, icon_name, 16)
            b.setProperty("kind", "tool")
            b.setCheckable(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            pv.addWidget(b)
            self.mode_buttons[key] = b
        pv.addStretch(1)
        body.addWidget(palette)

        # --- canvas -------------------------------------------------------
        mid = QtWidgets.QVBoxLayout()
        mid.setSpacing(6)
        self.canvas = PageCanvas()
        self.canvas.clicked.connect(self.on_press)
        self.canvas.dragged.connect(self.on_drag)
        self.canvas.released.connect(self.on_release)
        self.canvas.zoom_changed.connect(
            lambda z: self.zoom_label.setText(f"{z*100:.0f}%"))
        mid.addWidget(self.canvas, 1)
        self.hint = icon_label("Open a PDF, pick a tool, then draw on the "
                               "page.", "faint")
        mid.addWidget(self.hint)
        body.addLayout(mid, 1)

        # --- properties ---------------------------------------------------
        side = QtWidgets.QFrame()
        side.setObjectName("Card")
        side.setFixedWidth(258)
        sv = QtWidgets.QVBoxLayout(side)
        sv.setContentsMargins(10, 10, 10, 10)
        sv.setSpacing(8)
        sv.addWidget(icon_label("Style", "h2"))

        form = QtWidgets.QFormLayout()
        form.setSpacing(7)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.text_edit = QtWidgets.QPlainTextEdit("Your text")
        self.text_edit.setMaximumHeight(72)
        form.addRow("Text", self.text_edit)
        self.font_box = QtWidgets.QComboBox()
        for f in FONT_CHOICES:
            self.font_box.addItem(FONT_LABELS.get(f, f), f)
        form.addRow("Font", self.font_box)
        self.size_box = QtWidgets.QDoubleSpinBox()
        self.size_box.setRange(4, 300)
        self.size_box.setValue(14)
        self.size_box.setSuffix(" pt")
        form.addRow("Size", self.size_box)
        self.color_btn = ColorButton("#1a1a1a", allow_empty=False)
        form.addRow("Colour", self.color_btn)
        self.fill_btn = ColorButton("", allow_empty=True)
        form.addRow("Fill", self.fill_btn)
        self.width_box = QtWidgets.QDoubleSpinBox()
        self.width_box.setRange(0, 40)
        self.width_box.setValue(1.6)
        self.width_box.setSuffix(" pt")
        form.addRow("Line width", self.width_box)
        self.opacity_box = QtWidgets.QDoubleSpinBox()
        self.opacity_box.setRange(0.05, 1.0)
        self.opacity_box.setSingleStep(0.05)
        self.opacity_box.setValue(1.0)
        form.addRow("Opacity", self.opacity_box)
        self.stamp_box = QtWidgets.QComboBox()
        self.stamp_box.addItems(STAMP_TEXTS)
        self.stamp_box.setEditable(True)
        form.addRow("Stamp", self.stamp_box)
        sv.addLayout(form)

        hint = icon_label("Changes apply to the next item you draw, and to "
                          "the selected item.", "faint")
        hint.setWordWrap(True)
        sv.addWidget(hint)
        for w in (self.color_btn, self.fill_btn):
            w.changed.connect(self._apply_style_to_selection)
        self.size_box.valueChanged.connect(self._apply_style_to_selection)
        self.width_box.valueChanged.connect(self._apply_style_to_selection)
        self.opacity_box.valueChanged.connect(self._apply_style_to_selection)
        self.font_box.currentIndexChanged.connect(
            self._apply_style_to_selection)
        self.text_edit.textChanged.connect(self._apply_style_to_selection)

        sv.addWidget(self._hline())
        sv.addWidget(icon_label("Items on this page", "h2"))
        self.item_list = QtWidgets.QListWidget()
        self.item_list.currentRowChanged.connect(self._pick_from_list)
        sv.addWidget(self.item_list, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Delete item")
        icons.apply(b, "trash", 15)
        b.setProperty("kind", "danger")
        b.clicked.connect(self.delete_selected)
        row.addWidget(b)
        b2 = QtWidgets.QPushButton("Clear page")
        icons.apply(b2, "eraser", 15)
        b2.setProperty("kind", "danger")
        b2.clicked.connect(self.clear_page)
        row.addWidget(b2)
        sv.addLayout(row)
        body.addWidget(side)

        root.addLayout(body, 1)
        self.set_mode(self.mode)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _wrap(w):
        w.setWordWrap(True)
        return w

    @staticmethod
    def _hline():
        f = QtWidgets.QFrame()
        f.setFrameShape(QtWidgets.QFrame.HLine)
        f.setStyleSheet("color: rgba(128,128,128,.3)")
        return f

    def add_files(self, paths):
        pdfs = [p for p in paths if str(p).lower().endswith(".pdf")]
        if pdfs:
            self.picker.add(pdfs)

    def open_path(self, path):
        doc = open_with_prompt(self, path)
        if doc is None:
            return
        if self.doc:
            self.doc.close()
        self.doc = doc
        self.path = Path(path)
        self.index = 0
        self.items.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.canvas.set_zoom(1.0)
        self.fit()

    def set_mode(self, mode):
        self.mode = mode
        for k, b in self.mode_buttons.items():
            b.setChecked(k == mode)
        tip = {k: t for k, _, t, _i in TOOLS}.get(mode, "")
        self.hint.setText(tip)
        drag = (QtWidgets.QGraphicsView.NoDrag)
        self.canvas.setDragMode(drag)
        self.canvas.setCursor(Qt.ArrowCursor if mode == "select"
                              else Qt.CrossCursor)

    # ---------------------------------------------------------------- pages
    def goto(self, index):
        if not self.doc:
            return
        self.index = max(0, min(index, self.doc.page_count - 1))
        self.page_label.setText(f"{self.index+1} / {self.doc.page_count}")
        self.redraw()

    def scale(self, factor):
        self.canvas.set_zoom(self.canvas.zoom * factor)
        self.redraw()

    def fit(self):
        if not self.doc:
            return
        self.canvas.show_page(self.doc, self.index)
        self.canvas.set_zoom(self.canvas.fit_page())
        self.goto(self.index)

    def redraw(self):
        if not self.doc:
            return
        self.canvas.show_page(self.doc, self.index)
        z = self.canvas.zoom
        self.item_list.blockSignals(True)
        self.item_list.clear()
        for it in self.items:
            if it.page != self.index:
                continue
            self._draw_item(it, z)
            label = it.kind
            if it.kind in ("text", "note", "stamp"):
                label += f": {str(it.props.get('text',''))[:22]}"
            row = QtWidgets.QListWidgetItem(label)
            icons.item_icon(row, {k: i for k, _n, _t, i in TOOLS}.get(
                it.kind, "shapes"), 15)
            self.item_list.addItem(row)
            if it is self.selected:
                self.item_list.setCurrentRow(self.item_list.count() - 1)
        self.item_list.blockSignals(False)

    def _page_items(self):
        return [it for it in self.items if it.page == self.index]

    def _draw_item(self, it: Item, z: float):
        x0, y0, x1, y1 = (v * z for v in it.rect)
        rect = QtCore.QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0),
                             abs(y1 - y0))
        col = QtGui.QColor(to_hex(parse_color(it.props.get("color",
                                                           "#1a1a1a"))))
        col.setAlphaF(float(it.props.get("opacity", 1.0)))
        fill_raw = it.props.get("fill", "")
        pen = QtGui.QPen(col, max(1.0, float(it.props.get("width", 1.5)) * z))
        brush = QtGui.QBrush(Qt.NoBrush)
        if fill_raw:
            fc = QtGui.QColor(to_hex(parse_color(fill_raw)))
            fc.setAlphaF(float(it.props.get("opacity", 1.0)))
            brush = QtGui.QBrush(fc)

        gi = None
        if it.kind == "rect":
            gi = QtWidgets.QGraphicsRectItem(rect)
            gi.setPen(pen)
            gi.setBrush(brush)
        elif it.kind == "ellipse":
            gi = QtWidgets.QGraphicsEllipseItem(rect)
            gi.setPen(pen)
            gi.setBrush(brush)
        elif it.kind in ("line", "arrow"):
            gi = QtWidgets.QGraphicsLineItem(x0, y0, x1, y1)
            gi.setPen(pen)
            if it.kind == "arrow":
                self._arrow_overlay(x0, y0, x1, y1, pen, z)
        elif it.kind in ("highlight", "underline", "strike", "redact"):
            gi = QtWidgets.QGraphicsRectItem(rect)
            if it.kind == "redact":
                gi.setPen(QtGui.QPen(QtGui.QColor("#ff3b30"), 1.4,
                                     Qt.DashLine))
                gi.setBrush(QtGui.QBrush(QtGui.QColor(20, 20, 20, 190)))
            elif it.kind == "highlight":
                hl = QtGui.QColor(to_hex(parse_color(
                    it.props.get("color", "#ffe14d"))))
                hl.setAlpha(110)
                gi.setPen(QtGui.QPen(Qt.NoPen))
                gi.setBrush(QtGui.QBrush(hl))
            else:
                gi.setPen(QtGui.QPen(Qt.NoPen))
                gi.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 0)))
                line_y = (rect.bottom() - 1 if it.kind == "underline"
                          else rect.center().y())
                li = QtWidgets.QGraphicsLineItem(rect.left(), line_y,
                                                 rect.right(), line_y)
                li.setPen(QtGui.QPen(col, max(1.2, 1.4 * z)))
                self.canvas.add_overlay(li)
        elif it.kind == "ink":
            path = QtGui.QPainterPath()
            for stroke in it.props.get("strokes", []):
                if not stroke:
                    continue
                path.moveTo(stroke[0][0] * z, stroke[0][1] * z)
                for px, py in stroke[1:]:
                    path.lineTo(px * z, py * z)
            gi = QtWidgets.QGraphicsPathItem(path)
            gi.setPen(QtGui.QPen(col, max(1.0, float(
                it.props.get("width", 2.0)) * z), Qt.SolidLine, Qt.RoundCap,
                Qt.RoundJoin))
        elif it.kind == "image":
            pm = it.props.get("_pixmap")
            if pm is not None:
                gi = QtWidgets.QGraphicsPixmapItem(
                    pm.scaled(max(1, int(rect.width())),
                              max(1, int(rect.height())),
                              Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
                gi.setPos(rect.topLeft())
                gi.setOpacity(float(it.props.get("opacity", 1.0)))
        elif it.kind in ("text", "stamp", "note"):
            label = str(it.props.get("text", ""))
            if it.kind == "note":
                gi = QtWidgets.QGraphicsRectItem(
                    QtCore.QRectF(rect.left(), rect.top(), 16 * z, 16 * z))
                gi.setBrush(QtGui.QBrush(QtGui.QColor("#ffd000")))
                gi.setPen(QtGui.QPen(QtGui.QColor("#9a7b00"), 1))
                ti = QtWidgets.QGraphicsSimpleTextItem(
                    label[:40] + ("..." if len(label) > 40 else ""))
                ti.setBrush(QtGui.QBrush(col))
                ti.setPos(rect.left() + 20 * z, rect.top())
                f = ti.font()
                f.setPointSizeF(max(5.0, 8 * z))
                ti.setFont(f)
                self.canvas.add_overlay(ti)
            else:
                ti = QtWidgets.QGraphicsTextItem(label)
                ti.setDefaultTextColor(col)
                font = QtGui.QFont(
                    "Helvetica" if "hel" in it.props.get("font", "helv")
                    else "Times" if "ti" in it.props.get("font", "") else
                    "monospace")
                font.setPointSizeF(max(2.0, float(it.props.get(
                    "size", 14)) * z * 0.75))
                font.setBold(it.kind == "stamp")
                ti.setFont(font)
                ti.setPos(rect.left(), rect.top())
                ti.setOpacity(float(it.props.get("opacity", 1.0)))
                self.canvas.add_overlay(ti)
                br = ti.boundingRect()
                it.rect[2] = it.rect[0] + br.width() / z
                it.rect[3] = it.rect[1] + br.height() / z
                if it.kind == "stamp":
                    gi = QtWidgets.QGraphicsRectItem(
                        QtCore.QRectF(rect.left() - 4 * z, rect.top() - 2 * z,
                                      br.width() + 8 * z, br.height() + 4 * z))
                    gi.setPen(QtGui.QPen(col, max(1.2, 1.6 * z)))
        if gi is not None:
            self.canvas.add_overlay(gi)
        if it is self.selected:
            sel = QtWidgets.QGraphicsRectItem(rect.adjusted(-3, -3, 3, 3))
            sel.setPen(QtGui.QPen(QtGui.QColor("#4f8cff"), 1.4, Qt.DashLine))
            self.canvas.add_overlay(sel)
            handle = QtWidgets.QGraphicsRectItem(
                QtCore.QRectF(rect.right() - 5, rect.bottom() - 5, 10, 10))
            handle.setBrush(QtGui.QBrush(QtGui.QColor("#4f8cff")))
            handle.setPen(QtGui.QPen(Qt.NoPen))
            self.canvas.add_overlay(handle)

    def _arrow_overlay(self, x0, y0, x1, y1, pen, z):
        import math
        ang = math.atan2(y1 - y0, x1 - x0)
        size = max(8.0, pen.widthF() * 4)
        for side in (-1, 1):
            a = ang + side * math.radians(150)
            li = QtWidgets.QGraphicsLineItem(
                x1, y1, x1 + size * math.cos(a), y1 + size * math.sin(a))
            li.setPen(pen)
            self.canvas.add_overlay(li)

    # --------------------------------------------------------------- input
    def _style(self) -> dict:
        return {"color": self.color_btn.value() or "#1a1a1a",
                "fill": self.fill_btn.value(),
                "width": self.width_box.value(),
                "opacity": self.opacity_box.value(),
                "size": self.size_box.value(),
                "font": self.font_box.currentData() or "helv"}

    def snapshot(self):
        self.undo_stack.append([it.clone() for it in self.items])
        if len(self.undo_stack) > 80:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def on_press(self, scene_pos, ev):
        if not self.doc or ev.button() != Qt.LeftButton:
            return
        x, y = self.canvas.to_pdf(scene_pos)
        if self.mode == "select":
            self.selected = self._hit(x, y)
            if self.selected:
                self._drag_start = (x, y)
                self._orig_rect = list(self.selected.rect)
                r = self.selected.rect
                near_corner = (abs(x - max(r[0], r[2])) < 9 and
                               abs(y - max(r[1], r[3])) < 9)
                self._drag_mode = "resize" if near_corner else "move"
                self._load_style(self.selected)
            self.redraw()
            return
        if self.mode == "ink":
            self._ink = [[(x, y)]]
            return
        if self.mode in ("text", "note", "stamp"):
            self.snapshot()
            text = (self.stamp_box.currentText() if self.mode == "stamp"
                    else self.text_edit.toPlainText() or "Text")
            it = Item(self.mode, self.index,
                      [x, y, x + 120, y + max(16, self.size_box.value() * 1.4)],
                      text=text, **self._style())
            if self.mode == "stamp":
                it.props["size"] = max(16.0, self.size_box.value() * 1.4)
            self.items.append(it)
            self.selected = it
            self.redraw()
            return
        if self.mode == "image":
            self._draft = Item("image", self.index, [x, y, x, y],
                               **self._style())
            return
        self._draft = Item(self.mode, self.index, [x, y, x, y], **self._style())
        if self.mode == "highlight" and not self.color_btn.value():
            self._draft.props["color"] = "#ffe14d"

    def on_drag(self, start, pos, ev):
        if not self.doc:
            return
        x, y = self.canvas.to_pdf(pos)
        if self.mode == "ink" and self._ink:
            self._ink[-1].append((x, y))
            self._live_ink()
            return
        if self.mode == "select" and self.selected and self._drag_start:
            sx, sy = self._drag_start
            dx, dy = x - sx, y - sy
            r = list(self._orig_rect)
            if self._drag_mode == "move":
                self.selected.rect = [r[0] + dx, r[1] + dy, r[2] + dx,
                                      r[3] + dy]
                if self.selected.kind == "ink":
                    strokes = self.selected.props.get("_orig_strokes")
                    if strokes is None:
                        strokes = copy.deepcopy(
                            self.selected.props.get("strokes", []))
                        self.selected.props["_orig_strokes"] = strokes
                    self.selected.props["strokes"] = [
                        [(px + dx, py + dy) for px, py in st]
                        for st in strokes]
            else:
                self.selected.rect = [r[0], r[1], max(r[0] + 6, r[2] + dx),
                                      max(r[1] + 6, r[3] + dy)]
            self.redraw()
            return
        if self._draft is not None:
            self._draft.rect[2], self._draft.rect[3] = x, y
            self.redraw()
            self._draw_item(self._draft, self.canvas.zoom)

    def _live_ink(self):
        z = self.canvas.zoom
        path = QtGui.QPainterPath()
        for stroke in self._ink:
            if not stroke:
                continue
            path.moveTo(stroke[0][0] * z, stroke[0][1] * z)
            for px, py in stroke[1:]:
                path.lineTo(px * z, py * z)
        gi = QtWidgets.QGraphicsPathItem(path)
        col = QtGui.QColor(to_hex(parse_color(self.color_btn.value()
                                              or "#1d4ed8")))
        gi.setPen(QtGui.QPen(col, max(1.0, self.width_box.value() * z),
                             Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.canvas.add_overlay(gi)

    def on_release(self, pos, ev):
        if not self.doc:
            return
        x, y = self.canvas.to_pdf(pos)
        if self.mode == "select":
            if self.selected and self._drag_start:
                self.selected.props.pop("_orig_strokes", None)
                self.snapshot()
            self._drag_start = None
            self._drag_mode = None
            return
        if self.mode == "ink":
            strokes = [s for s in self._ink if len(s) > 1]
            self._ink = []
            if strokes:
                self.snapshot()
                xs = [p[0] for s in strokes for p in s]
                ys = [p[1] for s in strokes for p in s]
                it = Item("ink", self.index,
                          [min(xs), min(ys), max(xs), max(ys)],
                          strokes=strokes, **self._style())
                self.items.append(it)
                self.selected = it
            self.redraw()
            return
        if self._draft is None:
            return
        draft = self._draft
        self._draft = None
        draft.rect[2], draft.rect[3] = x, y
        if abs(draft.rect[2] - draft.rect[0]) < 3 and \
                abs(draft.rect[3] - draft.rect[1]) < 3:
            self.redraw()
            return
        if draft.kind == "image":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Choose an image", str(Path.home()),
                "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff "
                "*.heic);;All files (*)")
            if not path:
                self.redraw()
                return
            draft.props["path"] = path
            pm = QtGui.QPixmap(path)
            if pm.isNull():
                from pdfbuilder.core.images import load_image
                try:
                    img = load_image(path).convert("RGBA")
                    data = img.tobytes("raw", "RGBA")
                    qi = QtGui.QImage(data, img.width, img.height,
                                      QtGui.QImage.Format_RGBA8888)
                    pm = QtGui.QPixmap.fromImage(qi.copy())
                except Exception as e:
                    QtWidgets.QMessageBox.warning(self, "Image",
                                                  f"Could not load it: {e}")
                    self.redraw()
                    return
            draft.props["_pixmap"] = pm
        self.snapshot()
        self.items.append(draft)
        self.selected = draft
        self.redraw()

    def _hit(self, x, y) -> Item | None:
        for it in reversed(self._page_items()):
            x0, x1 = sorted((it.rect[0], it.rect[2]))
            y0, y1 = sorted((it.rect[1], it.rect[3]))
            if x0 - 5 <= x <= x1 + 5 and y0 - 5 <= y <= y1 + 5:
                return it
        return None

    def _load_style(self, it: Item):
        for w in (self.color_btn, self.fill_btn, self.size_box,
                  self.width_box, self.opacity_box, self.text_edit,
                  self.font_box):
            w.blockSignals(True)
        self.color_btn.set_value(it.props.get("color", "#1a1a1a"))
        self.fill_btn.set_value(it.props.get("fill", ""))
        self.size_box.setValue(float(it.props.get("size", 14)))
        self.width_box.setValue(float(it.props.get("width", 1.5)))
        self.opacity_box.setValue(float(it.props.get("opacity", 1.0)))
        if it.kind in ("text", "note"):
            self.text_edit.setPlainText(str(it.props.get("text", "")))
        for w in (self.color_btn, self.fill_btn, self.size_box,
                  self.width_box, self.opacity_box, self.text_edit,
                  self.font_box):
            w.blockSignals(False)

    def _apply_style_to_selection(self, *_):
        if not self.selected:
            return
        it = self.selected
        it.props.update(self._style())
        if it.kind in ("text", "note"):
            it.props["text"] = self.text_edit.toPlainText()
        self.redraw()

    def _pick_from_list(self, row):
        items = self._page_items()
        if 0 <= row < len(items):
            self.selected = items[row]
            self._load_style(self.selected)
            self.redraw()

    def delete_selected(self):
        if not self.selected:
            return
        self.snapshot()
        self.items.remove(self.selected)
        self.selected = None
        self.redraw()

    def clear_page(self):
        if not self._page_items():
            return
        self.snapshot()
        self.items = [it for it in self.items if it.page != self.index]
        self.selected = None
        self.redraw()

    def do_undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append([it.clone() for it in self.items])
        self.items = self.undo_stack.pop()
        self.selected = None
        self.redraw()

    def do_redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append([it.clone() for it in self.items])
        self.items = self.redo_stack.pop()
        self.selected = None
        self.redraw()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected:
            self.delete_selected()
            return
        if self.selected and ev.key() in (Qt.Key_Left, Qt.Key_Right,
                                          Qt.Key_Up, Qt.Key_Down):
            step = 1 if ev.modifiers() & Qt.ShiftModifier else 5
            dx = -step if ev.key() == Qt.Key_Left else \
                step if ev.key() == Qt.Key_Right else 0
            dy = -step if ev.key() == Qt.Key_Up else \
                step if ev.key() == Qt.Key_Down else 0
            r = self.selected.rect
            self.selected.rect = [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy]
            if self.selected.kind == "ink":
                self.selected.props["strokes"] = [
                    [(px + dx, py + dy) for px, py in st]
                    for st in self.selected.props.get("strokes", [])]
            self.redraw()
            return
        super().keyPressEvent(ev)

    # ------------------------------------------------------------- writing
    def _render(self) -> fitz.Document:
        """Apply every pending item to a copy of the document."""
        out = fitz.open()
        out.insert_pdf(self.doc)
        redactions: dict[int, list] = {}
        for it in self.items:
            page = out[it.page]
            x0, x1 = sorted((it.rect[0], it.rect[2]))
            y0, y1 = sorted((it.rect[1], it.rect[3]))
            rect = fitz.Rect(x0, y0, x1, y1)
            col = parse_color(it.props.get("color", "#1a1a1a"))
            fill_raw = it.props.get("fill", "")
            fill = parse_color(fill_raw) if fill_raw else None
            op = float(it.props.get("opacity", 1.0))
            lw = float(it.props.get("width", 1.5))
            kind = it.kind

            if kind == "text":
                size = float(it.props.get("size", 14))
                box = fitz.Rect(x0, y0, max(x1, x0 + 10),
                                max(y1, y0 + size * 1.6) + size * 4)
                page.insert_textbox(box, str(it.props.get("text", "")),
                                    fontsize=size,
                                    fontname=it.props.get("font", "helv"),
                                    color=col, fill_opacity=op)
            elif kind == "stamp":
                size = float(it.props.get("size", 22))
                page.insert_text((x0, y0 + size), str(it.props.get("text", "")),
                                 fontsize=size, fontname="hebo", color=col,
                                 fill_opacity=op)
                page.draw_rect(fitz.Rect(x0 - 5, y0 - 2, x1 + 5, y0 + size * 1.3),
                               color=col, width=max(1.2, size / 14),
                               stroke_opacity=op)
            elif kind == "note":
                annot = page.add_text_annot(
                    fitz.Point(x0, y0), str(it.props.get("text", "")),
                    icon="Comment")
                annot.set_colors(stroke=parse_color("#ffd000"))
                annot.update()
            elif kind == "rect":
                page.draw_rect(rect, color=col, fill=fill, width=lw,
                               stroke_opacity=op, fill_opacity=op)
            elif kind == "ellipse":
                page.draw_oval(rect, color=col, fill=fill, width=lw,
                               stroke_opacity=op, fill_opacity=op)
            elif kind == "line":
                page.draw_line((it.rect[0], it.rect[1]),
                               (it.rect[2], it.rect[3]), color=col, width=lw,
                               stroke_opacity=op)
            elif kind == "arrow":
                shape = page.new_shape()
                shape.draw_line((it.rect[0], it.rect[1]),
                                (it.rect[2], it.rect[3]))
                from pdfbuilder.core.edit import _arrow_head
                _arrow_head(shape, (it.rect[0], it.rect[1]),
                            (it.rect[2], it.rect[3]), lw)
                shape.finish(color=col, width=lw, stroke_opacity=op)
                shape.commit()
            elif kind == "ink":
                strokes = [[(float(px), float(py)) for px, py in st]
                           for st in it.props.get("strokes", [])
                           if len(st) > 1]
                if strokes:
                    annot = page.add_ink_annot(strokes)
                    annot.set_colors(stroke=col)
                    annot.set_border(width=lw)
                    annot.set_opacity(op)
                    annot.update()
            elif kind in ("highlight", "underline", "strike"):
                method = {"highlight": "add_highlight_annot",
                          "underline": "add_underline_annot",
                          "strike": "add_strikeout_annot"}[kind]
                annot = getattr(page, method)(rect)
                annot.set_colors(stroke=col)
                annot.set_opacity(op if kind == "highlight" else 1.0)
                annot.update()
            elif kind == "image":
                path = it.props.get("path")
                if path:
                    if op < 0.999:
                        import io

                        from pdfbuilder.core.common import fade_image
                        from pdfbuilder.core.images import load_image
                        buf = io.BytesIO()
                        fade_image(load_image(path), op).save(buf, "PNG")
                        page.insert_image(rect, stream=buf.getvalue(),
                                          keep_proportion=False, alpha=-1)
                    else:
                        page.insert_image(rect, filename=path,
                                          keep_proportion=False)
            elif kind == "redact":
                redactions.setdefault(it.page, []).append(rect)

        for pno, rects in redactions.items():
            page = out[pno]
            for rect in rects:
                page.add_redact_annot(rect, fill=(0, 0, 0))
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
            except TypeError:
                page.apply_redactions()
        return out

    def preview(self):
        if not self.doc:
            return
        if not self.items:
            QtWidgets.QMessageBox.information(
                self, "Nothing to preview",
                "Add something to the page first.")
            return
        import tempfile
        doc = self._render()
        tmp = Path(tempfile.mkdtemp(prefix="pdfbuilder-preview-")) / \
            f"{self.path.stem}-preview.pdf"
        doc.save(str(tmp), garbage=3, deflate=True)
        doc.close()
        dlg = PreviewDialog(tmp, self.index, self)
        dlg.exec()

    def export(self):
        if not self.doc:
            return
        if not self.items:
            QtWidgets.QMessageBox.information(
                self, "Nothing to save",
                "No edits have been made yet.")
            return
        outdir = self.main.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        suffix = "redacted" if self.tool.id == "redact_boxes" else "edited"
        target = outdir / f"{self.path.stem}-{suffix}.pdf"
        n = 2
        while target.exists():
            target = outdir / f"{self.path.stem}-{suffix} ({n}).pdf"
            n += 1
        doc = self._render()
        save_pdf(doc, target, garbage=4, clean=True, deflate=True)
        doc.close()
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Saved")
        box.setText(f"{len(self.items)} edit(s) written to:\n{target}")
        box.addButton("Open", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("Show in files", QtWidgets.QMessageBox.ActionRole)
        box.addButton("Keep editing", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        label = box.clickedButton().text()
        if label == "Open":
            open_externally(target)
        elif label == "Show in files":
            reveal_in_files(target)


class PreviewDialog(QtWidgets.QDialog):
    def __init__(self, path, page=0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Preview - {Path(path).name}")
        self.resize(820, 900)
        lay = QtWidgets.QVBoxLayout(self)
        from pdfbuilder.ui.views.common import PageCanvas
        self.doc = fitz.open(path)
        bar = ToolBarRow()
        bar.button("‹", lambda: self.goto(self.page - 1))
        self.label = bar.label("")
        bar.button("›", lambda: self.goto(self.page + 1))
        bar.stretch()
        bar.button("Open in my PDF viewer",
                   lambda: open_externally(path))
        bar.button("Close", self.accept)
        lay.addWidget(bar)
        self.canvas = PageCanvas()
        lay.addWidget(self.canvas, 1)
        self.page = max(0, min(page, self.doc.page_count - 1))
        QtCore.QTimer.singleShot(10, lambda: self.goto(self.page))

    def goto(self, index):
        self.page = max(0, min(index, self.doc.page_count - 1))
        self.canvas.show_page(self.doc, self.page)
        self.canvas.set_zoom(self.canvas.fit_page())
        self.canvas.show_page(self.doc, self.page)
        self.label.setText(f"{self.page+1} / {self.doc.page_count}")

    def closeEvent(self, ev):
        self.doc.close()
        super().closeEvent(ev)


def build(tool, main):
    return Editor(tool, main)
