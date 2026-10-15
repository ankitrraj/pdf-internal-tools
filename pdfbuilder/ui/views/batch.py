"""Batch panel: choose any tool and run it over many files at once."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfbuilder import registry
from pdfbuilder.registry import CATEGORY_NAMES
from pdfbuilder.ui.toolpanel import ToolPanel
from pdfbuilder.ui.views.common import ToolBarRow
from pdfbuilder.ui import icons
from pdfbuilder.ui.widgets import icon_label

Qt = QtCore.Qt


class BatchPanel(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.inner: ToolPanel | None = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(8)
        root.addWidget(icon_label(tool.name, "h1"))
        sub = icon_label("Pick a tool, add as many files as you like, and the "
                         "same settings are applied to every one of them.",
                         "dim")
        sub.setWordWrap(True)
        root.addWidget(sub)

        row = ToolBarRow()
        row.add(QtWidgets.QLabel("Tool"))
        self.combo = QtWidgets.QComboBox()
        self.combo.setMinimumWidth(380)
        for t in registry.REGISTRY.values():
            if t.view or not t.batchable:
                continue
            self.combo.addItem(
                icons.ic(icons.for_tool(t.id, t.category), 16),
                f"{CATEGORY_NAMES.get(t.category, '')}  ·  {t.name}", t.id)
        row.add(self.combo)
        row.stretch()
        root.addWidget(row)

        self.host = QtWidgets.QVBoxLayout()
        root.addLayout(self.host, 1)
        self.combo.currentIndexChanged.connect(self._swap)
        default = self.combo.findData("compress")
        if default >= 0:
            self.combo.setCurrentIndex(default)
        self._swap()

    def _swap(self, *_):
        tool_id = self.combo.currentData()
        if not tool_id:
            return
        if self.inner is not None:
            self.inner.setParent(None)
            self.inner.deleteLater()
        tool = registry.REGISTRY[tool_id]
        self.inner = ToolPanel(tool, self.main.outdir, self)
        self.inner.title.setVisible(False)
        self.inner.batch_box.setChecked(True)
        self.host.addWidget(self.inner)

    def add_files(self, paths):
        if self.inner:
            self.inner.add_files(paths)

    def set_outdir(self, path):
        if self.inner:
            self.inner.set_outdir(path)


def build(tool, main):
    return BatchPanel(tool, main)
