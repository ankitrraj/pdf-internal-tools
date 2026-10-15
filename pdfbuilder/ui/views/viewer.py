"""Document viewer: scroll, zoom, fit, search, print, save pages."""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.ui.views.common import (FilePicker, PageCanvas, PageStrip,
                                        ToolBarRow, open_with_prompt)
from pdfbuilder.ui.widgets import icon_label, open_externally, print_file

Qt = QtCore.Qt


class Viewer(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.doc = None
        self.path: Path | None = None
        self.index = 0
        self.hits: list[tuple[int, object]] = []
        self.hit_pos = -1
        self.fit_mode = "width"

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(9)

        top = ToolBarRow(wrap=True)
        self.picker = FilePicker("Document")
        self.picker.file_chosen.connect(self.open_path)
        top.add(self.picker)
        top.sep()
        top.button("‹", lambda: self.goto(self.index - 1), tip="Previous page",
                   shortcut="PgUp")
        self.page_spin = QtWidgets.QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(74)
        self.page_spin.valueChanged.connect(lambda v: self.goto(v - 1))
        top.add(self.page_spin)
        self.page_total = top.label("/ 0")
        top.button("›", lambda: self.goto(self.index + 1), tip="Next page",
                   shortcut="PgDown")
        top.sep()
        top.button("−", lambda: self.scale(1 / 1.2), tip="Zoom out",
                   shortcut="Ctrl+-")
        self.zoom_label = top.label("100%")
        top.button("+", lambda: self.scale(1.2), tip="Zoom in",
                   shortcut="Ctrl+=")
        top.button("Fit width", lambda: self.set_fit("width"), icon="resize")
        top.button("Fit page", lambda: self.set_fit("page"), icon="margins")
        top.button("100%", lambda: self.set_fit("actual"))
        top.stretch()
        root.addWidget(top)

        search_row = ToolBarRow(wrap=True)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Find in this document...   (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.find_next)
        self.search.textChanged.connect(self._search_changed)
        search_row.add(self.search)
        search_row.button("Find", self.run_search, shortcut="Ctrl+F")
        search_row.button("Previous", self.find_prev, icon="left")
        search_row.button("Next", self.find_next, shortcut="F3")
        self.hit_label = search_row.label("")
        search_row.stretch()
        search_row.button("Print", self.print_doc, tip="Print this document",
                          shortcut="Ctrl+P")
        search_row.button("Save this page", self.save_page, icon="save")
        search_row.button("Open elsewhere", self.open_external, icon="open")
        root.addWidget(search_row)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(10)
        self.strip = PageStrip()
        self.strip.page_chosen.connect(self.goto)
        body.addWidget(self.strip)
        self.canvas = PageCanvas()
        self.canvas.zoom_changed.connect(self._zoom_applied)
        body.addWidget(self.canvas, 1)
        root.addLayout(body, 1)

        self.status = icon_label("Open a PDF to start reading.", "faint")
        root.addWidget(self.status)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------- loading
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
        self.page_spin.setMaximum(max(1, doc.page_count))
        self.page_total.setText(f"/ {doc.page_count}")
        self.strip.load(doc)
        self.set_fit(self.fit_mode)
        meta = doc.metadata or {}
        self.status.setText(
            f"{self.path.name}  ·  {doc.page_count} page(s)"
            + (f"  ·  {meta.get('title')}" if meta.get("title") else ""))

    def goto(self, index: int):
        if not self.doc:
            return
        index = max(0, min(index, self.doc.page_count - 1))
        self.index = index
        self.canvas.show_page(self.doc, index)
        self._draw_hits()
        for w, v in ((self.page_spin, index + 1), (self.strip, index)):
            w.blockSignals(True)
            if w is self.page_spin:
                w.setValue(v)
            else:
                w.setCurrentRow(v)
            w.blockSignals(False)

    # ---------------------------------------------------------------- zoom
    def scale(self, factor):
        self.fit_mode = "manual"
        self.canvas.set_zoom(self.canvas.zoom * factor)
        self.goto(self.index)

    def set_fit(self, mode):
        if not self.doc:
            return
        self.fit_mode = mode
        self.canvas.show_page(self.doc, self.index)
        zoom = {"width": self.canvas.fit_width, "page": self.canvas.fit_page,
                "actual": lambda: 1.0}.get(mode, lambda: self.canvas.zoom)()
        self.canvas.set_zoom(zoom)
        self.goto(self.index)

    def _zoom_applied(self, zoom):
        self.zoom_label.setText(f"{zoom*100:.0f}%")

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.doc and self.fit_mode in ("width", "page"):
            QtCore.QTimer.singleShot(60, lambda: self.set_fit(self.fit_mode))

    # -------------------------------------------------------------- search
    def _search_changed(self):
        self.hits = []
        self.hit_pos = -1
        self.hit_label.setText("")

    def run_search(self):
        if not self.doc:
            return
        term = self.search.text().strip()
        if not term:
            self.search.setFocus()
            return
        self.hits = []
        for i in range(self.doc.page_count):
            for rect in self.doc[i].search_for(term) or []:
                self.hits.append((i, rect))
        self.hit_pos = -1
        if not self.hits:
            self.hit_label.setProperty("role", "warn")
            self.hit_label.setText("no matches")
            self.hit_label.style().unpolish(self.hit_label)
            self.hit_label.style().polish(self.hit_label)
            self.status.setText(
                f"'{term}' was not found. If this document is a scan, run "
                f"Scan & OCR → 'Make a scanned PDF searchable' first.")
            return
        self.hit_label.setProperty("role", "good")
        self.hit_label.style().unpolish(self.hit_label)
        self.hit_label.style().polish(self.hit_label)
        self.find_next()

    def find_next(self):
        if not self.hits:
            self.run_search()
            return
        self.hit_pos = (self.hit_pos + 1) % len(self.hits)
        self._show_hit()

    def find_prev(self):
        if not self.hits:
            self.run_search()
            return
        self.hit_pos = (self.hit_pos - 1) % len(self.hits)
        self._show_hit()

    def _show_hit(self):
        page, rect = self.hits[self.hit_pos]
        self.hit_label.setText(f"{self.hit_pos+1} of {len(self.hits)}")
        self.goto(page)
        z = self.canvas.zoom
        self.canvas.centerOn((rect.x0 + rect.x1) / 2 * z,
                             (rect.y0 + rect.y1) / 2 * z)

    def _draw_hits(self):
        if not self.hits:
            return
        z = self.canvas.zoom
        pen = QtGui.QPen(QtGui.QColor(255, 180, 0, 230), 1.4)
        brush = QtGui.QBrush(QtGui.QColor(255, 214, 10, 86))
        cur_pen = QtGui.QPen(QtGui.QColor(255, 90, 0, 255), 2.0)
        for n, (page, rect) in enumerate(self.hits):
            if page != self.index:
                continue
            item = QtWidgets.QGraphicsRectItem(
                QtCore.QRectF(rect.x0 * z, rect.y0 * z,
                              (rect.x1 - rect.x0) * z,
                              (rect.y1 - rect.y0) * z))
            item.setPen(cur_pen if n == self.hit_pos else pen)
            item.setBrush(brush)
            self.canvas.add_overlay(item)

    # ------------------------------------------------------------- actions
    def print_doc(self):
        if not self.path:
            return
        if not print_file(self.path, self):
            QtWidgets.QMessageBox.information(
                self, "Print",
                "No printing command was found on this system.\n\n"
                "Install CUPS (sudo apt install cups) or open the file in your "
                "document viewer and print from there.")

    def save_page(self):
        if not self.doc:
            return
        import pymupdf as fitz
        dest, kind = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save this page",
            str(Path.home() / f"{self.path.stem}-page{self.index+1}.pdf"),
            "PDF file (*.pdf);;PNG image (*.png);;JPEG image (*.jpg)")
        if not dest:
            return
        ext = Path(dest).suffix.lower()
        if ext == ".pdf":
            part = fitz.open()
            part.insert_pdf(self.doc, from_page=self.index, to_page=self.index)
            part.save(dest)
            part.close()
        else:
            pix = self.doc[self.index].get_pixmap(dpi=200)
            if ext == ".png":
                pix.save(dest)
            else:
                from PIL import Image
                Image.frombytes("RGB" if pix.n >= 3 else "L",
                                (pix.width, pix.height),
                                pix.samples).save(dest, quality=92)
        self.status.setText(f"Saved {dest}")

    def open_external(self):
        if self.path:
            open_externally(self.path)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space):
            self.goto(self.index + 1)
        elif ev.key() in (Qt.Key_Left, Qt.Key_Up):
            self.goto(self.index - 1)
        elif ev.key() == Qt.Key_Home:
            self.goto(0)
        elif ev.key() == Qt.Key_End and self.doc:
            self.goto(self.doc.page_count - 1)
        else:
            super().keyPressEvent(ev)


def build(tool, main):
    return Viewer(tool, main)
