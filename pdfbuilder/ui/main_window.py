"""Main application window: category sidebar, tool list and panel host."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from pdfbuilder import deps, registry
from pdfbuilder.registry import (CATEGORIES, CATEGORY_NAMES, POPULAR,
                                 Tool)
from pdfbuilder.ui import icons, theme
from pdfbuilder.ui.toolpanel import ToolPanel
from pdfbuilder.ui.widgets import icon_label, open_externally

Qt = QtCore.Qt

CONFIG = Path.home() / ".config" / "pdf-builder" / "settings.json"
DEFAULT_OUT = Path.home() / "PDF Builder"

VIEW_MODULES = {
    "viewer": "pdfbuilder.ui.views.viewer",
    "organizer": "pdfbuilder.ui.views.organizer",
    "editor": "pdfbuilder.ui.views.editor",
    "formfill": "pdfbuilder.ui.views.formfill",
    "fieldmaker": "pdfbuilder.ui.views.fieldmaker",
    "signature": "pdfbuilder.ui.views.signature",
    "compare": "pdfbuilder.ui.views.compare",
    "scanner": "pdfbuilder.ui.views.scanner",
    "chain": "pdfbuilder.ui.views.chain",
    "batch": "pdfbuilder.ui.views.batch",
    "presets": "pdfbuilder.ui.views.presets",
}


def load_settings() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2), encoding="utf-8")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, start_files=()):
        super().__init__()
        registry.load_all()
        self.settings = load_settings()
        self.dark = bool(self.settings.get("dark", True))
        self.outdir = Path(self.settings.get("outdir", str(DEFAULT_OUT)))
        self.panels: dict[str, QtWidgets.QWidget] = {}
        self.current_tool: Tool | None = None
        self.busy = False

        icons.set_theme(theme.colors(self.dark))
        self.setWindowIcon(icons.app_icon())
        self.setWindowTitle("PDF Builder")
        self.setMinimumSize(620, 520)   # usable on small laptop screens too
        self.resize(*self.settings.get("size", [1340, 880]))
        self.setAcceptDrops(True)

        self._build_ui()
        self._build_menus()
        self.apply_theme()

        first = self.settings.get("tool", "merge")
        self.select_category(self.settings.get("category", "popular"))
        if first in registry.REGISTRY:
            self.select_tool(first)
        if start_files:
            self.add_files(start_files)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # header -----------------------------------------------------------
        header = QtWidgets.QFrame()
        header.setObjectName("Header")
        hl = QtWidgets.QHBoxLayout(header)
        hl.setContentsMargins(16, 9, 16, 9)
        hl.setSpacing(10)
        self.brand_icon = QtWidgets.QLabel()
        self.brand_icon.setPixmap(icons.app_icon().pixmap(24, 24))
        hl.addWidget(self.brand_icon)
        brand = icon_label("PDF Builder", "h2")
        hl.addWidget(brand)
        hl.addWidget(icon_label("offline · nothing leaves this computer",
                                "pill"))
        hl.addStretch(1)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search all tools...   (Ctrl+K)")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.ic("search", 16),
                              QtWidgets.QLineEdit.LeadingPosition)
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(self._on_search)
        hl.addWidget(self.search)
        self.btn_theme = QtWidgets.QPushButton("Light mode")
        icons.apply(self.btn_theme, "sun", 16)
        self.btn_theme.setProperty("kind", "flat")
        self.btn_theme.clicked.connect(self.toggle_theme)
        hl.addWidget(self.btn_theme)
        outer.addWidget(header)

        # body -------------------------------------------------------------
        self.split = QtWidgets.QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        outer.addWidget(self.split, 1)

        side = QtWidgets.QFrame()
        side.setObjectName("Sidebar")
        side.setMinimumWidth(236)
        side.setMaximumWidth(400)
        sv = QtWidgets.QVBoxLayout(side)
        sv.setContentsMargins(10, 10, 8, 10)
        sv.setSpacing(6)

        self.cat_buttons: dict[str, QtWidgets.QPushButton] = {}
        cat_box = QtWidgets.QWidget()
        cv = QtWidgets.QVBoxLayout(cat_box)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(2)
        start = QtWidgets.QPushButton(f"Start here    {len(POPULAR)}")
        icons.apply(start, "star", 17)
        start.setProperty("kind", "cat")
        start.setCheckable(True)
        start.setCursor(Qt.PointingHandCursor)
        start.setToolTip("The jobs people use most often")
        start.clicked.connect(lambda _=False: self.select_category("popular"))
        cv.addWidget(start)
        self.cat_buttons["popular"] = start
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setStyleSheet("color: rgba(128,128,128,.25); max-height:1px;")
        cv.addWidget(line)
        for key, label in CATEGORIES:
            n = len(registry.by_category(key))
            btn = QtWidgets.QPushButton(f"{label.replace('&', '&&')}    {n}")
            icons.apply(btn, icons.CATEGORY_ICONS.get(key, "file"), 17)
            btn.setProperty("kind", "cat")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.select_category(k))
            cv.addWidget(btn)
            self.cat_buttons[key] = btn
        sv.addWidget(cat_box)
        sv.addStretch(1)
        tip = icon_label("Tip: drop files anywhere in the window.", "faint")
        tip.setWordWrap(True)
        sv.addWidget(tip)
        self.dep_note = icon_label("", "faint")
        self.dep_note.setWordWrap(True)
        self.dep_note.setOpenExternalLinks(False)
        sv.addWidget(self.dep_note)
        self.split.addWidget(side)

        # tool list --------------------------------------------------------
        tool_wrap = QtWidgets.QFrame()
        tool_wrap.setObjectName("Sidebar")
        tool_wrap.setMinimumWidth(230)
        tool_wrap.setMaximumWidth(420)
        tv = QtWidgets.QVBoxLayout(tool_wrap)
        tv.setContentsMargins(10, 12, 8, 10)
        tv.setSpacing(8)
        self.cat_combo = QtWidgets.QComboBox()
        self.cat_combo.addItem("Start here", "popular")
        for key, label in CATEGORIES:
            self.cat_combo.addItem(label, key)
        self.cat_combo.setVisible(False)
        self.cat_combo.currentIndexChanged.connect(
            lambda _i: self.select_category(self.cat_combo.currentData()))
        tv.addWidget(self.cat_combo)
        self.cat_title = icon_label("", "h2")
        self.cat_title.setWordWrap(True)
        tv.addWidget(self.cat_title)
        self.tool_list = QtWidgets.QListWidget()
        self.tool_list.setWordWrap(True)
        self.tool_list.setSpacing(1)
        self.tool_list.setUniformItemSizes(False)
        self.tool_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tool_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.tool_list.setIconSize(QtCore.QSize(17, 17))
        self.tool_list.currentItemChanged.connect(self._tool_row_changed)
        tv.addWidget(self.tool_list, 1)
        self.split.addWidget(tool_wrap)

        self.stack = QtWidgets.QStackedWidget()
        placeholder = QtWidgets.QLabel("Choose a tool on the left.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setProperty("role", "dim")
        self.stack.addWidget(placeholder)
        self.split.addWidget(self.stack)
        self.split.setSizes([250, 280, 810])
        self.split.setStretchFactor(2, 1)

        self.sidebar = side
        self.tool_wrap = tool_wrap
        self.setStatusBar(QtWidgets.QStatusBar())
        self._update_dep_note()

    def _build_menus(self):
        bar = self.menuBar()

        m = bar.addMenu("&File")
        act = m.addAction(icons.ic("plus", 16), "Add files...")
        act.setShortcut("Ctrl+O")
        act.triggered.connect(self._menu_add_files)
        act = m.addAction(icons.ic("folder", 16), "Add a folder...")
        act.triggered.connect(self._menu_add_folder)
        m.addSeparator()
        act = m.addAction(icons.ic("settings", 16), "Set output folder...")
        act.triggered.connect(self._menu_outdir)
        act = m.addAction(icons.ic("open", 16), "Open output folder")
        act.setShortcut("Ctrl+Shift+O")
        act.triggered.connect(lambda: self._open_outdir())
        m.addSeparator()
        act = m.addAction(icons.ic("trash", 16), "Clear temporary files")
        act.triggered.connect(self.clear_temp)
        m.addSeparator()
        act = m.addAction(icons.ic("close", 16), "Quit")
        act.setShortcut("Ctrl+Q")
        act.triggered.connect(self.close)

        m = bar.addMenu("&Tools")
        for key, label in CATEGORIES:
            sub = m.addMenu(icons.ic(icons.CATEGORY_ICONS.get(key, "file"), 16),
                            label)
            for t in sorted(registry.by_category(key), key=lambda t: t.name):
                a = sub.addAction(icons.ic(icons.for_tool(t.id, key), 16),
                                  t.name)
                a.triggered.connect(lambda _=False, tid=t.id:
                                    self.select_tool(tid, reveal=True))

        m = bar.addMenu("&View")
        act = m.addAction(icons.ic("search", 16), "Search tools")
        act.setShortcut("Ctrl+K")
        act.triggered.connect(lambda: (self.search.setFocus(),
                                       self.search.selectAll()))
        act = m.addAction(icons.ic("sun", 16), "Toggle dark / light")
        act.setShortcut("Ctrl+D")
        act.triggered.connect(self.toggle_theme)
        m.addSeparator()
        act = m.addAction("Next tool")
        act.setShortcut("Ctrl+Tab")
        act.triggered.connect(lambda: self._step_tool(1))
        act = m.addAction("Previous tool")
        act.setShortcut("Ctrl+Shift+Tab")
        act.triggered.connect(lambda: self._step_tool(-1))
        m.addSeparator()
        act = m.addAction("Full screen")
        act.setShortcut("F11")
        act.triggered.connect(
            lambda: self.showNormal() if self.isFullScreen()
            else self.showFullScreen())

        m = bar.addMenu("&Help")
        act = m.addAction(icons.ic("settings", 16),
                          "Optional components...")
        act.triggered.connect(self.show_deps)
        act = m.addAction(icons.ic("refresh", 16), "Re-check components")
        act.triggered.connect(self.recheck_deps)
        m.addSeparator()
        act = m.addAction(icons.ic("menu", 16), "Keyboard shortcuts")
        act.triggered.connect(self.show_shortcuts)
        act = m.addAction(icons.ic("info", 16), "About PDF Builder")
        act.triggered.connect(self.show_about)

    # ------------------------------------------------------------ selection
    def select_category(self, key: str):
        for k, btn in self.cat_buttons.items():
            btn.setChecked(k == key)
        self.category = key
        if key == "popular":
            self.cat_title.setText("Start here")
            self._populate_tools([registry.REGISTRY[t] for t in POPULAR
                                  if t in registry.REGISTRY])
            return
        i = self.cat_combo.findData(key)
        if i >= 0 and self.cat_combo.currentIndex() != i:
            self.cat_combo.blockSignals(True)
            self.cat_combo.setCurrentIndex(i)
            self.cat_combo.blockSignals(False)
        self.cat_title.setText(CATEGORY_NAMES.get(key, key))
        self._populate_tools(registry.by_category(key))

    def _populate_tools(self, tools):
        self.tool_list.blockSignals(True)
        self.tool_list.clear()
        self.tool_ids: list[str] = []
        for t in tools:
            label = t.name
            if t.view:
                label += "  ◱"
            item = QtWidgets.QListWidgetItem(label)
            tip = t.summary or t.name
            missing = [n for n in t.needs if not deps.have(n)]
            if missing:
                item.setText(label + "   ·")
                tip += f"\n\nNeeds: {', '.join(missing)}"
            if getattr(self, "category", "") == "popular":
                tip = f"{CATEGORY_NAMES.get(t.category, '')} · {tip}"
            item.setToolTip(tip)
            icons.item_icon(item, icons.for_tool(t.id, t.category), 17)
            item.setData(Qt.UserRole, t.id)
            item.setSizeHint(QtCore.QSize(0, 34))
            self.tool_list.addItem(item)
            self.tool_ids.append(t.id)
        self.tool_list.blockSignals(False)
        if self.current_tool and self.current_tool.id in self.tool_ids:
            self.tool_list.blockSignals(True)
            self.tool_list.setCurrentRow(
                self.tool_ids.index(self.current_tool.id))
            self.tool_list.blockSignals(False)

    def _tool_row_changed(self, item, _prev=None):
        if item is not None:
            self.select_tool(item.data(Qt.UserRole))

    def _on_search(self, text: str):
        text = text.strip().lower()
        if not text:
            self.cat_title.setText(CATEGORY_NAMES.get(self.category, ""))
            self._populate_tools(registry.by_category(self.category))
            return
        words = text.split()
        hits = []
        for t in registry.REGISTRY.values():
            blob = f"{t.name} {t.summary} {t.id} {CATEGORY_NAMES.get(t.category,'')}".lower()
            if all(w in blob for w in words):
                hits.append(t)
        hits.sort(key=lambda t: (not t.name.lower().startswith(text), t.name))
        self.cat_title.setText(f"{len(hits)} match"
                               f"{'es' if len(hits) != 1 else ''}")
        self._populate_tools(hits)

    def select_tool(self, tool_id: str, reveal: bool = False):
        tool = registry.REGISTRY.get(tool_id)
        if tool is None:
            return
        if reveal:
            self.search.clear()
            self.select_category(tool.category)
        self.current_tool = tool
        ids = getattr(self, "tool_ids", [])
        if tool_id in ids and self.tool_list.currentRow() != ids.index(tool_id):
            self.tool_list.blockSignals(True)
            self.tool_list.setCurrentRow(ids.index(tool_id))
            self.tool_list.blockSignals(False)
        panel = self.panels.get(tool_id)
        if panel is None:
            panel = self._make_panel(tool)
            self.panels[tool_id] = panel
            self.stack.addWidget(panel)
        self.stack.setCurrentWidget(panel)
        self.statusBar().showMessage(tool.summary or tool.name, 6000)

    def _make_panel(self, tool: Tool) -> QtWidgets.QWidget:
        if tool.view:
            try:
                import importlib
                mod = importlib.import_module(VIEW_MODULES[tool.view])
                panel = mod.build(tool, self)
            except Exception as e:                       # keep the app usable
                import traceback
                panel = QtWidgets.QWidget()
                v = QtWidgets.QVBoxLayout(panel)
                v.addWidget(icon_label(f"The {tool.name} panel could not be "
                                       f"loaded.", "h2"))
                err = QtWidgets.QPlainTextEdit(
                    f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}")
                err.setReadOnly(True)
                v.addWidget(err)
            return panel
        panel = ToolPanel(tool, self.outdir, self)
        panel.busy_changed.connect(self._on_busy)
        return panel

    def _step_tool(self, delta: int):
        ids = list(getattr(self, "tool_ids", []))
        if not ids or not self.current_tool:
            return
        try:
            i = ids.index(self.current_tool.id)
        except ValueError:
            i = 0
        self.select_tool(ids[(i + delta) % len(ids)])

    # ---------------------------------------------------------- responsive
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._apply_responsive()

    def _apply_responsive(self):
        """Fold the navigation columns away when the window gets narrow."""
        w = self.width()
        show_sidebar = w >= 1080
        show_tools = w >= 780
        if self.sidebar.isVisible() != show_sidebar:
            self.sidebar.setVisible(show_sidebar)
        if self.tool_wrap.isVisible() != show_tools:
            self.tool_wrap.setVisible(show_tools)
        # when the category buttons are hidden, offer the drop-down instead
        self.cat_combo.setVisible(not show_sidebar and show_tools)
        self.cat_title.setVisible(show_sidebar)
        if not show_tools:
            self.statusBar().showMessage(
                "Window is narrow - use the Tools menu to switch tool.", 4000)

    # ----------------------------------------------------------------- misc
    def add_files(self, paths):
        panel = self.stack.currentWidget()
        if hasattr(panel, "add_files"):
            panel.add_files(paths)
        else:
            self.select_tool("merge", reveal=True)
            self.stack.currentWidget().add_files(paths)

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [Path(u.toLocalFile()) for u in ev.mimeData().urls()]
        files = []
        for p in paths:
            if p.is_dir():
                files += sorted(q for q in p.iterdir() if q.is_file())
            elif p.exists():
                files.append(p)
        if files:
            self.add_files(files)
        ev.acceptProposedAction()

    def _menu_add_files(self):
        panel = self.stack.currentWidget()
        if hasattr(panel, "files"):
            panel.files.pick_files()

    def _menu_add_folder(self):
        panel = self.stack.currentWidget()
        if hasattr(panel, "files"):
            panel.files.pick_folder()

    def _menu_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Where should results be saved?", str(self.outdir))
        if not d:
            return
        self.outdir = Path(d)
        for panel in self.panels.values():
            if hasattr(panel, "set_outdir"):
                panel.set_outdir(self.outdir)

    def _open_outdir(self):
        self.outdir.mkdir(parents=True, exist_ok=True)
        open_externally(self.outdir)

    def clear_temp(self):
        import shutil
        import tempfile
        root = Path(tempfile.gettempdir())
        removed = 0
        for p in root.glob("pdfbuilder-*"):
            shutil.rmtree(p, ignore_errors=True)
            removed += 1
        for p in self.outdir.glob("**/.chain-work"):
            shutil.rmtree(p, ignore_errors=True)
            removed += 1
        QtWidgets.QMessageBox.information(
            self, "Temporary files",
            f"Removed {removed} temporary folder(s)." if removed
            else "There were no temporary files to remove.")

    def _on_busy(self, busy: bool):
        self.busy = busy
        self.statusBar().showMessage("Working..." if busy else "Ready", 3000)

    # ---------------------------------------------------------------- theme
    def apply_theme(self):
        app = QtWidgets.QApplication.instance()
        app.setStyleSheet(theme.stylesheet(self.dark))
        icons.set_theme(theme.colors(self.dark))
        self.btn_theme.setText("Light mode" if self.dark else "Dark mode")
        self.search.actions()[0].setIcon(icons.ic("search", 16)) \
            if self.search.actions() else None
        self._repaint_tool_icons()
        for panel in self.panels.values():
            if hasattr(panel, "theme_changed"):
                panel.theme_changed(self.dark)

    def _repaint_tool_icons(self):
        for i in range(self.tool_list.count()):
            item = self.tool_list.item(i)
            tid = item.data(Qt.UserRole)
            tool = registry.REGISTRY.get(tid)
            if tool is not None:
                icons.item_icon(item, icons.for_tool(tid, tool.category), 17)

    def toggle_theme(self):
        self.dark = not self.dark
        self.apply_theme()

    def colors(self) -> dict:
        return theme.colors(self.dark)

    # ----------------------------------------------------------- help/about
    def _update_dep_note(self):
        missing = [(n, pkg, what) for n, ok, pkg, what in deps.report()
                   if not ok]
        if not missing:
            self.dep_note.setText("All optional components are installed.")
            return
        self.dep_note.setText(
            f"{len(missing)} optional component(s) not installed - "
            f"see Help → Optional components.")

    def recheck_deps(self):
        deps.reset_cache()
        self._update_dep_note()
        self._populate_tools(registry.by_category(self.category))
        QtWidgets.QMessageBox.information(self, "Components",
                                          "Re-checked installed components.")

    def show_deps(self):
        rows = deps.report()
        from pdfbuilder.core.ocr import any_engine, have_rapidocr
        html = ["<h3>Optional components</h3>",
                "<p>PDF Builder works without these. Each one unlocks extra "
                "features.</p><table cellpadding='6'>"]
        for name, ok, pkg, what in rows:
            mark = "installed" if ok else "not installed"
            colour = "#3ec07a" if ok else "#e9a33a"
            html.append(
                f"<tr><td><b>{name}</b></td>"
                f"<td style='color:{colour}'>{mark}</td>"
                f"<td>{what}</td>"
                f"<td><code>sudo apt install {pkg}</code></td></tr>")
        html.append("</table>")
        html.append(
            "<tr><td><b>built-in OCR</b></td>"
            f"<td style='color:{'#3ec07a' if have_rapidocr() else '#e9a33a'}'>"
            f"{'installed' if have_rapidocr() else 'not installed'}</td>"
            "<td>Text recognition with no system packages</td>"
            "<td><code>.venv/bin/pip install rapidocr-onnxruntime</code>"
            "</td></tr>")
        missing = [pkg for _, ok, pkg, _ in rows if not ok]
        if missing:
            html.append("<p>Install everything at once:<br><code>sudo apt "
                        "install " + " ".join(sorted(set(missing))) +
                        "</code></p>")
            html.append("<p>For more OCR languages:<br><code>sudo apt install "
                        "tesseract-ocr-hin tesseract-ocr-fra ...</code></p>")
        if any_engine():
            html.append("<p style='color:#3ec07a'>Text recognition is "
                        "working right now.</p>")
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Optional components")
        box.setTextFormat(Qt.RichText)
        box.setText("".join(html))
        box.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.exec()

    def show_shortcuts(self):
        rows = [("Ctrl+O", "Add files"), ("Ctrl+K", "Search tools"),
                ("Ctrl+Enter", "Run the current tool"),
                ("Ctrl+D", "Dark / light mode"),
                ("Ctrl+Tab", "Next tool in this category"),
                ("Ctrl+Shift+O", "Open the output folder"),
                ("Delete", "Remove the selected input files"),
                ("F11", "Full screen"), ("Ctrl+Q", "Quit"),
                ("+ / -", "Zoom in the viewer and editor"),
                ("Arrow keys", "Move between pages in the viewer")]
        html = "<h3>Keyboard</h3><table cellpadding='5'>" + "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows
        ) + "</table>"
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Keyboard shortcuts")
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        box.exec()

    def show_about(self):
        import pymupdf
        n = len(registry.REGISTRY)
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("About PDF Builder")
        box.setTextFormat(Qt.RichText)
        box.setText(
            f"<h3>PDF Builder</h3>"
            f"<p>{n} tools for PDFs, images, scans and office documents.</p>"
            f"<p>Everything runs on this computer. No file is ever uploaded, "
            f"and the app keeps working with no network connection.</p>"
            f"<p style='color:#888'>PyMuPDF {pymupdf.__doc__.split()[1] if pymupdf.__doc__ else ''} "
            f"· Qt for Python · Linux desktop</p>")
        box.exec()

    # --------------------------------------------------------------- closing
    def closeEvent(self, ev):
        if self.busy:
            if QtWidgets.QMessageBox.question(
                    self, "Still working",
                    "A job is still running. Quit anyway?") \
                    != QtWidgets.QMessageBox.Yes:
                ev.ignore()
                return
        for panel in self.panels.values():
            worker = getattr(panel, "worker", None)
            if worker is not None:
                worker.cancel()
                worker.wait(2500)
        self.settings.update({
            "dark": self.dark, "outdir": str(self.outdir),
            "category": getattr(self, "category", "organize"),
            "tool": self.current_tool.id if self.current_tool else "merge",
            "size": [self.width(), self.height()]})
        try:
            save_settings(self.settings)
        except OSError:
            pass
        ev.accept()
