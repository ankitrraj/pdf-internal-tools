"""The generated panel used by every non-interactive tool."""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder import deps
from pdfbuilder.core.batch import (delete_preset, presets_for, save_preset)
from pdfbuilder.core.common import is_image, is_pdf
from pdfbuilder.registry import Tool
from pdfbuilder.ui import icons
from pdfbuilder.ui.runner import Worker
from pdfbuilder.ui.widgets import (FileList, OutputPanel, ParamForm,
                                   SummaryTable, icon_label)

Qt = QtCore.Qt


class ToolPanel(QtWidgets.QWidget):
    """Inputs + generated options + run controls + results for one tool."""

    busy_changed = QtCore.Signal(bool)
    request_view = QtCore.Signal(str, list)

    def __init__(self, tool: Tool, outdir: Path, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.outdir = Path(outdir)
        self.worker: Worker | None = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        # ------------------------------------------------------------ header
        head = QtWidgets.QVBoxLayout()
        head.setSpacing(3)
        title_row = QtWidgets.QHBoxLayout()
        title_row.setSpacing(9)
        self.title_icon = QtWidgets.QLabel()
        self.title_icon.setPixmap(
            icons.pixmap(icons.for_tool(tool.id, tool.category), 24,
                         icons.current("accent")))
        title_row.addWidget(self.title_icon)
        self.title = icon_label(tool.name, "h1")
        title_row.addWidget(self.title)
        title_row.addStretch(1)
        for need in tool.needs:
            if not deps.have(need):
                warn = icon_label(f"needs {need}", "pill")
                warn.setToolTip(f"Install it with: sudo apt install "
                                f"{deps.EXTERNAL.get(need, ((), need, ''))[1]}")
                title_row.addWidget(warn)
        head.addLayout(title_row)
        if tool.summary:
            sub = icon_label(tool.summary, "dim")
            sub.setWordWrap(True)
            head.addWidget(sub)
        root.addLayout(head)

        # ------------------------------------------------------------- split
        self.top_split = QtWidgets.QSplitter(Qt.Horizontal)
        self.top_split.setChildrenCollapsible(False)

        left = QtWidgets.QWidget()
        left.setMinimumHeight(176)
        left.setMinimumWidth(260)
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        lv.addWidget(icon_label(self._input_label(), "h2"))
        self.files = FileList()
        self.files.changed.connect(self._validate)
        lv.addWidget(self.files, 1)
        self.top_split.addWidget(left)

        right = QtWidgets.QWidget()
        right.setMinimumHeight(190)
        right.setMinimumWidth(300)
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        opt_head = QtWidgets.QHBoxLayout()
        opt_head.addWidget(icon_label("Options", "h2"))
        opt_head.addStretch(1)
        self.preset_box = QtWidgets.QComboBox()
        self.preset_box.setMinimumWidth(150)
        self.preset_box.setToolTip("Saved presets for this tool")
        self.btn_preset_save = QtWidgets.QPushButton("Save preset")
        icons.apply(self.btn_preset_save, "star", 15)
        self.btn_preset_save.setProperty("kind", "flat")
        self.btn_preset_del = QtWidgets.QPushButton("Delete")
        self.btn_preset_del.setProperty("kind", "flat")
        self.btn_reset = QtWidgets.QPushButton("Reset")
        icons.apply(self.btn_reset, "refresh", 15)
        self.btn_reset.setProperty("kind", "flat")
        if tool.params:
            opt_head.addWidget(self.preset_box)
            opt_head.addWidget(self.btn_preset_save)
            opt_head.addWidget(self.btn_preset_del)
            opt_head.addWidget(self.btn_reset)
        rv.addLayout(opt_head)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(300)
        inner = QtWidgets.QWidget()
        iv = QtWidgets.QVBoxLayout(inner)
        iv.setContentsMargins(2, 2, 10, 2)
        self.form = ParamForm(tool.params)
        iv.addWidget(self.form)
        if not tool.params:
            iv.addWidget(icon_label("This tool has no settings - just add "
                                    "your files and run it.", "dim"))
        iv.addStretch(1)
        scroll.setWidget(inner)
        rv.addWidget(scroll, 1)
        self.top_split.addWidget(right)
        self.top_split.setSizes([400, 620])
        root.addWidget(self.top_split, 3)

        # --------------------------------------------------------- run strip
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self.batch_box = QtWidgets.QCheckBox("Run on every file separately")
        self.batch_box.setChecked(True)
        self.batch_box.setToolTip(
            "On: each file is processed on its own with these same settings.\n"
            "Off: only the first file is used.")
        self.batch_box.setVisible(tool.batchable and not tool.multi)
        bar.addWidget(self.batch_box)
        bar.addStretch(1)
        self.out_label = QtWidgets.QPushButton("")
        icons.apply(self.out_label, "folder", 15)
        self.out_label.setProperty("kind", "flat")
        self.out_label.setToolTip("Where results are written - click to change")
        self.out_label.clicked.connect(self._choose_outdir)
        bar.addWidget(self.out_label)
        self.btn_run = QtWidgets.QPushButton("Run")
        icons.apply(self.btn_run, "play", 16)
        self.btn_run.setProperty("kind", "primary")
        self.btn_run.setShortcut("Ctrl+Return")
        self.btn_run.setToolTip("Run  (Ctrl+Enter)")
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        icons.apply(self.btn_cancel, "stop", 16)
        self.btn_cancel.setProperty("kind", "danger")
        self.btn_cancel.setVisible(False)
        bar.addWidget(self.btn_run)
        bar.addWidget(self.btn_cancel)
        root.addLayout(bar)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status = icon_label("", "faint")
        root.addWidget(self.status)

        # ----------------------------------------------------------- results
        self.tabs = QtWidgets.QTabWidget()
        self.results = OutputPanel()
        self.results.reuse.connect(self._reuse)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setFont(QtGui.QFont("monospace", 10))
        self.report = SummaryTable()
        self.tabs.addTab(self.results, icons.ic("files", 16), "Results")
        self.tabs.addTab(self.log, icons.ic("list", 16), "Activity")
        self.tabs.addTab(self.report, icons.ic("info", 16), "Report")
        root.addWidget(self.tabs, 2)

        self.btn_run.clicked.connect(self.run)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_reset.clicked.connect(self._reset)
        self.btn_preset_save.clicked.connect(self._save_preset)
        self.btn_preset_del.clicked.connect(self._delete_preset)
        self.preset_box.currentIndexChanged.connect(self._load_preset)

        self._refresh_presets()
        self._update_outdir_label()
        self._validate()

    # --------------------------------------------------------------- helpers
    def _input_label(self) -> str:
        kind = {"pdf": "PDF file", "pdf+": "PDF files", "image+": "Images",
                "any": "File", "any+": "Files",
                "none": "No input needed"}.get(self.tool.inputs, "Files")
        if self.tool.inputs == "none":
            return "Input"
        plural = "s" if self.tool.multi else ""
        return f"Input {kind}" if plural else f"Input {kind}"

    def set_outdir(self, path):
        self.outdir = Path(path)
        self._update_outdir_label()

    def theme_changed(self, dark: bool):
        self.title_icon.setPixmap(
            icons.pixmap(icons.for_tool(self.tool.id, self.tool.category), 24,
                         icons.current("accent")))
        for i, name in enumerate(("files", "list", "info")):
            self.tabs.setTabIcon(i, icons.ic(name, 16))

    def _update_outdir_label(self):
        p = str(self.outdir)
        home = str(Path.home())
        if p.startswith(home):
            p = "~" + p[len(home):]
        self.out_label.setText(f"Save to:  {p}")

    def _choose_outdir(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Where should results be saved?", str(self.outdir))
        if d:
            self.set_outdir(d)

    def add_files(self, paths):
        self.files.add(paths)

    def _reuse(self, paths):
        self.files.set_paths(paths)
        self.tabs.setCurrentIndex(0)

    def _validate(self):
        n = len(self.files.paths())
        need = self.tool.inputs
        ok, why = True, ""
        if need == "none":
            ok = True
        elif n == 0:
            ok, why = False, "Add at least one file to continue."
        elif need == "pdf+" and sum(1 for p in self.files.paths()
                                    if is_pdf(p)) < 2:
            ok, why = False, "This tool needs two or more PDF files."
        elif need == "pdf" and not any(is_pdf(p) for p in self.files.paths()):
            ok, why = False, "None of the selected files is a PDF."
        elif need == "image+" and not any(is_image(p) for p
                                          in self.files.paths()):
            ok, why = False, "Select image files for this tool."
        self.btn_run.setEnabled(ok and self.worker is None)
        self.status.setText(why)
        self.status.setProperty("role", "warn" if why else "faint")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    # ---------------------------------------------------------------- presets
    def _refresh_presets(self):
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        self.preset_box.addItem("Default settings")
        for name in sorted(presets_for(self.tool.id)):
            self.preset_box.addItem(name)
        self.preset_box.blockSignals(False)

    def _load_preset(self, idx):
        if idx <= 0:
            return
        name = self.preset_box.currentText()
        data = presets_for(self.tool.id).get(name)
        if data:
            self.form.set_values(data.get("params", {}))
            self._log(f"Loaded preset '{name}'.")

    def _save_preset(self):
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save preset", "Name this set of settings:",
            text=self.preset_box.currentText()
            if self.preset_box.currentIndex() > 0 else "")
        if not ok or not name.strip():
            return
        save_preset(name.strip(), self.tool.id, self.form.values())
        self._refresh_presets()
        self.preset_box.setCurrentText(name.strip())
        self._log(f"Saved preset '{name.strip()}'.")

    def _delete_preset(self):
        if self.preset_box.currentIndex() <= 0:
            return
        name = self.preset_box.currentText()
        if QtWidgets.QMessageBox.question(
                self, "Delete preset", f"Delete the preset '{name}'?") \
                == QtWidgets.QMessageBox.Yes:
            delete_preset(name)
            self._refresh_presets()

    def _reset(self):
        self.form.set_values(self.tool.defaults())
        self.preset_box.setCurrentIndex(0)

    # -------------------------------------------------------------- running
    def _log(self, msg: str):
        self.log.appendPlainText(str(msg))

    def run(self):
        if self.worker is not None:
            return
        inputs = self.files.paths()
        if self.tool.inputs != "none" and not inputs:
            self._validate()
            return
        try:
            self.outdir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QtWidgets.QMessageBox.critical(
                self, "Cannot write there",
                f"{self.outdir} cannot be used:\n{e}\n\n"
                f"Pick another output folder.")
            return
        self.log.clear()
        self.report.show_data({})
        self.results.set_files([])
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_run.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.status.setProperty("role", "faint")
        self.status.setText("Working...")
        self._log(f"{self.tool.name}  ·  {len(inputs)} input file(s)")

        self.worker = Worker(self.tool, inputs, self.form.values(),
                             self.outdir,
                             batch=self.batch_box.isChecked()
                             and self.batch_box.isVisible())
        self.worker.progressed.connect(self._on_progress)
        self.worker.logged.connect(self._log)
        self.worker.finished_ok.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.cancelled.connect(self._on_cancelled)
        self.busy_changed.emit(True)
        self.worker.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel()
            self.status.setText("Stopping...")
            self.btn_cancel.setEnabled(False)

    def _on_progress(self, frac: float, msg: str):
        self.progress.setValue(int(frac * 1000))
        if msg:
            self.status.setText(msg)

    def _finish(self):
        self.worker = None
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(False)
        self.busy_changed.emit(False)
        self._validate()

    def _on_done(self, files, summary, secs):
        self._finish()
        self.results.set_files(files)
        if summary:
            self.report.show_data(summary)
            self.tabs.setCurrentIndex(2 if not files else 0)
        else:
            self.tabs.setCurrentIndex(0 if files else 1)
        if files:
            msg = (f"Finished in {secs:.1f}s  ·  "
                   f"{len(files)} file{'s' if len(files) != 1 else ''} written")
        else:
            msg = f"Finished in {secs:.1f}s"
        self.status.setProperty("role", "good")
        self.status.setText(msg)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self._log(msg)

    def _on_failed(self, msg, detail):
        self._finish()
        self.status.setProperty("role", "bad")
        self.status.setText(msg.splitlines()[0][:140])
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self._log("ERROR: " + msg)
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("That did not work")
        box.setText(msg)
        if detail:
            box.setDetailedText(detail)
            self._log(detail)
        box.exec()

    def _on_cancelled(self):
        self._finish()
        self.status.setText("Cancelled.")
        self._log("Cancelled by the user.")

    # ------------------------------------------------------------ responsive
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        want = Qt.Vertical if self.width() < 760 else Qt.Horizontal
        if self.top_split.orientation() != want:
            self.top_split.setOrientation(want)
            # a stacked layout needs its own sensible split
            self.top_split.setSizes([300, 420] if want == Qt.Vertical
                                    else [400, 620])
            self.tabs.setMaximumHeight(240 if want == Qt.Vertical
                                       else 16777215)
