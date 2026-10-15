"""Reusable widgets: drop-target file list, generated parameter forms,
output panel and small helpers."""
from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.core.common import (human_size, is_image, is_pdf, parse_color,
                                    to_hex)
from pdfbuilder.registry import P
from pdfbuilder.ui import icons

Qt = QtCore.Qt


# --------------------------------------------------------------- utilities

def open_externally(path) -> None:
    """Hand a file or folder to the desktop environment."""
    path = str(path)
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


def reveal_in_files(path) -> None:
    path = Path(path)
    target = path if path.is_dir() else path.parent
    for cmd in (["xdg-open", str(target)], ["nautilus", str(path)],
                ["dolphin", "--select", str(path)]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
        except FileNotFoundError:
            continue
    open_externally(target)


def print_file(path, parent=None) -> bool:
    """Print through the system spooler, falling back to a Qt dialog."""
    path = str(path)
    try:
        from PySide6 import QtPrintSupport
    except ImportError:
        QtPrintSupport = None
    if Path(path).suffix.lower() == ".pdf":
        for exe in ("lp", "lpr"):
            try:
                subprocess.run([exe, path], check=True,
                               capture_output=True, timeout=30)
                return True
            except (FileNotFoundError, subprocess.CalledProcessError,
                    subprocess.TimeoutExpired):
                continue
    if QtPrintSupport is not None:
        dlg = QtPrintSupport.QPrintDialog(parent)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            return True
    return False


def icon_label(text: str, role: str = "") -> QtWidgets.QLabel:
    lab = QtWidgets.QLabel(text)
    if role:
        lab.setProperty("role", role)
    return lab


EXT_ICONS = {
    ".pdf": "to_pdf", ".zip": "zip", ".txt": "text", ".log": "text",
    ".md": "text", ".html": "code", ".htm": "code", ".xml": "code",
    ".svg": "shapes", ".csv": "table", ".tsv": "table", ".json": "code",
    ".docx": "word", ".doc": "word", ".odt": "word", ".rtf": "word",
    ".xlsx": "excel", ".xls": "excel", ".ods": "excel",
    ".pptx": "slides", ".ppt": "slides", ".odp": "slides",
    ".epub": "book",
}


def _file_icon(path) -> str:
    ext = Path(path).suffix.lower()
    if ext in EXT_ICONS:
        return EXT_ICONS[ext]
    return "picture" if is_image(path) else "file"


def hline() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setFrameShape(QtWidgets.QFrame.HLine)
    f.setStyleSheet("color: rgba(128,128,128,0.25);")
    f.setFixedHeight(1)
    return f


class FlowLayout(QtWidgets.QLayout):
    """A layout that wraps its children onto the next line when space runs
    out - used for the dense tool strips so buttons are never squeezed."""

    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self._items: list[QtWidgets.QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QtCore.QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, test=False):
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        line_height = 0
        space = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            if x > rect.x() + m.left() and x + hint.width() > right:
                x = rect.x() + m.left()
                y += line_height + space
                line_height = 0
            if not test:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x += hint.width() + space
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


# ------------------------------------------------------------ colour picker

class ColorButton(QtWidgets.QPushButton):
    changed = QtCore.Signal(str)

    def __init__(self, value: str = "#000000", allow_empty=True, parent=None):
        super().__init__(parent)
        self.allow_empty = allow_empty
        self._value = value or ""
        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._paint()

    def _paint(self):
        if not self._value:
            self.setText("none")
            self.setStyleSheet("")
            return
        hexv = to_hex(parse_color(self._value))
        r, g, b = (int(hexv[i:i + 2], 16) for i in (1, 3, 5))
        fg = "#000" if (r * 0.299 + g * 0.587 + b * 0.114) > 150 else "#fff"
        self.setText(hexv)
        self.setStyleSheet(f"background:{hexv}; color:{fg}; font-weight:600;"
                           f"border:1px solid rgba(128,128,128,.5);"
                           f"border-radius:7px;")

    def _pick(self):
        start = QtGui.QColor(to_hex(parse_color(self._value or "#000000")))
        dlg = QtWidgets.QColorDialog(start, self)
        dlg.setOption(QtWidgets.QColorDialog.DontUseNativeDialog, True)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.set_value(dlg.currentColor().name())

    def value(self) -> str:
        return self._value

    def set_value(self, v: str):
        self._value = v or ""
        self._paint()
        self.changed.emit(self._value)

    def contextMenuEvent(self, ev):
        if not self.allow_empty:
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction("Clear (no colour)", lambda: self.set_value(""))
        menu.exec(ev.globalPos())


class PathPicker(QtWidgets.QWidget):
    changed = QtCore.Signal(str)

    def __init__(self, directory=False, filt="All files (*)", parent=None):
        super().__init__(parent)
        self.directory = directory
        self.filt = filt
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText("Choose a folder..." if directory
                                     else "Choose a file...")
        self.edit.textChanged.connect(self.changed.emit)
        btn = QtWidgets.QPushButton("Browse")
        btn.clicked.connect(self._browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)

    def _browse(self):
        start = self.edit.text().strip() or str(Path.home())
        if self.directory:
            p = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose a folder",
                                                           start)
        else:
            p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose a file",
                                                         start, self.filt)
        if p:
            self.edit.setText(p)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, v):
        self.edit.setText(str(v or ""))


