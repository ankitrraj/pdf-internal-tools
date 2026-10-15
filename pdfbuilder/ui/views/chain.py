"""Workflow builder: run several tools in sequence and save the recipe."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfbuilder import registry
from pdfbuilder.core.batch import delete_chain, load_chains, save_chain
from pdfbuilder.registry import CATEGORY_NAMES
from pdfbuilder.ui.runner import ChainWorker
from pdfbuilder.ui.views.common import ToolBarRow
from pdfbuilder.ui import icons
from pdfbuilder.ui.widgets import (FileList, OutputPanel, ParamForm,
                                   icon_label)

Qt = QtCore.Qt


class StepDialog(QtWidgets.QDialog):
    """Pick a tool and set its options for one step of a workflow."""

    def __init__(self, parent=None, tool_id=None, params=None):
        super().__init__(parent)
        self.setWindowTitle("Workflow step")
        self.resize(640, 640)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(8)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search tools...")
        lay.addWidget(self.search)
        self.combo = QtWidgets.QComboBox()
        self._fill_combo()
        lay.addWidget(self.combo)
        self.summary = icon_label("", "dim")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        lay.addWidget(self.scroll, 1)
        self.form: ParamForm | None = None

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.search.textChanged.connect(self._fill_combo)
        self.combo.currentIndexChanged.connect(self._tool_changed)
        if tool_id:
            i = self.combo.findData(tool_id)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self._tool_changed()
        if params and self.form:
            self.form.set_values(params)

    def _fill_combo(self, text=""):
        text = (text or "").strip().lower()
        current = self.combo.currentData()
        self.combo.blockSignals(True)
        self.combo.clear()
        from pdfbuilder.ui import icons as _icons
        for t in registry.REGISTRY.values():
            if t.view:
                continue                   # interactive tools cannot queue
            label = f"{CATEGORY_NAMES.get(t.category, '')}  ·  {t.name}"
            if text and text not in label.lower() and text not in t.id:
                continue
            self.combo.addItem(_icons.ic(_icons.for_tool(t.id, t.category), 16),
                               label, t.id)
        if current:
            i = self.combo.findData(current)
            if i >= 0:
                self.combo.setCurrentIndex(i)
        self.combo.blockSignals(False)
        self._tool_changed()

    def _tool_changed(self, *_):
        tool_id = self.combo.currentData()
        if not tool_id:
            return
        tool = registry.REGISTRY[tool_id]
        self.summary.setText(tool.summary)
        host = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(host)
        self.form = ParamForm(tool.params)
        v.addWidget(self.form)
        if not tool.params:
            v.addWidget(icon_label("This tool has no settings.", "faint"))
        v.addStretch(1)
        self.scroll.setWidget(host)

    def result_step(self) -> dict:
        return {"tool": self.combo.currentData(),
                "params": self.form.values() if self.form else {}}


class ChainPanel(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.steps: list[dict] = []
        self.worker: ChainWorker | None = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(9)
        root.addWidget(icon_label(tool.name, "h1"))
        sub = icon_label("Each step receives the files the previous step "
                         "produced. Save the sequence as a workflow to reuse "
                         "it on other files.", "dim")
        sub.setWordWrap(True)
        root.addWidget(sub)

        split = QtWidgets.QSplitter(Qt.Horizontal)
        left = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        lv.addWidget(icon_label("Input files", "h2"))
        self.files = FileList()
        lv.addWidget(self.files, 1)
        split.addWidget(left)

        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)

        wf_row = ToolBarRow(wrap=True)
        wf_row.add(QtWidgets.QLabel("Saved workflow"))
        self.wf_box = QtWidgets.QComboBox()
        self.wf_box.setMinimumWidth(180)
        wf_row.add(self.wf_box)
        wf_row.button("Load", self.load_workflow, icon="open")
        wf_row.button("Save as...", self.save_workflow, icon="save")
        wf_row.button("Delete", self.delete_workflow, kind="danger", icon="trash")
        wf_row.stretch()
        rv.addWidget(wf_row)

        rv.addWidget(icon_label("Steps", "h2"))
        self.list = QtWidgets.QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setMinimumHeight(170)
        self.list.setIconSize(QtCore.QSize(17, 17))
        self.list.itemDoubleClicked.connect(lambda _: self.edit_step())
        rv.addWidget(self.list, 1)

        row = ToolBarRow(wrap=True)
        row.button("Add step...", self.add_step, kind="primary", icon="plus")
        row.button("Edit", self.edit_step, icon="pen")
        row.button("Move up", lambda: self.move(-1), icon="up")
        row.button("Move down", lambda: self.move(1), icon="down")
        row.button("Duplicate", self.duplicate, icon="copy")
        row.button("Remove", self.remove, kind="danger", icon="trash")
        row.stretch()
        rv.addWidget(row)

        run_row = ToolBarRow(wrap=True)
        self.keep_box = QtWidgets.QCheckBox("Keep the files from every step")
        run_row.add(self.keep_box)
        run_row.stretch()
        self.btn_run = run_row.button("Run the workflow", self.run,
                                      kind="primary", shortcut="Ctrl+Return",
                                      icon="play")
        self.btn_cancel = run_row.button("Cancel", self.cancel, kind="danger",
                                         icon="stop")
        self.btn_cancel.setVisible(False)
        rv.addWidget(run_row)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setVisible(False)
        rv.addWidget(self.progress)
        self.status = icon_label("", "faint")
        self.status.setWordWrap(True)
        rv.addWidget(self.status)

        self.tabs = QtWidgets.QTabWidget()
        self.results = OutputPanel()
        self.results.reuse.connect(lambda p: self.files.set_paths(p))
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.tabs.addTab(self.results, icons.ic("files", 16), "Results")
        self.tabs.addTab(self.log, icons.ic("list", 16), "Activity")
        self.tabs.setMinimumHeight(190)
        rv.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([360, 720])
        root.addWidget(split, 1)

        self._refresh_workflows()
        self.refresh()

    # --------------------------------------------------------------- steps
    def add_files(self, paths):
        self.files.add(paths)

    def refresh(self):
        self.list.clear()
        for n, step in enumerate(self.steps, 1):
            tool = registry.REGISTRY.get(step["tool"])
            name = tool.name if tool else step["tool"]
            changed = []
            if tool:
                defaults = tool.defaults()
                for k, v in (step.get("params") or {}).items():
                    if k in defaults and str(defaults[k]) != str(v) and \
                            v not in ("", None):
                        changed.append(f"{k}={v}")
            detail = ("   " + ", ".join(changed[:4])) if changed else ""
            row = QtWidgets.QListWidgetItem(f"{n}.  {name}{detail}")
            if tool:
                icons.item_icon(row, icons.for_tool(tool.id, tool.category), 17)
            self.list.addItem(row)
        self.btn_run.setEnabled(bool(self.steps))
        self.status.setText(
            f"{len(self.steps)} step(s)." if self.steps
            else "Add a step to begin building your workflow.")

    def add_step(self):
        dlg = StepDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            step = dlg.result_step()
            if step["tool"]:
                self.steps.append(step)
                self.refresh()

    def edit_step(self):
        row = self.list.currentRow()
        if row < 0:
            return
        step = self.steps[row]
        dlg = StepDialog(self, step["tool"], step.get("params"))
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.steps[row] = dlg.result_step()
            self.refresh()
            self.list.setCurrentRow(row)

    def move(self, delta):
        row = self.list.currentRow()
        new = row + delta
        if row < 0 or not (0 <= new < len(self.steps)):
            return
        self.steps[row], self.steps[new] = self.steps[new], self.steps[row]
        self.refresh()
        self.list.setCurrentRow(new)

    def duplicate(self):
        row = self.list.currentRow()
        if row < 0:
            return
        import copy
        self.steps.insert(row + 1, copy.deepcopy(self.steps[row]))
        self.refresh()

    def remove(self):
        row = self.list.currentRow()
        if row < 0:
            return
        del self.steps[row]
        self.refresh()

    # ----------------------------------------------------------- workflows
    def _refresh_workflows(self):
        self.wf_box.clear()
        names = sorted(load_chains())
        self.wf_box.addItems(names or ["(none saved yet)"])
        self.wf_box.setEnabled(bool(names))

    def load_workflow(self):
        data = load_chains().get(self.wf_box.currentText())
        if not data:
            return
        self.steps = [dict(s) for s in data.get("steps", [])]
        self.refresh()
        self.status.setText(f"Loaded '{self.wf_box.currentText()}'.")

    def save_workflow(self):
        if not self.steps:
            self.status.setText("Add at least one step first.")
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "Save workflow", "Name this workflow:")
        if not ok or not name.strip():
            return
        from pdfbuilder.job import ToolError
        try:
            save_chain(name.strip(), self.steps)
        except ToolError as e:
            QtWidgets.QMessageBox.warning(self, "Workflow", str(e))
            return
        self._refresh_workflows()
        self.wf_box.setCurrentText(name.strip())
        self.status.setText(f"Saved '{name.strip()}'.")

    def delete_workflow(self):
        name = self.wf_box.currentText()
        if name not in load_chains():
            return
        if QtWidgets.QMessageBox.question(
                self, "Delete workflow", f"Delete '{name}'?") \
                == QtWidgets.QMessageBox.Yes:
            delete_chain(name)
            self._refresh_workflows()

    # --------------------------------------------------------------- run
    def run(self):
        if self.worker is not None:
            return
        inputs = self.files.paths()
        if not inputs:
            self.status.setText("Add the files the workflow should start from.")
            return
        if not self.steps:
            return
        self.log.clear()
        self.results.set_files([])
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_run.setEnabled(False)
        self.btn_cancel.setVisible(True)
        outdir = self.main.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        self.worker = ChainWorker(self.steps, inputs, outdir,
                                  keep=self.keep_box.isChecked())
        self.worker.progressed.connect(
            lambda f, m: (self.progress.setValue(int(f * 1000)),
                          self.status.setText(m or "")))
        self.worker.logged.connect(self.log.appendPlainText)
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel()
            self.status.setText("Stopping...")

    def _reset(self):
        self.worker = None
        self.btn_cancel.setVisible(False)
        self.progress.setVisible(False)
        self.btn_run.setEnabled(bool(self.steps))

    def _done(self, files, summary, secs):
        self._reset()
        self.results.set_files(files)
        self.status.setProperty("role", "good")
        self.status.setText(f"Workflow finished in {secs:.1f}s - "
                            f"{len(files)} file(s).")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.tabs.setCurrentIndex(0)

    def _failed(self, msg, detail):
        self._reset()
        self.status.setProperty("role", "bad")
        self.status.setText(msg.splitlines()[0])
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.log.appendPlainText("ERROR: " + msg)
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("The workflow stopped")
        box.setText(msg)
        if detail:
            box.setDetailedText(detail)
        box.exec()

    def _cancelled(self):
        self._reset()
        self.status.setText("Cancelled.")


def build(tool, main):
    return ChainPanel(tool, main)
