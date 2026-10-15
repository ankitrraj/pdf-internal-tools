"""Visual page organiser: drag to reorder, rotate, duplicate, delete,
insert blanks or another PDF, then export."""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.core.common import fmt_pages, save_pdf
from pdfbuilder.ui.views.common import (FilePicker, ToolBarRow,
                                        open_with_prompt, thumb_pixmap)
from pdfbuilder.ui.widgets import icon_label, open_externally

Qt = QtCore.Qt


class PageGrid(QtWidgets.QListWidget):
    """Thumbnail grid whose order is the document's page order."""
    order_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QtWidgets.QListWidget.IconMode)
        self.setIconSize(QtCore.QSize(150, 190))
        self.setGridSize(QtCore.QSize(176, 238))
        self.setResizeMode(QtWidgets.QListWidget.Adjust)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setSpacing(6)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.model().rowsMoved.connect(lambda *a: self.order_changed.emit())


class Organizer(QtWidgets.QWidget):
    """Model: a list of (source_index, rotation) entries we can reshuffle."""

    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.tool = tool
        self.doc: fitz.Document | None = None
        self.path: Path | None = None
        self.extra_docs: list[fitz.Document] = []
        self.entries: list[dict] = []
        self._uid = 0
        self.undo: list[list[dict]] = []
        self.redo: list[list[dict]] = []
        self._pix_cache: dict[tuple, QtGui.QPixmap] = {}

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(9)

        head = QtWidgets.QHBoxLayout()
        head.addWidget(icon_label(tool.name, "h1"))
        head.addStretch(1)
        root.addLayout(head)
        sub = icon_label(tool.summary, "dim")
        sub.setWordWrap(True)
        root.addWidget(sub)

        row1 = ToolBarRow(wrap=True)
        self.picker = FilePicker("Document")
        self.picker.file_chosen.connect(self.open_path)
        row1.add(self.picker)
        row1.stretch()
        row1.button("Select all", lambda: self.grid.selectAll(),
                    shortcut="Ctrl+A")
        row1.button("Select none", lambda: self.grid.clearSelection(), icon="close")
        row1.button("Odd pages", lambda: self.select_parity(0))
        row1.button("Even pages", lambda: self.select_parity(1))
        root.addWidget(row1)

        row2 = ToolBarRow(wrap=True)
        row2.button("Rotate left", lambda: self.rotate(-90), tip="Rotate the "
                    "selected pages 90° anticlockwise")
        row2.button("Rotate right", lambda: self.rotate(90), icon="rotate_cw")
        row2.button("Rotate 180°", lambda: self.rotate(180), icon="rotate_180")
        row2.sep()
        row2.button("Move left", lambda: self.move(-1), icon="left")
        row2.button("Move right", lambda: self.move(1), icon="right")
        row2.button("To front", lambda: self.move_edge(True), icon="first")
        row2.button("To end", lambda: self.move_edge(False), icon="last")
        row2.sep()
        row2.button("Duplicate", self.duplicate, icon="copy")
        row2.button("Delete", self.delete, kind="danger", shortcut="Del", icon="trash")
        row2.button("Reverse all", self.reverse, icon="reverse")
        row2.sep()
        row2.button("Insert blank", self.insert_blank, icon="blank")
        row2.button("Insert from PDF...", self.insert_pdf, icon="insert")
        row2.stretch()
        row2.button("Undo", self.do_undo, shortcut="Ctrl+Z")
        row2.button("Redo", self.do_redo, shortcut="Ctrl+Shift+Z")
        root.addWidget(row2)

        self.grid = PageGrid()
        self.grid.order_changed.connect(self._order_dragged)
        self.grid.itemSelectionChanged.connect(self._update_status)
        root.addWidget(self.grid, 1)

        bottom = ToolBarRow(wrap=True)
        self.status = bottom.label("Open a PDF to organise its pages.",
                                   "faint")
        bottom.stretch()
        bottom.add(icon_label("Export:", "dim"))
        self.btn_export = bottom.button("Save organised PDF", self.export,
                                        kind="primary")
        self.btn_export_sel = bottom.button("Export selected pages only",
                                            self.export_selection, icon="export")
        root.addWidget(bottom)

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
        self.doc = doc
        self.path = Path(path)
        self._uid = 0
        self.entries = [self._entry(0, i, doc[i].rotation, False, str(i + 1))
                        for i in range(doc.page_count)]
        self.undo.clear()
        self.redo.clear()
        self._pix_cache.clear()
        self.refresh()

    def _entry(self, doc_i, page, rot, blank, label) -> dict:
        """Entries carry a stable uid so drag-and-drop order can be recovered."""
        self._uid += 1
        return {"uid": self._uid, "doc": doc_i, "page": page, "rot": rot,
                "blank": blank, "label": label}

    # --------------------------------------------------------------- model
    def _docs(self):
        return [self.doc] + self.extra_docs

    def snapshot(self):
        self.undo.append([dict(e) for e in self.entries])
        if len(self.undo) > 60:
            self.undo.pop(0)
        self.redo.clear()

    def do_undo(self):
        if not self.undo:
            return
        self.redo.append([dict(e) for e in self.entries])
        self.entries = self.undo.pop()
        self.refresh(set())

    def do_redo(self):
        if not self.redo:
            return
        self.undo.append([dict(e) for e in self.entries])
        self.entries = self.redo.pop()
        self.refresh(set())

    def refresh(self, keep_uids=None):
        """Rebuild the grid, keeping the selection on the same pages."""
        if keep_uids is None:
            keep_uids = {self.grid.item(i).data(Qt.UserRole)
                         for i in range(self.grid.count())
                         if self.grid.item(i).isSelected()}
        self.grid.blockSignals(True)
        self.grid.clear()
        for n, e in enumerate(self.entries):
            item = QtWidgets.QListWidgetItem()
            item.setData(Qt.UserRole, e["uid"])
            item.setIcon(QtGui.QIcon(self._pixmap(e)))
            tag = f"{n+1}"
            if e["blank"]:
                tag += "  blank"
            elif e["doc"] > 0:
                tag += f"  ins·{e['label']}"
            elif e["label"] != str(n + 1):
                tag += f"  (was {e['label']})"
            if e["rot"] % 360:
                tag += f"  {e['rot']%360}°"
            item.setText(tag)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            self.grid.addItem(item)
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            if item.data(Qt.UserRole) in keep_uids:
                item.setSelected(True)
        self.grid.blockSignals(False)
        self._update_status()

    def _pixmap(self, entry) -> QtGui.QPixmap:
        key = (entry["doc"], entry["page"], entry["rot"], entry["blank"])
        if key in self._pix_cache:
            return self._pix_cache[key]
        if entry["blank"]:
            pm = QtGui.QPixmap(116, 150)
            pm.fill(QtGui.QColor("white"))
            p = QtGui.QPainter(pm)
            p.setPen(QtGui.QPen(QtGui.QColor(190, 190, 190), 1,
                                Qt.DashLine))
            p.drawRect(0, 0, pm.width() - 1, pm.height() - 1)
            p.setPen(QtGui.QColor(150, 150, 150))
            p.drawText(pm.rect(), Qt.AlignCenter, "blank")
            p.end()
        else:
            doc = self._docs()[entry["doc"]]
            pm = thumb_pixmap(doc, entry["page"], 150)
            if entry["rot"] % 360:
                src = doc[entry["page"]].rotation
                delta = (entry["rot"] - src) % 360
                if delta:
                    pm = pm.transformed(QtGui.QTransform().rotate(delta),
                                        Qt.SmoothTransformation)
        self._pix_cache[key] = pm
        return pm

    def _selected_rows(self) -> list[int]:
        return sorted(self.grid.row(i) for i in self.grid.selectedItems())

    def _order_dragged(self):
        """Rebuild the model from the grid's new order, matching on uid."""
        by_uid = {e["uid"]: e for e in self.entries}
        new = []
        for i in range(self.grid.count()):
            uid = self.grid.item(i).data(Qt.UserRole)
            if uid in by_uid:
                new.append(by_uid.pop(uid))
        new.extend(by_uid.values())        # safety net: never lose a page
        if len(new) == len(self.entries) and new != self.entries:
            self.undo.append([dict(e) for e in self.entries])
            self.redo.clear()
            self.entries = new
        self.refresh()

    def _update_status(self):
        if not self.doc:
            return
        sel = self._selected_rows()
        bits = [f"{len(self.entries)} page(s)"]
        if sel:
            bits.append(f"{len(sel)} selected: "
                        f"{fmt_pages(sel)}")
        if self.path:
            bits.insert(0, self.path.name)
        self.status.setText("  ·  ".join(bits))

    # ------------------------------------------------------------- editing
    def _need_sel(self) -> list[int]:
        sel = self._selected_rows()
        if not sel:
            self.status.setText("Select one or more pages first "
                                "(click, or Ctrl+A for all).")
        return sel

    def rotate(self, delta: int):
        sel = self._need_sel()
        if not sel:
            return
        self.snapshot()
        for r in sel:
            self.entries[r]["rot"] = (self.entries[r]["rot"] + delta) % 360
        self.refresh()

    def move(self, delta: int):
        sel = self._need_sel()
        if not sel:
            return
        if delta < 0 and sel[0] == 0:
            return
        if delta > 0 and sel[-1] == len(self.entries) - 1:
            return
        self.snapshot()
        for r in (sel if delta < 0 else reversed(sel)):
            self.entries[r], self.entries[r + delta] = \
                self.entries[r + delta], self.entries[r]
        self.refresh()

    def move_edge(self, front: bool):
        sel = self._need_sel()
        if not sel:
            return
        self.snapshot()
        picked = [self.entries[r] for r in sel]
        rest = [e for i, e in enumerate(self.entries) if i not in set(sel)]
        self.entries = picked + rest if front else rest + picked
        self.refresh()

    def duplicate(self):
        sel = self._need_sel()
        if not sel:
            return
        self.snapshot()
        new_uids = set()
        for r in reversed(sel):
            copy = dict(self.entries[r])
            self._uid += 1
            copy["uid"] = self._uid
            new_uids.add(self._uid)
            self.entries.insert(r + 1, copy)
        self.refresh(new_uids)

    def delete(self):
        sel = self._need_sel()
        if not sel:
            return
        if len(sel) >= len(self.entries):
            QtWidgets.QMessageBox.information(
                self, "Cannot delete every page",
                "A PDF needs at least one page. Leave one unselected.")
            return
        self.snapshot()
        for r in reversed(sel):
            del self.entries[r]
        self.refresh(set())

    def reverse(self):
        if not self.entries:
            return
        self.snapshot()
        self.entries.reverse()
        self.refresh()

    def select_parity(self, parity: int):
        self.grid.clearSelection()
        for i in range(self.grid.count()):
            if i % 2 == parity:
                self.grid.item(i).setSelected(True)

    def insert_blank(self):
        if not self.doc:
            return
        sel = self._selected_rows()
        at = (sel[-1] + 1) if sel else len(self.entries)
        self.snapshot()
        self.entries.insert(at, self._entry(0, 0, 0, True, "blank"))
        self.refresh({self.entries[at]["uid"]})

    def insert_pdf(self):
        if not self.doc:
            QtWidgets.QMessageBox.information(self, "Open a document first",
                                              "Open the main PDF first.")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Insert pages from", str(Path.home()), "PDF files (*.pdf)")
        if not path:
            return
        doc = open_with_prompt(self, path)
        if doc is None:
            return
        self.extra_docs.append(doc)
        d_idx = len(self.extra_docs)
        spec, ok = QtWidgets.QInputDialog.getText(
            self, "Which pages?",
            f"{Path(path).name} has {doc.page_count} page(s).\n"
            f"Pages to insert (e.g. all, 1-3, 2,5):", text="all")
        if not ok:
            return
        from pdfbuilder.core.common import parse_pages
        from pdfbuilder.job import ToolError
        try:
            idxs = parse_pages(spec, doc.page_count)
        except ToolError as e:
            QtWidgets.QMessageBox.warning(self, "Page range", str(e))
            return
        sel = self._selected_rows()
        at = (sel[-1] + 1) if sel else len(self.entries)
        self.snapshot()
        added = set()
        for n, i in enumerate(idxs):
            entry = self._entry(d_idx, i, doc[i].rotation, False,
                                f"{Path(path).stem}:{i+1}")
            added.add(entry["uid"])
            self.entries.insert(at + n, entry)
        self.refresh(added)
        self.status.setText(f"Inserted {len(idxs)} page(s) from "
                            f"{Path(path).name}.")

    # ------------------------------------------------------------- export
    def _build(self, rows=None) -> fitz.Document:
        out = fitz.open()
        docs = self._docs()
        entries = self.entries if rows is None else [self.entries[r]
                                                     for r in rows]
        for e in entries:
            if e["blank"]:
                ref = docs[0][0].rect
                out.new_page(width=ref.width, height=ref.height)
                continue
            src = docs[e["doc"]]
            out.insert_pdf(src, from_page=e["page"], to_page=e["page"])
            out[-1].set_rotation(e["rot"] % 360)
        return out

    def _save(self, doc, suffix):
        outdir = self.main.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        base = f"{self.path.stem}-{suffix}.pdf"
        target = outdir / base
        n = 2
        while target.exists():
            target = outdir / f"{self.path.stem}-{suffix} ({n}).pdf"
            n += 1
        save_pdf(doc, target, garbage=3, deflate=True)
        doc.close()
        return target

    def export(self):
        if not self.doc:
            return
        target = self._save(self._build(), "organised")
        self.status.setProperty("role", "good")
        self.status.setText(f"Saved {target}")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self._offer(target)

    def export_selection(self):
        sel = self._need_sel()
        if not sel or not self.doc:
            return
        target = self._save(self._build(sel), f"pages-{fmt_pages(sel)}")
        self.status.setText(f"Saved {target}")
        self._offer(target)

    def _offer(self, target):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Saved")
        box.setText(f"Written to:\n{target}")
        box.addButton("Open", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("Show in files", QtWidgets.QMessageBox.ActionRole)
        box.addButton("Close", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton().text()
        if clicked == "Open":
            open_externally(target)
        elif clicked == "Show in files":
            from pdfbuilder.ui.widgets import reveal_in_files
            reveal_in_files(target)


def build(tool, main):
    return Organizer(tool, main)