# -------------------------------------------------------------- file list

class FileList(QtWidgets.QWidget):
    """Drag-and-drop list of input files with sizes and page counts."""
    changed = QtCore.Signal()
    activated = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._meta: dict[str, str] = {}
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.drop = QtWidgets.QFrame()
        self.drop.setObjectName("DropZone")
        self.drop.setMinimumHeight(74)
        self.drop.setMaximumHeight(110)
        self.drop.setAcceptDrops(True)
        dl = QtWidgets.QVBoxLayout(self.drop)
        dl.setSpacing(2)
        title = icon_label("Drop files here", "h2")
        title.setAlignment(Qt.AlignCenter)
        sub = icon_label("or use the buttons below  ·  nothing is uploaded, "
                         "everything stays on this computer", "faint")
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        dl.addWidget(title)
        dl.addWidget(sub)
        lay.addWidget(self.drop)

        row = FlowLayout(spacing=6)
        self.btn_add = QtWidgets.QPushButton("Add files")
        self.btn_add.setShortcut("Ctrl+O")
        self.btn_add.setToolTip("Add files  (Ctrl+O)")
        self.btn_folder = QtWidgets.QPushButton("Add folder")
        self.btn_up = QtWidgets.QPushButton("Move up")
        self.btn_down = QtWidgets.QPushButton("Move down")
        self.btn_rm = QtWidgets.QPushButton("Remove")
        self.btn_rm.setProperty("kind", "danger")
        self.btn_clear = QtWidgets.QPushButton("Clear")
        self.btn_clear.setProperty("kind", "danger")
        for b, name in ((self.btn_add, "plus"), (self.btn_folder, "folder"),
                        (self.btn_up, "up"), (self.btn_down, "down"),
                        (self.btn_rm, "minus"), (self.btn_clear, "trash")):
            icons.apply(b, name, 15)
        for b in (self.btn_add, self.btn_folder, self.btn_up, self.btn_down,
                  self.btn_rm, self.btn_clear):
            b.setSizePolicy(QtWidgets.QSizePolicy.Preferred,
                            QtWidgets.QSizePolicy.Fixed)
            row.addWidget(b)
        lay.addLayout(row)

        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.list.setAlternatingRowColors(True)
        self.list.setAcceptDrops(True)
        self.list.setMinimumHeight(84)
        self.list.itemDoubleClicked.connect(
            lambda it: self.activated.emit(it.data(Qt.UserRole)))
        self.list.model().rowsMoved.connect(lambda *a: self.changed.emit())
        lay.addWidget(self.list, 1)

        self.info = icon_label("No files selected", "faint")
        lay.addWidget(self.info)

        self.btn_add.clicked.connect(self.pick_files)
        self.btn_folder.clicked.connect(self.pick_folder)
        self.btn_rm.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(self.clear)
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))

        for w in (self.drop, self.list):
            w.dragEnterEvent = self._drag_enter        # type: ignore
            w.dragMoveEvent = self._drag_move          # type: ignore
            w.dragLeaveEvent = self._drag_leave        # type: ignore
            w.dropEvent = self._drop                   # type: ignore
        self.setAcceptDrops(True)

    # ---------------------------------------------------------- drag/drop
    def _drag_enter(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()
            self.drop.setProperty("hot", "true")
            self.drop.style().unpolish(self.drop)
            self.drop.style().polish(self.drop)

    def _drag_move(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def _drag_leave(self, ev):
        self.drop.setProperty("hot", "false")
        self.drop.style().unpolish(self.drop)
        self.drop.style().polish(self.drop)

    def _drop(self, ev):
        self._drag_leave(ev)
        paths = []
        for url in ev.mimeData().urls():
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths += sorted(q for q in p.rglob("*") if q.is_file())
            elif p.exists():
                paths.append(p)
        self.add(paths)
        ev.acceptProposedAction()

    def dragEnterEvent(self, ev):
        self._drag_enter(ev)

    def dropEvent(self, ev):
        self._drop(ev)

    # -------------------------------------------------------------- model
    def pick_files(self):
        start = str(Path.home())
        items = self.paths()
        if items:
            start = str(Path(items[-1]).parent)
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add files", start,
            "All supported (*.pdf *.jpg *.jpeg *.png *.webp *.tif *.tiff "
            "*.bmp *.gif *.heic *.heif *.txt *.md *.html *.htm *.csv *.docx "
            "*.doc *.xlsx *.xls *.pptx *.ppt *.odt *.ods *.odp *.rtf *.epub "
            "*.zip *.json);;PDF files (*.pdf);;Images (*.jpg *.jpeg *.png "
            "*.webp *.tif *.tiff *.bmp *.gif *.heic);;Office documents "
            "(*.docx *.xlsx *.pptx *.odt *.ods *.odp *.rtf *.epub);;"
            "All files (*)")
        self.add([Path(f) for f in files])

    def pick_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Add a folder",
                                                       str(Path.home()))
        if d:
            self.add(sorted(p for p in Path(d).iterdir() if p.is_file()))

    def add(self, paths):
        known = set(self.paths())
        added = 0
        for p in paths:
            p = Path(p)
            if str(p) in known or not p.exists() or not p.is_file():
                continue
            item = QtWidgets.QListWidgetItem(p.name)
            icons.item_icon(item, _file_icon(p), 17)
            item.setData(Qt.UserRole, str(p))
            item.setToolTip(str(p))
            self.list.addItem(item)
            known.add(str(p))
            added += 1
        if added:
            self._refresh_meta()
            self._update_dropzone()
            self.changed.emit()

    def _refresh_meta(self):
        import pymupdf as fitz
        for i in range(self.list.count()):
            item = self.list.item(i)
            path = Path(item.data(Qt.UserRole))
            key = str(path)
            if key not in self._meta:
                bits = [human_size(path.stat().st_size)]
                if is_pdf(path):
                    try:
                        d = fitz.open(path)
                        bits.append(f"{d.page_count} page"
                                    f"{'s' if d.page_count != 1 else ''}")
                        if d.needs_pass:
                            bits.append("password protected")
                        d.close()
                    except Exception:
                        bits.append("unreadable")
                elif is_image(path):
                    try:
                        from PIL import Image
                        with Image.open(path) as im:
                            bits.append(f"{im.width}x{im.height}")
                    except Exception:
                        pass
                self._meta[key] = "  ·  ".join(bits)
            item.setText(f"{path.name}      {self._meta[key]}")
        self._update_info()

    def _update_info(self):
        paths = self.paths()
        if not paths:
            self.info.setText("No files selected")
            return
        total = sum(Path(p).stat().st_size for p in paths if Path(p).exists())
        pdfs = sum(1 for p in paths if is_pdf(p))
        imgs = sum(1 for p in paths if is_image(p))
        bits = [f"{len(paths)} file{'s' if len(paths) != 1 else ''}",
                human_size(total)]
        if pdfs:
            bits.append(f"{pdfs} PDF")
        if imgs:
            bits.append(f"{imgs} image")
        self.info.setText("  ·  ".join(bits))

    def remove_selected(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._update_info()
        self._update_dropzone()
        self.changed.emit()

    def clear(self):
        self.list.clear()
        self._update_info()
        self._update_dropzone()
        self.changed.emit()

    def _update_dropzone(self):
        """The drop target only earns its space while the list is empty -
        files can still be dropped onto the list itself."""
        self.drop.setVisible(self.list.count() == 0)

    def _move(self, delta: int):
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        if not rows:
            return
        if delta < 0 and rows[0] == 0:
            return
        if delta > 0 and rows[-1] == self.list.count() - 1:
            return
        for r in (rows if delta < 0 else reversed(rows)):
            item = self.list.takeItem(r)
            self.list.insertItem(r + delta, item)
            item.setSelected(True)
        self.changed.emit()

    def paths(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole)
                for i in range(self.list.count())]

    def selected_paths(self) -> list[str]:
        return [i.data(Qt.UserRole) for i in self.list.selectedItems()]

    def set_paths(self, paths):
        self.list.clear()
        self.add(paths)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.remove_selected()
            return
        super().keyPressEvent(ev)


