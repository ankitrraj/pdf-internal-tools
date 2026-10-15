"""Shared pieces for the interactive panels."""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.core.common import open_pdf
from pdfbuilder.job import ToolError
from pdfbuilder.ui.widgets import icon_label

Qt = QtCore.Qt


def ask_password(parent, name: str) -> str | None:
    pw, ok = QtWidgets.QInputDialog.getText(
        parent, "Password needed",
        f"{name} is protected.\nEnter the password to open it:",
        QtWidgets.QLineEdit.Password)
    return pw if ok else None


def open_with_prompt(parent, path) -> fitz.Document | None:
    """Open a PDF, asking for the password if one is needed."""
    path = Path(path)
    try:
        return open_pdf(path)
    except ToolError:
        pass
    for _ in range(3):
        pw = ask_password(parent, path.name)
        if pw is None:
            return None
        try:
            return open_pdf(path, pw)
        except ToolError:
            QtWidgets.QMessageBox.warning(parent, "Wrong password",
                                          "That password was not accepted.")
    return None


def page_pixmap(doc: fitz.Document, index: int, zoom: float = 1.0,
                annots: bool = True) -> QtGui.QPixmap:
    mat = fitz.Matrix(zoom, zoom)
    pix = doc[index].get_pixmap(matrix=mat, alpha=False, annots=annots)
    img = QtGui.QImage(pix.samples, pix.width, pix.height, pix.stride,
                       QtGui.QImage.Format_RGB888)
    return QtGui.QPixmap.fromImage(img.copy())


def thumb_pixmap(doc: fitz.Document, index: int, edge: int = 150) -> QtGui.QPixmap:
    page = doc[index]
    r = page.rect
    zoom = edge / max(1.0, max(r.width, r.height))
    return page_pixmap(doc, index, zoom)


class PageCanvas(QtWidgets.QGraphicsView):
    """Scrollable, zoomable page display with an overlay layer."""

    clicked = QtCore.Signal(QtCore.QPointF, QtGui.QMouseEvent)
    dragged = QtCore.Signal(QtCore.QPointF, QtCore.QPointF, QtGui.QMouseEvent)
    released = QtCore.Signal(QtCore.QPointF, QtGui.QMouseEvent)
    moved = QtCore.Signal(QtCore.QPointF)
    zoom_changed = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Canvas")
        self.scene_ = QtWidgets.QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QtGui.QPainter.Antialiasing |
                            QtGui.QPainter.SmoothPixmapTransform)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setAlignment(Qt.AlignCenter)
        self.page_item: QtWidgets.QGraphicsPixmapItem | None = None
        self.overlay: list[QtWidgets.QGraphicsItem] = []
        self.zoom = 1.0
        self.page_size = QtCore.QSizeF(1, 1)   # PDF points
        self._press: QtCore.QPointF | None = None
        self._panning = False

    # ------------------------------------------------------------- content
    def show_page(self, doc, index: int, zoom: float | None = None,
                  annots: bool = True):
        if zoom is not None:
            self.zoom = zoom
        r = doc[index].rect
        self.page_size = QtCore.QSizeF(r.width, r.height)
        pm = page_pixmap(doc, index, self.zoom, annots=annots)
        self.clear_overlay()
        self.scene_.clear()
        self.page_item = self.scene_.addPixmap(pm)
        self.page_item.setTransformationMode(Qt.SmoothTransformation)
        self.scene_.setSceneRect(QtCore.QRectF(pm.rect()))
        shadow = QtWidgets.QGraphicsDropShadowEffect()
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 3)
        shadow.setColor(QtGui.QColor(0, 0, 0, 120))
        self.page_item.setGraphicsEffect(shadow)

    def clear_overlay(self):
        for item in self.overlay:
            if item.scene():
                self.scene_.removeItem(item)
        self.overlay = []

    def add_overlay(self, item):
        self.scene_.addItem(item)
        self.overlay.append(item)
        return item

    # --------------------------------------------------------- coordinates
    def to_pdf(self, scene_pos: QtCore.QPointF) -> tuple[float, float]:
        return scene_pos.x() / self.zoom, scene_pos.y() / self.zoom

    def from_pdf(self, x: float, y: float) -> QtCore.QPointF:
        return QtCore.QPointF(x * self.zoom, y * self.zoom)

    # --------------------------------------------------------------- zoom
    def set_zoom(self, zoom: float):
        self.zoom = max(0.08, min(8.0, zoom))
        self.zoom_changed.emit(self.zoom)

    def fit_width(self) -> float:
        if self.page_size.width() <= 0:
            return self.zoom
        avail = self.viewport().width() - 30
        return max(0.08, avail / self.page_size.width())

    def fit_page(self) -> float:
        if self.page_size.width() <= 0:
            return self.zoom
        w = (self.viewport().width() - 30) / self.page_size.width()
        h = (self.viewport().height() - 30) / self.page_size.height()
        return max(0.08, min(w, h))

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.ControlModifier:
            step = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
            self.set_zoom(self.zoom * step)
            ev.accept()
            return
        super().wheelEvent(ev)

    # -------------------------------------------------------------- mouse
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MiddleButton or (
                ev.button() == Qt.LeftButton and
                ev.modifiers() & Qt.ShiftModifier):
            self._panning = True
            self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
            super().mousePressEvent(ev)
            return
        self._press = self.mapToScene(ev.position().toPoint())
        self.clicked.emit(self._press, ev)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        pos = self.mapToScene(ev.position().toPoint())
        self.moved.emit(pos)
        if self._press is not None and not self._panning:
            self.dragged.emit(self._press, pos, ev)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._panning:
            self._panning = False
            self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
            super().mouseReleaseEvent(ev)
            return
        pos = self.mapToScene(ev.position().toPoint())
        self.released.emit(pos, ev)
        self._press = None
        super().mouseReleaseEvent(ev)


