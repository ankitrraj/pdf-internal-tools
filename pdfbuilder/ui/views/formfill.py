"""Fill in an existing PDF form, field by field."""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.core.common import save_pdf
from pdfbuilder.core.forms import WIDGET_NAMES, _set_widget
from pdfbuilder.ui.views.common import (FilePicker, PageCanvas, ToolBarRow,
                                        open_with_prompt)
from pdfbuilder.ui.widgets import icon_label, open_externally

Qt = QtCore.Qt


class FormFill(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.doc: fitz.Document | None = None
        self.path: Path | None = None
        self.index = 0
        self.editors: list[tuple] = []
        # redrawing the page on every keystroke is wasteful, so coalesce
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(320)
        self._preview_timer.timeout.connect(self._live_preview)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)
        root.addWidget(icon_label(tool.name, "h1"))
        sub = icon_label(tool.summary, "dim")
        sub.setWordWrap(True)
        root.addWidget(sub)

        top = ToolBarRow(wrap=True)
        self.picker = FilePicker("Form")
        self.picker.file_chosen.connect(self.open_path)
        top.add(self.picker)
        top.sep()
        top.button("‹", lambda: self.goto(self.index - 1), icon="left")
        self.page_label = top.label("- / -")
        top.button("›", lambda: self.goto(self.index + 1), icon="right")
        top.button("Fit", self.fit, icon="margins")
        top.stretch()
        top.button("Clear all answers", self.reset_all, kind="danger", icon="refresh")
        top.button("Export answers", self.export_data, icon="export")
        top.button("Save filled PDF", lambda: self.save(False), kind="primary",
                   shortcut="Ctrl+S", icon="save")
        top.button("Save flattened", lambda: self.save(True), icon="layers",
                   tip="Save so the answers can no longer be changed")
        root.addWidget(top)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(10)
        self.canvas = PageCanvas()
        body.addWidget(self.canvas, 1)

        side = QtWidgets.QFrame()
        side.setObjectName("Card")
        side.setMinimumWidth(360)
        side.setMaximumWidth(480)
        sv = QtWidgets.QVBoxLayout(side)
        sv.setContentsMargins(10, 10, 10, 10)
        sv.setSpacing(8)
        self.fields_title = icon_label("Fields on this page", "h2")
        sv.addWidget(self.fields_title)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.host)
        self.form.setSpacing(8)
        self.form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.scroll.setWidget(self.host)
        sv.addWidget(self.scroll, 1)
        self.status = icon_label("Open a PDF form to fill it in.", "faint")
        self.status.setWordWrap(True)
        sv.addWidget(self.status)
        body.addWidget(side)
        root.addLayout(body, 1)

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
        total = sum(len(list(doc[i].widgets() or []))
                    for i in range(doc.page_count))
        if total == 0:
            self.status.setProperty("role", "warn")
            self.status.setText(
                "This PDF has no interactive form fields.\n\n"
                "Use 'Create fillable fields' to add some, or the visual "
                "editor to type straight onto the page.")
        else:
            self.status.setProperty("role", "faint")
            self.status.setText(f"{total} field(s) in this document.")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
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
        self.canvas.show_page(self.doc, self.index)
        self._build_form()
        self._outline_fields()

    def _clear_form(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.editors = []

    def _build_form(self):
        self._clear_form()
        page = self.doc[self.index]
        widgets = list(page.widgets() or [])
        self.fields_title.setText(
            f"Fields on page {self.index+1}   ({len(widgets)})")
        if not widgets:
            self.form.addRow(icon_label("No fields on this page.", "faint"))
            return
        for w in widgets:
            name = w.field_name or "(unnamed)"
            kind = w.field_type
            label = QtWidgets.QLabel(
                (w.field_label or name) +
                (" *" if w.field_flags & 2 else ""))
            label.setWordWrap(True)
            if kind == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                ed = QtWidgets.QCheckBox()
                ed.setChecked(bool(w.field_value) and
                              str(w.field_value).lower() not in
                              ("off", "false", "0", ""))
            elif kind in (fitz.PDF_WIDGET_TYPE_COMBOBOX,
                          fitz.PDF_WIDGET_TYPE_LISTBOX):
                ed = QtWidgets.QComboBox()
                ed.setEditable(kind == fitz.PDF_WIDGET_TYPE_COMBOBOX)
                ed.addItems([str(o) for o in (w.choice_values or [])])
                if w.field_value:
                    ed.setCurrentText(str(w.field_value))
            elif kind == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                ed = QtWidgets.QCheckBox("selected")
                ed.setChecked(bool(w.field_value) and
                              str(w.field_value).lower() not in
                              ("off", "false", "0", ""))
            elif _looks_like_date(name):
                ed = QtWidgets.QWidget()
                hl = QtWidgets.QHBoxLayout(ed)
                hl.setContentsMargins(0, 0, 0, 0)
                line = QtWidgets.QLineEdit(str(w.field_value or ""))
                btn = QtWidgets.QPushButton("Pick...")
                btn.clicked.connect(
                    lambda _=False, l=line: _date_dialog(self, l))
                hl.addWidget(line, 1)
                hl.addWidget(btn)
                ed.line = line                      # type: ignore
            else:
                multiline = bool(w.field_flags & 4096)
                if multiline:
                    ed = QtWidgets.QPlainTextEdit(str(w.field_value or ""))
                    ed.setMaximumHeight(86)
                else:
                    ed = QtWidgets.QLineEdit(str(w.field_value or ""))
            if w.field_flags & 1:
                ed.setEnabled(False)
                label.setToolTip("This field is read-only.")
            self.form.addRow(label, ed)
            self.editors.append((w.field_name, kind, ed))
            self._watch(ed)
        hint = icon_label("Fields marked * are required by the form.",
                          "faint")
        self.form.addRow("", hint)

    def _watch(self, ed):
        """Re-render the page shortly after a field is edited."""
        kick = self._preview_timer.start
        if isinstance(ed, QtWidgets.QCheckBox):
            ed.toggled.connect(lambda _=False: kick())
        elif isinstance(ed, QtWidgets.QComboBox):
            ed.currentTextChanged.connect(lambda _="": kick())
            if ed.isEditable():
                ed.lineEdit().textEdited.connect(lambda _="": kick())
        elif isinstance(ed, QtWidgets.QPlainTextEdit):
            ed.textChanged.connect(kick)
        elif hasattr(ed, "line"):
            ed.line.textChanged.connect(lambda _="": kick())
        elif isinstance(ed, QtWidgets.QLineEdit):
            ed.textChanged.connect(lambda _="": kick())

    def _live_preview(self):
        """Write the current answers into the document and redraw the page."""
        if not self.doc:
            return
        self._collect()
        self.canvas.show_page(self.doc, self.index)
        self._outline_fields()

    def _outline_fields(self):
        z = self.canvas.zoom
        page = self.doc[self.index]
        for w in page.widgets() or []:
            r = w.rect
            item = QtWidgets.QGraphicsRectItem(
                QtCore.QRectF(r.x0 * z, r.y0 * z, (r.x1 - r.x0) * z,
                              (r.y1 - r.y0) * z))
            item.setPen(QtGui.QPen(QtGui.QColor("#4f8cff"), 1.2))
            item.setBrush(QtGui.QBrush(QtGui.QColor(79, 140, 255, 26)))
            self.canvas.add_overlay(item)

    def _collect(self) -> int:
        """Write the editor values into the live document."""
        if not self.doc:
            return 0
        page = self.doc[self.index]
        by_name = {w.field_name: w for w in (page.widgets() or [])}
        applied = 0
        for name, kind, ed in self.editors:
            w = by_name.get(name)
            if w is None or not ed.isEnabled():
                continue
            if isinstance(ed, QtWidgets.QCheckBox):
                val = ed.isChecked()
            elif isinstance(ed, QtWidgets.QComboBox):
                val = ed.currentText()
            elif isinstance(ed, QtWidgets.QPlainTextEdit):
                val = ed.toPlainText()
            elif hasattr(ed, "line"):
                val = ed.line.text()
            else:
                val = ed.text()
            if _set_widget(w, val):
                applied += 1
        return applied

    def reset_all(self):
        if not self.doc:
            return
        if QtWidgets.QMessageBox.question(
                self, "Clear the form",
                "Clear every answer in this document?") \
                != QtWidgets.QMessageBox.Yes:
            return
        for i in range(self.doc.page_count):
            for w in self.doc[i].widgets() or []:
                if w.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                    _set_widget(w, False)
                else:
                    _set_widget(w, "")
        self.goto(self.index)
        self.status.setText("All answers cleared.")

    def save(self, flatten: bool):
        if not self.doc:
            return
        self._collect()
        outdir = self.main.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        tag = "completed" if flatten else "filled"
        target = outdir / f"{self.path.stem}-{tag}.pdf"
        n = 2
        while target.exists():
            target = outdir / f"{self.path.stem}-{tag} ({n}).pdf"
            n += 1
        out = fitz.open()
        out.insert_pdf(self.doc)
        if flatten:
            from pdfbuilder.core.layout import _burn_widget
            for i in range(out.page_count):
                for w in list(out[i].widgets() or []):
                    _burn_widget(out[i], w)
        save_pdf(out, target, garbage=3, deflate=True)
        out.close()
        self.status.setProperty("role", "good")
        self.status.setText(f"Saved {target}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        if QtWidgets.QMessageBox.question(
                self, "Saved", f"Written to:\n{target}\n\nOpen it now?") \
                == QtWidgets.QMessageBox.Yes:
            open_externally(target)

    def export_data(self):
        if not self.doc:
            return
        self._collect()
        import csv
        import json
        rows = []
        for i in range(self.doc.page_count):
            for w in self.doc[i].widgets() or []:
                rows.append({"page": i + 1, "field": w.field_name or "",
                             "type": WIDGET_NAMES.get(w.field_type, "?"),
                             "value": w.field_value})
        if not rows:
            QtWidgets.QMessageBox.information(self, "No fields",
                                              "There is nothing to export.")
            return
        dest, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export answers",
            str(self.main.outdir / f"{self.path.stem}-answers.csv"),
            "CSV file (*.csv);;JSON file (*.json)")
        if not dest:
            return
        if dest.lower().endswith(".json"):
            Path(dest).write_text(json.dumps(
                {r["field"]: r["value"] for r in rows}, indent=2,
                default=str), encoding="utf-8")
        else:
            with open(dest, "w", newline="", encoding="utf-8") as fh:
                wr = csv.DictWriter(fh, fieldnames=["page", "field", "type",
                                                    "value"])
                wr.writeheader()
                wr.writerows(rows)
        self.status.setText(f"Answers written to {dest}")


def _looks_like_date(name: str) -> bool:
    return any(k in (name or "").lower() for k in ("date", "dob", "dated"))


def _date_dialog(parent, line_edit):
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("Choose a date")
    lay = QtWidgets.QVBoxLayout(dlg)
    cal = QtWidgets.QCalendarWidget()
    lay.addWidget(cal)
    row = QtWidgets.QHBoxLayout()
    fmt = QtWidgets.QComboBox()
    fmt.addItems(["dd/MM/yyyy", "MM/dd/yyyy", "yyyy-MM-dd", "d MMMM yyyy"])
    row.addWidget(QtWidgets.QLabel("Format"))
    row.addWidget(fmt, 1)
    lay.addLayout(row)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)
    if dlg.exec() == QtWidgets.QDialog.Accepted:
        line_edit.setText(cal.selectedDate().toString(fmt.currentText()))


def build(tool, main):
    return FormFill(tool, main)
