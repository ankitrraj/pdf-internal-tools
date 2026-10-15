"""Side-by-side visual comparison of two PDFs with a text diff."""
from __future__ import annotations

import difflib
from pathlib import Path

import pymupdf as fitz
from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.ui.views.common import PageCanvas, ToolBarRow, open_with_prompt
from pdfbuilder.ui.widgets import icon_label

Qt = QtCore.Qt


class Compare(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.docs: list[fitz.Document | None] = [None, None]
        self.paths: list[Path | None] = [None, None]
        self.index = 0
        self.diff_pages: list[int] = []

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)
        root.addWidget(icon_label(tool.name, "h1"))

        pick = ToolBarRow(wrap=True)
        self.btn_a = pick.button("Choose the first PDF...",
                                 lambda: self.choose(0))
        self.btn_b = pick.button("Choose the second PDF...",
                                 lambda: self.choose(1))
        pick.sep()
        pick.add(QtWidgets.QLabel("Sensitivity"))
        self.sens = QtWidgets.QSlider(Qt.Horizontal)
        self.sens.setRange(2, 90)
        self.sens.setValue(24)
        self.sens.setFixedWidth(120)
        self.sens.valueChanged.connect(lambda _: self.refresh())
        pick.add(self.sens)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(["side by side", "overlay", "difference only"])
        self.mode.currentTextChanged.connect(lambda _: self.refresh())
        pick.add(self.mode)
        pick.stretch()
        pick.button("Only changed pages", self.jump_next_diff, icon="compare")
        pick.button("Save a comparison PDF", self.save_report, kind="primary", icon="save")
        root.addWidget(pick)

        nav = ToolBarRow(wrap=True)
        nav.button("‹", lambda: self.goto(self.index - 1), icon="left")
        self.page_label = nav.label("- / -")
        nav.button("›", lambda: self.goto(self.index + 1), icon="right")
        nav.button("Fit", self.refresh, icon="margins")
        self.summary = nav.label("Choose two PDFs to compare.", "faint")
        nav.stretch()
        root.addWidget(nav)

        split = QtWidgets.QSplitter(Qt.Vertical)
        pages = QtWidgets.QWidget()
        pl = QtWidgets.QHBoxLayout(pages)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.left = PageCanvas()
        self.right = PageCanvas()
        for c, title in ((self.left, "First document"),
                         (self.right, "Second document")):
            box = QtWidgets.QVBoxLayout()
            lab = icon_label(title, "dim")
            box.addWidget(lab)
            box.addWidget(c, 1)
            holder = QtWidgets.QWidget()
            holder.setLayout(box)
            pl.addWidget(holder, 1)
            c.label = lab                     # type: ignore
        split.addWidget(pages)

        self.diff_view = QtWidgets.QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(QtGui.QFont("monospace", 10))
        self.diff_view.setMaximumHeight(240)
        split.addWidget(self.diff_view)
        split.setSizes([620, 200])
        root.addWidget(split, 1)

        # keep both views in sync
        for a, b in ((self.left, self.right), (self.right, self.left)):
            a.verticalScrollBar().valueChanged.connect(
                b.verticalScrollBar().setValue)
            a.horizontalScrollBar().valueChanged.connect(
                b.horizontalScrollBar().setValue)

    def add_files(self, paths):
        pdfs = [p for p in paths if str(p).lower().endswith(".pdf")]
        for p in pdfs:
            slot = 0 if self.docs[0] is None else 1
            if self.docs[slot] is not None:
                break
            self.load(slot, p)

    def choose(self, slot):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, f"Choose PDF {slot+1}", str(Path.home()),
            "PDF files (*.pdf)")
        if path:
            self.load(slot, path)

    def load(self, slot, path):
        doc = open_with_prompt(self, path)
        if doc is None:
            return
        if self.docs[slot]:
            self.docs[slot].close()
        self.docs[slot] = doc
        self.paths[slot] = Path(path)
        (self.btn_a if slot == 0 else self.btn_b).setText(Path(path).name)
        (self.left if slot == 0 else self.right).label.setText(
            Path(path).name)
        if all(self.docs):
            self.analyse()
        self.goto(0)

    def analyse(self):
        a, b = self.docs
        n = max(a.page_count, b.page_count)
        self.diff_pages = []
        import numpy as np
        from PIL import ImageChops
        thresh = self.sens.value()
        for i in range(n):
            if i >= a.page_count or i >= b.page_count:
                self.diff_pages.append(i)
                continue
            ia = self._render(a, i, 60)
            ib = self._render(b, i, 60)
            if ia.size != ib.size:
                self.diff_pages.append(i)
                continue
            diff = ImageChops.difference(ia, ib).convert("L")
            if (np.array(diff) > thresh).any():
                self.diff_pages.append(i)
        same = n - len(self.diff_pages)
        self.summary.setProperty("role", "warn" if self.diff_pages else "good")
        self.summary.setText(
            f"{len(self.diff_pages)} of {n} page(s) differ   ·   "
            f"{same} identical" if self.diff_pages
            else f"All {n} page(s) render identically")
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        self._text_diff()

    @staticmethod
    def _render(doc, i, dpi):
        from PIL import Image
        pix = doc[i].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB" if pix.n >= 3 else "L",
                               (pix.width, pix.height),
                               pix.samples).convert("RGB")

    def _text_diff(self):
        a, b = self.docs
        ta = [a[i].get_text("text") for i in range(a.page_count)]
        tb = [b[i].get_text("text") for i in range(b.page_count)]
        lines = list(difflib.unified_diff(
            "\n".join(ta).splitlines(), "\n".join(tb).splitlines(),
            fromfile=self.paths[0].name, tofile=self.paths[1].name,
            lineterm="", n=1))
        self.diff_view.setPlainText(
            "\n".join(lines[:4000]) if lines
            else "The text content of both documents is identical.")

    def goto(self, index):
        docs = [d for d in self.docs if d]
        if not docs:
            return
        n = max(d.page_count for d in docs)
        self.index = max(0, min(index, n - 1))
        self.page_label.setText(f"{self.index+1} / {n}")
        self.refresh()

    def refresh(self):
        import numpy as np
        from PIL import ImageChops
        mode = self.mode.currentText()
        for slot, canvas in ((0, self.left), (1, self.right)):
            doc = self.docs[slot]
            if doc is None or self.index >= doc.page_count:
                canvas.scene_.clear()
                continue
            canvas.show_page(doc, self.index)
            canvas.set_zoom(canvas.fit_page())
            canvas.show_page(doc, self.index)
        self.right.setVisible(mode == "side by side")
        if not all(self.docs):
            return
        a, b = self.docs
        if self.index >= a.page_count or self.index >= b.page_count:
            return
        ia = self._render(a, self.index, 110)
        ib = self._render(b, self.index, 110)
        if ia.size != ib.size:
            ib = ib.resize(ia.size)
        diff = ImageChops.difference(ia, ib).convert("L")
        mask = np.array(diff) > self.sens.value()
        if not mask.any():
            return
        # draw difference boxes on both sides
        boxes = _mask_boxes(mask, ia.size)
        for canvas, colour in ((self.left, "#4f8cff"), (self.right, "#f2545b")):
            if not canvas.isVisible() and canvas is self.right:
                continue
            z = canvas.zoom
            sx = canvas.page_size.width() / ia.width
            sy = canvas.page_size.height() / ia.height
            for (bx0, by0, bx1, by1) in boxes:
                item = QtWidgets.QGraphicsRectItem(QtCore.QRectF(
                    bx0 * sx * z, by0 * sy * z, (bx1 - bx0) * sx * z,
                    (by1 - by0) * sy * z))
                pen = QtGui.QPen(QtGui.QColor(colour), 1.6)
                item.setPen(pen)
                fill = QtGui.QColor(colour)
                fill.setAlpha(40)
                item.setBrush(QtGui.QBrush(fill))
                canvas.add_overlay(item)

    def jump_next_diff(self):
        if not self.diff_pages:
            self.summary.setText("No differing pages to jump to.")
            return
        later = [p for p in self.diff_pages if p > self.index]
        self.goto(later[0] if later else self.diff_pages[0])

    def save_report(self):
        if not all(self.docs):
            QtWidgets.QMessageBox.information(
                self, "Choose two files",
                "Pick both PDFs before saving a comparison.")
            return
        from pdfbuilder.job import Ctx, ToolError
        from pdfbuilder.registry import REGISTRY
        tool = REGISTRY["compare_report"]
        params = {**tool.defaults(), "sensitivity": self.sens.value(),
                  "layout": self.mode.currentText()}
        outdir = self.main.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        prog = QtWidgets.QProgressDialog("Building the comparison...",
                                         "Cancel", 0, 100, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        cancelled = {"v": False}
        prog.canceled.connect(lambda: cancelled.update(v=True))
        ctx = Ctx([str(p) for p in self.paths], params, outdir,
                  progress=lambda f, m="": (prog.setValue(int(f * 100)),
                                            prog.setLabelText(m or ""),
                                            QtWidgets.QApplication
                                            .processEvents()),
                  cancelled=lambda: cancelled["v"])
        try:
            made = tool.fn(ctx) or ctx.produced
        except ToolError as e:
            prog.close()
            QtWidgets.QMessageBox.warning(self, "Comparison", str(e))
            return
        except Exception as e:
            prog.close()
            QtWidgets.QMessageBox.warning(self, "Comparison",
                                          f"{type(e).__name__}: {e}")
            return
        finally:
            ctx.cleanup()
        prog.close()
        if made:
            from pdfbuilder.ui.widgets import open_externally
            if QtWidgets.QMessageBox.question(
                    self, "Saved",
                    "Comparison written to:\n" +
                    "\n".join(str(m) for m in made) + "\n\nOpen it now?") \
                    == QtWidgets.QMessageBox.Yes:
                open_externally(made[0])


def _mask_boxes(mask, size, grid: int = 26, limit: int = 220):
    """Group changed pixels into coarse rectangles for display."""
    import numpy as np
    h, w = mask.shape
    cell_h = max(1, h // grid)
    cell_w = max(1, w // grid)
    boxes = []
    for gy in range(0, h, cell_h):
        for gx in range(0, w, cell_w):
            block = mask[gy:gy + cell_h, gx:gx + cell_w]
            if not block.any():
                continue
            ys, xs = np.nonzero(block)
            boxes.append((gx + int(xs.min()), gy + int(ys.min()),
                          gx + int(xs.max()) + 1, gy + int(ys.max()) + 1))
            if len(boxes) >= limit:
                return boxes
    return boxes


def build(tool, main):
    return Compare(tool, main)