class PageStrip(QtWidgets.QListWidget):
    """Narrow page thumbnail strip used for navigation."""
    page_chosen = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QtWidgets.QListWidget.IconMode)
        self.setIconSize(QtCore.QSize(104, 134))
        self.setGridSize(QtCore.QSize(124, 168))
        self.setResizeMode(QtWidgets.QListWidget.Adjust)
        self.setMovement(QtWidgets.QListWidget.Static)
        self.setSpacing(4)
        self.setFixedWidth(158)
        self.setUniformItemSizes(True)
        self.currentRowChanged.connect(
            lambda r: self.page_chosen.emit(r) if r >= 0 else None)

    def load(self, doc, limit: int = 400):
        self.clear()
        for i in range(min(doc.page_count, limit)):
            item = QtWidgets.QListWidgetItem(str(i + 1))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            item.setIcon(QtGui.QIcon(thumb_pixmap(doc, i, 130)))
            self.addItem(item)


class ToolBarRow(QtWidgets.QWidget):
    """Strip of controls. With wrap=True the buttons flow onto a second
    line instead of being squeezed when the window is narrow."""

    def __init__(self, parent=None, wrap: bool = False):
        super().__init__(parent)
        self.wrap = wrap
        if wrap:
            from pdfbuilder.ui.widgets import FlowLayout
            self.row = FlowLayout(self, spacing=6)
        else:
            self.row = QtWidgets.QHBoxLayout(self)
            self.row.setContentsMargins(0, 0, 0, 0)
            self.row.setSpacing(6)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                           QtWidgets.QSizePolicy.Minimum)

    def add(self, w):
        self.row.addWidget(w)
        return w

    def button(self, text, slot=None, *, kind="", tip="", shortcut="",
               icon=""):
        b = QtWidgets.QPushButton(text)
        if icon:
            from pdfbuilder.ui import icons
            icons.apply(b, icon, 16)
        if kind:
            b.setProperty("kind", kind)
        if tip:
            b.setToolTip(tip + (f"  ({shortcut})" if shortcut else ""))
        if shortcut:
            b.setShortcut(shortcut)
        if slot:
            b.clicked.connect(slot)
        return self.add(b)

    def label(self, text, role="dim"):
        return self.add(icon_label(text, role))

    def stretch(self):
        if not self.wrap:
            self.row.addStretch(1)

    def sep(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.VLine)
        line.setStyleSheet("color: rgba(128,128,128,.3);")
        return self.add(line)


class FilePicker(QtWidgets.QWidget):
    """A compact 'current file' selector used by the interactive panels."""
    file_chosen = QtCore.Signal(str)

    def __init__(self, label="Document", parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(icon_label(label + ":", "dim"))
        self.box = QtWidgets.QComboBox()
        self.box.setMinimumWidth(240)
        self.box.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self.box.currentIndexChanged.connect(self._emit)
        lay.addWidget(self.box, 1)
        self.btn = QtWidgets.QPushButton("Open...")
        self.btn.clicked.connect(self._browse)
        lay.addWidget(self.btn)
        self._paths: list[str] = []

    def _browse(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Open PDF", str(Path.home()),
            "PDF files (*.pdf);;All files (*)")
        if files:
            self.add(files)

    def add(self, paths, choose_last=True):
        added = False
        for p in paths:
            p = str(p)
            if p not in self._paths:
                self._paths.append(p)
                self.box.addItem(Path(p).name)
                added = True
        if added and choose_last:
            self.box.setCurrentIndex(len(self._paths) - 1)
        elif added:
            self._emit()

    def _emit(self):
        p = self.current()
        if p:
            self.file_chosen.emit(p)

    def current(self) -> str | None:
        i = self.box.currentIndex()
        if 0 <= i < len(self._paths):
            return self._paths[i]
        return None

    def paths(self) -> list[str]:
        return list(self._paths)