# ------------------------------------------------------------- param form

class ParamForm(QtWidgets.QWidget):
    """Builds editors for a tool's parameter spec and reads them back."""
    changed = QtCore.Signal()

    def __init__(self, params, parent=None):
        super().__init__(parent)
        self.params = list(params)
        self.editors: dict[str, QtWidgets.QWidget] = {}
        self.rows: dict[str, tuple] = {}
        self.form = QtWidgets.QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(10)
        self.form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.form.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        for p in self.params:
            self._add(p)
        self._apply_visibility()

    def _add(self, p: P):
        w = self._editor(p)
        self.editors[p.key] = w
        label = QtWidgets.QLabel(p.label)
        label.setWordWrap(True)
        label.setMinimumWidth(104)
        label.setMaximumWidth(190)
        if p.help:
            label.setToolTip(p.help)
            w.setToolTip(p.help)
        container = w
        if p.help:
            container = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(container)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            v.addWidget(w)
            hint = icon_label(p.help, "faint")
            hint.setWordWrap(True)
            v.addWidget(hint)
        if p.kind == "bool":
            self.form.addRow("", container)   # the checkbox carries its label
        else:
            self.form.addRow(label, container)
        self.rows[p.key] = (label, container)

    def _editor(self, p: P) -> QtWidgets.QWidget:
        kind = p.kind
        if kind == "bool":
            w = QtWidgets.QCheckBox(p.label)
            w.setChecked(bool(p.default))
            # long labels must wrap rather than widen the whole column
            w.setMinimumWidth(1)
            w.toggled.connect(self._on_change)
            return w
        if kind == "choice":
            w = QtWidgets.QComboBox()
            w.setSizeAdjustPolicy(
                QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(12)
            w.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                            QtWidgets.QSizePolicy.Fixed)
            w.addItems([str(c) for c in p.choices])
            if p.default is not None and str(p.default) in [str(c) for c
                                                            in p.choices]:
                w.setCurrentText(str(p.default))
            w.currentTextChanged.connect(self._on_change)
            return w
        if kind == "int":
            w = QtWidgets.QSpinBox()
            w.setRange(int(p.lo), int(min(p.hi, 2_000_000_000)))
            w.setValue(int(p.default or 0))
            w.setSuffix(p.suffix)
            w.setSingleStep(max(1, int(p.step)))
            w.valueChanged.connect(self._on_change)
            return w
        if kind == "float":
            w = QtWidgets.QDoubleSpinBox()
            w.setRange(float(p.lo), float(p.hi))
            w.setDecimals(2 if float(p.step) < 1 else 1)
            w.setSingleStep(float(p.step))
            w.setValue(float(p.default or 0))
            w.setSuffix(p.suffix)
            w.valueChanged.connect(self._on_change)
            return w
        if kind == "color":
            w = ColorButton(str(p.default or ""))
            w.changed.connect(self._on_change)
            return w
        if kind == "file":
            w = PathPicker(False)
            w.set_value(p.default)
            w.changed.connect(self._on_change)
            return w
        if kind == "dir":
            w = PathPicker(True)
            w.set_value(p.default)
            w.changed.connect(self._on_change)
            return w
        if kind == "text":
            w = QtWidgets.QPlainTextEdit()
            w.setPlainText(str(p.default or ""))
            w.setMinimumHeight(74)
            w.setMaximumHeight(150)
            w.textChanged.connect(self._on_change)
            return w
        if kind == "pages":
            w = QtWidgets.QLineEdit(str(p.default or ""))
            w.setPlaceholderText("all  ·  1-3,7  ·  odd  ·  even  ·  last")
            w.textChanged.connect(self._on_change)
            return w
        w = QtWidgets.QLineEdit(str(p.default or ""))
        if "password" in p.key:
            w.setEchoMode(QtWidgets.QLineEdit.Password)
            w.setPlaceholderText("only needed for protected files")
        w.textChanged.connect(self._on_change)
        return w

    def _on_change(self, *_):
        self._apply_visibility()
        self.changed.emit()

    def _apply_visibility(self):
        vals = self.values()
        for p in self.params:
            if not p.when:
                continue
            other, wanted = p.when
            cur = vals.get(other)
            show = any(str(cur) == str(w) or cur is w for w in wanted)
            label, container = self.rows[p.key]
            label.setVisible(show)
            container.setVisible(show)

    def values(self) -> dict:
        out = {}
        for p in self.params:
            w = self.editors[p.key]
            if isinstance(w, QtWidgets.QCheckBox):
                out[p.key] = w.isChecked()
            elif isinstance(w, QtWidgets.QComboBox):
                out[p.key] = w.currentText()
            elif isinstance(w, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                out[p.key] = w.value()
            elif isinstance(w, ColorButton):
                out[p.key] = w.value()
            elif isinstance(w, PathPicker):
                out[p.key] = w.value()
            elif isinstance(w, QtWidgets.QPlainTextEdit):
                out[p.key] = w.toPlainText()
            else:
                out[p.key] = w.text()
        return out

    def set_values(self, data: dict):
        for p in self.params:
            if p.key not in data:
                continue
            v = data[p.key]
            w = self.editors[p.key]
            try:
                if isinstance(w, QtWidgets.QCheckBox):
                    w.setChecked(bool(v))
                elif isinstance(w, QtWidgets.QComboBox):
                    if str(v) in [w.itemText(i) for i in range(w.count())]:
                        w.setCurrentText(str(v))
                elif isinstance(w, QtWidgets.QSpinBox):
                    w.setValue(int(float(v)))
                elif isinstance(w, QtWidgets.QDoubleSpinBox):
                    w.setValue(float(v))
                elif isinstance(w, ColorButton):
                    w.set_value(str(v))
                elif isinstance(w, PathPicker):
                    w.set_value(v)
                elif isinstance(w, QtWidgets.QPlainTextEdit):
                    w.setPlainText(str(v))
                else:
                    w.setText(str(v))
            except (TypeError, ValueError):
                continue
        self._apply_visibility()

    def focus_first(self):
        for p in self.params:
            if p.kind != "str" or "password" in p.key:
                continue
            self.editors[p.key].setFocus()
            return


# ----------------------------------------------------------- output panel

class OutputPanel(QtWidgets.QWidget):
    """Shows the files a job produced, with open/save/print actions."""
    reuse = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        head = QtWidgets.QHBoxLayout()
        self.title = icon_label("Results", "h2")
        head.addWidget(self.title)
        head.addStretch(1)
        self.count = icon_label("", "pill")
        head.addWidget(self.count)
        lay.addLayout(head)

        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setAlternatingRowColors(True)
        self.list.itemDoubleClicked.connect(
            lambda it: open_externally(it.data(Qt.UserRole)))
        lay.addWidget(self.list, 1)

        row = FlowLayout(spacing=6)
        self.btn_open = QtWidgets.QPushButton("Open")
        self.btn_open.setProperty("kind", "primary")
        self.btn_folder = QtWidgets.QPushButton("Show in files")
        self.btn_save = QtWidgets.QPushButton("Save a copy...")
        self.btn_zip = QtWidgets.QPushButton("Save all as ZIP")
        self.btn_print = QtWidgets.QPushButton("Print")
        self.btn_reuse = QtWidgets.QPushButton("Use as input")
        for b, name in ((self.btn_open, "open"), (self.btn_folder, "folder"),
                        (self.btn_save, "save"), (self.btn_zip, "zip"),
                        (self.btn_print, "printer"),
                        (self.btn_reuse, "refresh")):
            icons.apply(b, name, 15)
            b.setMinimumWidth(92)
            row.addWidget(b)
        lay.addLayout(row)

        self.btn_open.clicked.connect(self._open)
        self.btn_folder.clicked.connect(self._reveal)
        self.btn_save.clicked.connect(self._save_as)
        self.btn_zip.clicked.connect(self._zip)
        self.btn_print.clicked.connect(self._print)
        self.btn_reuse.clicked.connect(
            lambda: self.reuse.emit(self._targets()))
        self.set_files([])

    def set_files(self, files):
        self.list.clear()
        for f in files:
            f = Path(f)
            if not f.exists():
                continue
            item = QtWidgets.QListWidgetItem(
                f"{f.name}      {human_size(f.stat().st_size)}")
            icons.item_icon(item, _file_icon(f), 17)
            item.setData(Qt.UserRole, str(f))
            item.setToolTip(str(f))
            self.list.addItem(item)
        n = self.list.count()
        self.count.setText(f"{n} file{'s' if n != 1 else ''}" if n else "")
        for b in (self.btn_open, self.btn_folder, self.btn_save, self.btn_zip,
                  self.btn_print, self.btn_reuse):
            b.setEnabled(n > 0)
        self.btn_zip.setEnabled(n > 1)
        if n:
            self.list.setCurrentRow(0)

    def files(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole)
                for i in range(self.list.count())]

    def _targets(self) -> list[str]:
        sel = [i.data(Qt.UserRole) for i in self.list.selectedItems()]
        return sel or self.files()

    def _open(self):
        for f in self._targets()[:8]:
            open_externally(f)

    def _reveal(self):
        t = self._targets()
        if t:
            reveal_in_files(t[0])

    def _save_as(self):
        targets = self._targets()
        if not targets:
            return
        if len(targets) == 1:
            src = Path(targets[0])
            dest, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save a copy", str(Path.home() / src.name),
                f"{src.suffix.upper().lstrip('.')} file (*{src.suffix});;"
                f"All files (*)")
            if dest:
                import shutil
                shutil.copy2(src, dest)
                QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), "Saved")
            return
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Save copies into", str(Path.home()))
        if d:
            import shutil
            for f in targets:
                shutil.copy2(f, Path(d) / Path(f).name)

    def _zip(self):
        import zipfile
        files = self.files()
        if not files:
            return
        dest, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save as ZIP", str(Path.home() / "pdf-builder-output.zip"),
            "ZIP archive (*.zip)")
        if not dest:
            return
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, Path(f).name)
        QtWidgets.QMessageBox.information(
            self, "Saved", f"{len(files)} file(s) written to\n{dest}")

    def _print(self):
        t = self._targets()
        if not t:
            return
        if not print_file(t[0], self):
            QtWidgets.QMessageBox.information(
                self, "Print",
                "No printer command was available.\nOpen the file and print "
                "from your document viewer instead.")


class SummaryTable(QtWidgets.QTableWidget):
    """Key/value report used by the inspection tools."""

    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["Property", "Value"])
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.horizontalHeader().setStretchLastSection(True)
        self.setWordWrap(True)

    def show_data(self, data: dict):
        self.setRowCount(0)
        for k, v in (data or {}).items():
            r = self.rowCount()
            self.insertRow(r)
            self.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))
        self.resizeColumnToContents(0)
        self.resizeRowsToContents()
