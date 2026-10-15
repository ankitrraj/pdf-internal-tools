"""Sign a PDF: draw with the mouse, type a signature, or import an image,
then place it on the page with an optional date and printed name."""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.core.common import save_pdf
from pdfbuilder.ui.views.common import (FilePicker, PageCanvas, ToolBarRow,
                                        open_with_prompt)
from pdfbuilder.ui import icons
from pdfbuilder.ui.widgets import ColorButton, icon_label, open_externally

Qt = QtCore.Qt

SIG_DIR = Path.home() / ".config" / "pdf-builder" / "signatures"

SCRIPT_FONTS = ["Caveat", "Dancing Script", "Segoe Script", "Lucida "
                "Handwriting", "URW Chancery L", "Z003", "DejaVu Sans",
                "Liberation Serif"]


class SignaturePad(QtWidgets.QWidget):
    """Freehand drawing surface."""
    drawn = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self.setCursor(Qt.CrossCursor)
        self.strokes: list[list[QtCore.QPointF]] = []
        self.pen_width = 2.6
        self.pen_color = QtGui.QColor("#101418")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: white; border: 1px dashed #9aa2b1;"
                           "border-radius: 8px;")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.strokes.append([ev.position()])
            self.update()

    def mouseMoveEvent(self, ev):
        if self.strokes and ev.buttons() & Qt.LeftButton:
            self.strokes[-1].append(ev.position())
            self.update()

    def mouseReleaseEvent(self, ev):
        self.drawn.emit()

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if not self.strokes:
            p.setPen(QtGui.QColor("#aab1bd"))
            p.drawText(self.rect().adjusted(14, 0, -14, 0),
                       Qt.AlignCenter | Qt.TextWordWrap,
                       "Draw your signature here\nwith the mouse or a stylus")
            return
        pen = QtGui.QPen(self.pen_color, self.pen_width, Qt.SolidLine,
                         Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        for stroke in self.strokes:
            if len(stroke) < 2:
                if stroke:
                    p.drawPoint(stroke[0])
                continue
            path = QtGui.QPainterPath(stroke[0])
            for pt in stroke[1:]:
                path.lineTo(pt)
            p.drawPath(path)

    def clear(self):
        self.strokes = []
        self.update()

    def is_empty(self) -> bool:
        return not any(len(s) > 1 for s in self.strokes)

    def to_image(self, scale: int = 3) -> QtGui.QImage:
        """Render the ink onto a transparent, tightly cropped image."""
        pts = [pt for s in self.strokes for pt in s]
        if not pts:
            return QtGui.QImage()
        pad = self.pen_width * 2 + 4
        x0 = min(p.x() for p in pts) - pad
        y0 = min(p.y() for p in pts) - pad
        x1 = max(p.x() for p in pts) + pad
        y1 = max(p.y() for p in pts) + pad
        w, h = max(1, int((x1 - x0) * scale)), max(1, int((y1 - y0) * scale))
        img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
        img.fill(QtGui.QColor(0, 0, 0, 0))
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(scale, scale)
        p.translate(-x0, -y0)
        p.setPen(QtGui.QPen(self.pen_color, self.pen_width, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        for stroke in self.strokes:
            if len(stroke) < 2:
                continue
            path = QtGui.QPainterPath(stroke[0])
            for pt in stroke[1:]:
                path.lineTo(pt)
            p.drawPath(path)
        p.end()
        return img


class SignPanel(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.doc: fitz.Document | None = None
        self.path: Path | None = None
        self.index = 0
        self.sig_image: QtGui.QImage | None = None
        self.placement: list[float] | None = None     # x0,y0,x1,y1 in points

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)
        root.addWidget(icon_label(tool.name, "h1"))
        sub = icon_label("Create a signature on the right, then click or drag "
                         "on the page to place it.", "dim")
        sub.setWordWrap(True)
        root.addWidget(sub)

        top = ToolBarRow(wrap=True)
        self.picker = FilePicker("Document")
        self.picker.file_chosen.connect(self.open_path)
        top.add(self.picker)
        top.sep()
        top.button("‹", lambda: self.goto(self.index - 1), icon="left")
        self.page_label = top.label("- / -")
        top.button("›", lambda: self.goto(self.index + 1), icon="right")
        top.button("Last page", lambda: self.goto(10 ** 6), icon="last")
        top.button("Fit", self.fit, icon="margins")
        top.stretch()
        top.button("Remove placement", self.clear_placement, icon="eraser")
        top.button("Sign and save", self.export, kind="primary", shortcut="Ctrl+S",
                   icon="signature")
        root.addWidget(top)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(10)
        self.canvas = PageCanvas()
        self.canvas.clicked.connect(self._press)
        self.canvas.dragged.connect(self._drag)
        self.canvas.released.connect(self._release)
        body.addWidget(self.canvas, 1)

        side = QtWidgets.QFrame()
        side.setObjectName("Card")
        side.setFixedWidth(330)
        sv = QtWidgets.QVBoxLayout(side)
        sv.setContentsMargins(10, 10, 10, 10)
        sv.setSpacing(8)

        self.tabs = QtWidgets.QTabWidget()
        # --- draw
        draw_tab = QtWidgets.QWidget()
        dv = QtWidgets.QVBoxLayout(draw_tab)
        self.pad = SignaturePad()
        self.pad.drawn.connect(self._pad_drawn)
        dv.addWidget(self.pad)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Ink"))
        self.ink_color = ColorButton("#101418", allow_empty=False)
        self.ink_color.changed.connect(
            lambda c: (setattr(self.pad, "pen_color",
                               QtGui.QColor(c or "#101418")),
                       self.pad.update()))
        row.addWidget(self.ink_color)
        self.ink_width = QtWidgets.QDoubleSpinBox()
        self.ink_width.setRange(0.5, 10)
        self.ink_width.setValue(2.6)
        self.ink_width.setSuffix(" pt")
        self.ink_width.valueChanged.connect(
            lambda v: (setattr(self.pad, "pen_width", v), self.pad.update()))
        row.addWidget(self.ink_width)
        clear = QtWidgets.QPushButton("Clear")
        clear.clicked.connect(self.pad.clear)
        row.addWidget(clear)
        dv.addLayout(row)
        use = QtWidgets.QPushButton("Use this drawing")
        use.setProperty("kind", "primary")
        use.clicked.connect(self._use_drawing)
        dv.addWidget(use)
        self.tabs.addTab(draw_tab, icons.ic("ink", 16), "Draw")

        # --- type
        type_tab = QtWidgets.QWidget()
        tv = QtWidgets.QVBoxLayout(type_tab)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Type your name")
        tv.addWidget(self.name_edit)
        self.font_box = QtWidgets.QComboBox()
        available = set(QtGui.QFontDatabase.families())
        for f in SCRIPT_FONTS:
            if f in available:
                self.font_box.addItem(f)
        if self.font_box.count() == 0:
            self.font_box.addItems(sorted(available)[:40])
        tv.addWidget(self.font_box)
        self.type_size = QtWidgets.QSpinBox()
        self.type_size.setRange(14, 200)
        self.type_size.setValue(58)
        self.type_size.setSuffix(" px")
        tv.addWidget(self.type_size)
        self.type_preview = QtWidgets.QLabel()
        self.type_preview.setMinimumHeight(96)
        self.type_preview.setAlignment(Qt.AlignCenter)
        self.type_preview.setStyleSheet(
            "background:white;border:1px dashed #9aa2b1;border-radius:8px;"
            "color:#101418;")
        tv.addWidget(self.type_preview)
        for w in (self.name_edit, self.font_box, self.type_size):
            sig = (w.textChanged if isinstance(w, QtWidgets.QLineEdit)
                   else w.currentTextChanged
                   if isinstance(w, QtWidgets.QComboBox) else w.valueChanged)
            sig.connect(self._update_typed_preview)
        use2 = QtWidgets.QPushButton("Use this signature")
        use2.setProperty("kind", "primary")
        use2.clicked.connect(self._use_typed)
        tv.addWidget(use2)
        self.tabs.addTab(type_tab, icons.ic("text", 16), "Type")

        # --- image
        img_tab = QtWidgets.QWidget()
        iv = QtWidgets.QVBoxLayout(img_tab)
        iv.addWidget(icon_label("Use a photo or scan of your signature. A "
                                "PNG with a transparent background works "
                                "best.", "faint"))
        pick = QtWidgets.QPushButton("Choose an image...")
        pick.clicked.connect(self._pick_image)
        iv.addWidget(pick)
        self.img_preview = QtWidgets.QLabel()
        self.img_preview.setMinimumHeight(120)
        self.img_preview.setAlignment(Qt.AlignCenter)
        self.img_preview.setStyleSheet(
            "background:white;border:1px dashed #9aa2b1;border-radius:8px;")
        iv.addWidget(self.img_preview)
        self.knock_box = QtWidgets.QCheckBox("Make the white background "
                                             "transparent")
        self.knock_box.setChecked(True)
        iv.addWidget(self.knock_box)
        iv.addStretch(1)
        self.tabs.addTab(img_tab, icons.ic("picture", 16), "Image")
        sv.addWidget(self.tabs)

        sv.addWidget(icon_label("Placement", "h2"))
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.width_box = QtWidgets.QDoubleSpinBox()
        self.width_box.setRange(10, 400)
        self.width_box.setValue(55)
        self.width_box.setSuffix(" mm")
        self.width_box.valueChanged.connect(self.redraw)
        form.addRow("Width", self.width_box)
        self.date_box = QtWidgets.QCheckBox("Add today's date")
        self.date_box.setChecked(True)
        form.addRow("", self.date_box)
        self.printed_edit = QtWidgets.QLineEdit()
        self.printed_edit.setPlaceholderText("optional printed name")
        form.addRow("Printed name", self.printed_edit)
        self.flatten_box = QtWidgets.QCheckBox("Flatten into the page")
        self.flatten_box.setToolTip(
            "The signature becomes part of the page and cannot be moved or "
            "deleted afterwards.")
        self.flatten_box.setChecked(True)
        form.addRow("", self.flatten_box)
        self.all_pages = QtWidgets.QCheckBox("Place on every page")
        form.addRow("", self.all_pages)
        sv.addLayout(form)

        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Save signature for later")
        b.clicked.connect(self._save_sig)
        row.addWidget(b)
        b2 = QtWidgets.QPushButton("Load saved...")
        b2.clicked.connect(self._load_sig)
        row.addWidget(b2)
        sv.addLayout(row)
        self.status = icon_label("", "faint")
        self.status.setWordWrap(True)
        sv.addWidget(self.status)
        body.addWidget(side)
        root.addLayout(body, 1)
        self._update_typed_preview()

    # ----------------------------------------------------------- signature
    def _pad_drawn(self):
        self.status.setText("Press 'Use this drawing' when you are happy "
                            "with it.")

    def _use_drawing(self):
        if self.pad.is_empty():
            self.status.setText("Draw something on the white pad first.")
            return
        self.sig_image = self.pad.to_image()
        self.status.setProperty("role", "good")
        self.status.setText("Signature ready - now click on the page to "
                            "place it.")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.redraw()

    def _typed_image(self) -> QtGui.QImage:
        text = self.name_edit.text().strip()
        if not text:
            return QtGui.QImage()
        font = QtGui.QFont(self.font_box.currentText(),
                           self.type_size.value())
        font.setStyleStrategy(QtGui.QFont.PreferAntialias)
        fm = QtGui.QFontMetrics(font)
        rect = fm.boundingRect(text)
        pad = max(10, self.type_size.value() // 4)
        img = QtGui.QImage(rect.width() + 2 * pad, rect.height() + 2 * pad,
                           QtGui.QImage.Format_ARGB32)
        img.fill(QtGui.QColor(0, 0, 0, 0))
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)
        p.setFont(font)
        p.setPen(QtGui.QColor(self.ink_color.value() or "#101418"))
        p.drawText(pad - rect.left(), pad - rect.top(), text)
        p.end()
        return img

    def _update_typed_preview(self, *_):
        img = self._typed_image()
        if img.isNull():
            self.type_preview.setText("Your typed signature appears here")
            self.type_preview.setPixmap(QtGui.QPixmap())
            return
        pm = QtGui.QPixmap.fromImage(img).scaled(
            self.type_preview.width() - 12, self.type_preview.height() - 12,
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.type_preview.setPixmap(pm)

    def _use_typed(self):
        img = self._typed_image()
        if img.isNull():
            self.status.setText("Type your name first.")
            return
        self.sig_image = img
        self.status.setText("Signature ready - click on the page to place it.")
        self.redraw()

    def _pick_image(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a signature image", str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif);;All files (*)")
        if not path:
            return
        from pdfbuilder.core.forms import _knock_out_white
        from pdfbuilder.core.images import load_image
        try:
            img = load_image(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Image", str(e))
            return
        if self.knock_box.isChecked():
            img = _knock_out_white(img)
        img = img.convert("RGBA")
        qi = QtGui.QImage(img.tobytes("raw", "RGBA"), img.width, img.height,
                          QtGui.QImage.Format_RGBA8888).copy()
        self.sig_image = qi
        self.img_preview.setPixmap(QtGui.QPixmap.fromImage(qi).scaled(
            self.img_preview.width() - 12, self.img_preview.height() - 12,
            Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.status.setText("Signature ready - click on the page to place it.")
        self.redraw()

    def _save_sig(self):
        if self.sig_image is None or self.sig_image.isNull():
            self.status.setText("Create a signature first.")
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save signature", "Name this signature:", text="My signature")
        if not ok or not name.strip():
            return
        SIG_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in name if c.isalnum() or c in " -_").strip()
        self.sig_image.save(str(SIG_DIR / f"{safe}.png"))
        self.status.setText(f"Saved as {safe}.png")

    def _load_sig(self):
        SIG_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(SIG_DIR.glob("*.png"))
        if not files:
            QtWidgets.QMessageBox.information(
                self, "No saved signatures",
                "Create a signature and use 'Save signature for later'.")
            return
        name, ok = QtWidgets.QInputDialog.getItem(
            self, "Load a signature", "Saved signatures:",
            [f.stem for f in files], 0, False)
        if not ok:
            return
        img = QtGui.QImage(str(SIG_DIR / f"{name}.png"))
        if img.isNull():
            return
        self.sig_image = img
        self.status.setText("Loaded - click on the page to place it.")
        self.redraw()

    # ---------------------------------------------------------------- doc
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
        self.index = doc.page_count - 1          # signatures usually go last
        self.placement = None
        self.fit()

    def fit(self):
        if not self.doc:
            return
        self.canvas.show_page(self.doc, self.index)
        self.canvas.set_zoom(self.canvas.fit_page())
        self.goto(self.index)

    def goto(self, index):
        if not self.doc:
            return
        self.index = max(0, min(index, self.doc.page_count - 1))
        self.page_label.setText(f"{self.index+1} / {self.doc.page_count}")
        self.redraw()

    def redraw(self):
        if not self.doc:
            return
        self.canvas.show_page(self.doc, self.index)
        if self.placement and self.sig_image is not None:
            z = self.canvas.zoom
            x0, y0, x1, y1 = self.placement
            pm = QtGui.QPixmap.fromImage(self.sig_image).scaled(
                max(1, int((x1 - x0) * z)), max(1, int((y1 - y0) * z)),
                Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            item = QtWidgets.QGraphicsPixmapItem(pm)
            item.setPos(x0 * z, y0 * z)
            self.canvas.add_overlay(item)
            frame = QtWidgets.QGraphicsRectItem(
                QtCore.QRectF(x0 * z, y0 * z, (x1 - x0) * z, (y1 - y0) * z))
            frame.setPen(QtGui.QPen(QtGui.QColor("#4f8cff"), 1.2,
                                    Qt.DashLine))
            self.canvas.add_overlay(frame)

    def _mm(self, mm: float) -> float:
        return mm * 72.0 / 25.4

    def _press(self, scene_pos, ev):
        if not self.doc or self.sig_image is None or self.sig_image.isNull():
            if self.doc:
                self.status.setText("Create a signature first, then click on "
                                    "the page.")
            return
        x, y = self.canvas.to_pdf(scene_pos)
        w = self._mm(self.width_box.value())
        h = w * self.sig_image.height() / max(1, self.sig_image.width())
        self.placement = [x, y, x + w, y + h]
        self.redraw()

    def _drag(self, start, pos, ev):
        if self.placement is None or self.sig_image is None:
            return
        x0, y0 = self.canvas.to_pdf(start)
        x1, y1 = self.canvas.to_pdf(pos)
        w = max(self._mm(10), abs(x1 - x0))
        h = w * self.sig_image.height() / max(1, self.sig_image.width())
        self.placement = [min(x0, x1), min(y0, y1), min(x0, x1) + w,
                          min(y0, y1) + h]
        self.width_box.blockSignals(True)
        self.width_box.setValue(w * 25.4 / 72)
        self.width_box.blockSignals(False)
        self.redraw()

    def _release(self, pos, ev):
        if self.placement:
            self.status.setText("Placed. Drag again to resize, or press "
                                "'Sign and save'.")

    def clear_placement(self):
        self.placement = None
        self.redraw()

    # ------------------------------------------------------------- export
    def export(self):
        import datetime
        if not self.doc:
            return
        if self.sig_image is None or self.sig_image.isNull():
            QtWidgets.QMessageBox.information(
                self, "No signature yet",
                "Draw, type or import a signature first.")
            return
        if not self.placement:
            QtWidgets.QMessageBox.information(
                self, "Where should it go?",
                "Click on the page to position the signature.")
            return
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="pdfbuilder-sig-")) / "sig.png"
        self.sig_image.save(str(tmp))
        data = tmp.read_bytes()

        out = fitz.open()
        out.insert_pdf(self.doc)
        pages = (range(out.page_count) if self.all_pages.isChecked()
                 else [self.index])
        x0, y0, x1, y1 = self.placement
        today = datetime.date.today().strftime("%d %B %Y")
        for pno in pages:
            page = out[pno]
            page.insert_image(fitz.Rect(x0, y0, x1, y1), stream=data,
                              keep_proportion=True, overlay=True)
            ty = y1 + 11
            if self.date_box.isChecked():
                page.insert_text((x0, ty), today, fontsize=9, fontname="helv",
                                 color=(0.2, 0.2, 0.2))
                ty += 12
            printed = self.printed_edit.text().strip()
            if printed:
                page.insert_text((x0, ty), printed, fontsize=9,
                                 fontname="helv", color=(0.2, 0.2, 0.2))
        if self.flatten_box.isChecked():
            for pno in pages:
                for w in list(out[pno].widgets() or []):
                    from pdfbuilder.core.layout import _burn_widget
                    _burn_widget(out[pno], w)
        outdir = self.main.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        target = outdir / f"{self.path.stem}-signed.pdf"
        n = 2
        while target.exists():
            target = outdir / f"{self.path.stem}-signed ({n}).pdf"
            n += 1
        save_pdf(out, target, garbage=3, deflate=True)
        out.close()
        self.status.setProperty("role", "good")
        self.status.setText(f"Saved {target}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        if QtWidgets.QMessageBox.question(
                self, "Signed", f"Written to:\n{target}\n\nOpen it now?") \
                == QtWidgets.QMessageBox.Yes:
            open_externally(target)


def build(tool, main):
    return SignPanel(tool, main)
