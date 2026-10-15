"""Draw new form fields onto a page: text, checkbox, radio, dropdown,
date and signature."""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.core.common import save_pdf
from pdfbuilder.core.forms import add_widget
from pdfbuilder.ui.views.common import (FilePicker, PageCanvas, ToolBarRow,
                                        open_with_prompt)
from pdfbuilder.ui.widgets import icon_label, open_externally

Qt = QtCore.Qt

KINDS = ("text", "checkbox", "radio button", "dropdown", "date", "signature")


class FieldMaker(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.doc: fitz.Document | None = None
        self.path: Path | None = None
        self.index = 0
        self.pending: list[dict] = []
        self._draft = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)
        root.addWidget(icon_label(tool.name, "h1"))
        sub = icon_label(tool.summary + "  Drag a rectangle on the page to "
                         "place a field.", "dim")
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
        top.button("Fit", self.fit, icon="margins")
        top.stretch()
        top.button("Undo last", self.undo, icon="undo")
        top.button("Clear page", self.clear_page, kind="danger", icon="trash")
        top.button("Save PDF with fields", self.export, kind="primary",
                   shortcut="Ctrl+S", icon="save")
        root.addWidget(top)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(10)
        self.canvas = PageCanvas()
        self.canvas.clicked.connect(self._press)
        self.canvas.dragged.connect(self._drag)
        self.canvas.released.connect(self._release)
        self.canvas.setCursor(Qt.CrossCursor)
        body.addWidget(self.canvas, 1)

        side = QtWidgets.QFrame()
        side.setObjectName("Card")
        side.setFixedWidth(268)
        sv = QtWidgets.QVBoxLayout(side)
        sv.setContentsMargins(10, 10, 10, 10)
        sv.setSpacing(8)
        sv.addWidget(icon_label("New field", "h2"))
        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.kind_box = QtWidgets.QComboBox()
        self.kind_box.addItems(KINDS)
        form.addRow("Type", self.kind_box)
        self.name_edit = QtWidgets.QLineEdit("field1")
        form.addRow("Name", self.name_edit)
        self.value_edit = QtWidgets.QLineEdit()
        self.value_edit.setToolTip("Starting value. Radio buttons always "
                                   "start unselected.")
        form.addRow("Default", self.value_edit)
        self.options_edit = QtWidgets.QPlainTextEdit("Option 1\nOption 2")
        self.options_edit.setMaximumHeight(70)
        form.addRow("Choices", self.options_edit)
        self.size_box = QtWidgets.QDoubleSpinBox()
        self.size_box.setRange(4, 48)
        self.size_box.setValue(10)
        self.size_box.setSuffix(" pt")
        form.addRow("Text size", self.size_box)
        self.required_box = QtWidgets.QCheckBox("Required")
        form.addRow("", self.required_box)
        self.multiline_box = QtWidgets.QCheckBox("Multi-line")
        form.addRow("", self.multiline_box)
        self.border_box = QtWidgets.QCheckBox("Draw a border")
        self.border_box.setChecked(True)
        form.addRow("", self.border_box)
        self.autoname_box = QtWidgets.QCheckBox("Auto-number names")
        self.autoname_box.setToolTip(
            "Each new field gets the next free number, so names stay unique.")
        self.autoname_box.setChecked(True)
        form.addRow("", self.autoname_box)
        sv.addLayout(form)
        sv.addWidget(icon_label("Fields queued on this page", "h2"))
        self.queue = QtWidgets.QListWidget()
        sv.addWidget(self.queue, 1)
        self.status = icon_label("", "faint")
        self.status.setWordWrap(True)
        sv.addWidget(self.status)
        body.addWidget(side)
        root.addLayout(body, 1)

        self.kind_box.currentTextChanged.connect(self._kind_changed)
        self._kind_changed(self.kind_box.currentText())

    def _kind_changed(self, kind):
        self.options_edit.setEnabled(kind in ("dropdown", "radio button"))
        self.multiline_box.setEnabled(kind == "text")

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
        self.pending.clear()
        self.index = 0
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
        self.canvas.show_page(self.doc, self.index)
        z = self.canvas.zoom
        self.queue.clear()
        for w in self.doc[self.index].widgets() or []:
            r = w.rect
            item = QtWidgets.QGraphicsRectItem(
                QtCore.QRectF(r.x0 * z, r.y0 * z, (r.x1 - r.x0) * z,
                              (r.y1 - r.y0) * z))
            item.setPen(QtGui.QPen(QtGui.QColor("#9aa2b1"), 1, Qt.DotLine))
            self.canvas.add_overlay(item)
        for f in self.pending:
            if f["page"] != self.index:
                continue
            x0, y0, x1, y1 = f["rect"]
            item = QtWidgets.QGraphicsRectItem(
                QtCore.QRectF(x0 * z, y0 * z, (x1 - x0) * z, (y1 - y0) * z))
            item.setPen(QtGui.QPen(QtGui.QColor("#3ec07a"), 1.6))
            item.setBrush(QtGui.QBrush(QtGui.QColor(62, 192, 122, 40)))
            self.canvas.add_overlay(item)
            ti = QtWidgets.QGraphicsSimpleTextItem(
                f"{f['kind']}  {f['name']}")
            ti.setBrush(QtGui.QBrush(QtGui.QColor("#3ec07a")))
            fnt = ti.font()
            fnt.setPointSizeF(max(5.0, 7.5 * z))
            ti.setFont(fnt)
            ti.setPos(x0 * z, max(0, y0 * z - 14))
            self.canvas.add_overlay(ti)
            self.queue.addItem(f"{f['kind']}  ·  {f['name']}")
        n = len([f for f in self.pending if f["page"] == self.index])
        self.status.setText(f"{len(self.pending)} field(s) queued "
                            f"({n} on this page). They are added when you "
                            f"save.")

    def _press(self, scene_pos, ev):
        if not self.doc or ev.button() != Qt.LeftButton:
            return
        x, y = self.canvas.to_pdf(scene_pos)
        self._draft = [x, y, x, y]

    def _drag(self, start, pos, ev):
        if self._draft is None:
            return
        x, y = self.canvas.to_pdf(pos)
        self._draft[2], self._draft[3] = x, y
        self.redraw()
        z = self.canvas.zoom
        x0, y0, x1, y1 = self._draft
        item = QtWidgets.QGraphicsRectItem(
            QtCore.QRectF(min(x0, x1) * z, min(y0, y1) * z,
                          abs(x1 - x0) * z, abs(y1 - y0) * z))
        item.setPen(QtGui.QPen(QtGui.QColor("#4f8cff"), 1.4, Qt.DashLine))
        self.canvas.add_overlay(item)

    def _release(self, pos, ev):
        if self._draft is None:
            return
        x, y = self.canvas.to_pdf(pos)
        x0, y0, x1, y1 = self._draft
        self._draft = None
        x1, y1 = x, y
        rect = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        if rect[2] - rect[0] < 8 or rect[3] - rect[1] < 6:
            self.status.setText("That box was too small - drag a bigger one.")
            self.redraw()
            return
        kind = self.kind_box.currentText()
        name = self.name_edit.text().strip() or "field"
        if self.autoname_box.isChecked():
            base = name.rstrip("0123456789") or "field"
            used = {f["name"] for f in self.pending}
            used |= {w.field_name for i in range(self.doc.page_count)
                     for w in (self.doc[i].widgets() or [])}
            n = 1
            while f"{base}{n}" in used:
                n += 1
            name = f"{base}{n}"
            self.name_edit.setText(name)
        self.pending.append({
            "page": self.index, "rect": rect, "kind": kind, "name": name,
            "value": self.value_edit.text(),
            "options": [o.strip() for o in
                        self.options_edit.toPlainText().splitlines()
                        if o.strip()],
            "required": self.required_box.isChecked(),
            "multiline": self.multiline_box.isChecked(),
            "fontsize": self.size_box.value(),
            "border": self.border_box.isChecked()})
        self.redraw()

    def undo(self):
        if self.pending:
            self.pending.pop()
            self.redraw()

    def clear_page(self):
        self.pending = [f for f in self.pending if f["page"] != self.index]
        self.redraw()

    def export(self):
        if not self.doc:
            return
        if not self.pending:
            QtWidgets.QMessageBox.information(
                self, "No fields queued",
                "Drag a rectangle on the page to place a field first.")
            return
        out = fitz.open()
        out.insert_pdf(self.doc)
        from pdfbuilder.job import ToolError
        try:
            for f in self.pending:
                add_widget(out[f["page"]], f["kind"], f["name"],
                           fitz.Rect(*f["rect"]), value=f["value"],
                           options=f["options"], required=f["required"],
                           multiline=f["multiline"],
                           fontsize=f["fontsize"], border=f["border"])
        except ToolError as e:
            QtWidgets.QMessageBox.warning(self, "Could not add a field",
                                          str(e))
            out.close()
            return
        outdir = self.main.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        target = outdir / f"{self.path.stem}-form.pdf"
        n = 2
        while target.exists():
            target = outdir / f"{self.path.stem}-form ({n}).pdf"
            n += 1
        save_pdf(out, target, garbage=3)
        out.close()
        count = len(self.pending)
        self.pending.clear()
        self.redraw()
        if QtWidgets.QMessageBox.question(
                self, "Saved",
                f"{count} field(s) added.\n{target}\n\nOpen it now?") \
                == QtWidgets.QMessageBox.Yes:
            open_externally(target)


def build(tool, main):
    return FieldMaker(tool, main)
