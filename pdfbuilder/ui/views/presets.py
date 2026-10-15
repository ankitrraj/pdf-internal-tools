"""Manage saved presets and workflows."""
from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from pdfbuilder import registry
from pdfbuilder.core.batch import (CHAIN_FILE, PRESET_FILE, delete_chain,
                                   delete_preset, load_chains, load_presets,
                                   save_chain, save_preset)
from pdfbuilder.ui.views.common import ToolBarRow
from pdfbuilder.ui import icons
from pdfbuilder.ui.widgets import icon_label, reveal_in_files

Qt = QtCore.Qt


class PresetsPanel(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(9)
        root.addWidget(icon_label(tool.name, "h1"))
        sub = icon_label("Presets remember one tool's settings. Workflows "
                         "remember a sequence of steps. Both are stored in "
                         "your home folder.", "dim")
        sub.setWordWrap(True)
        root.addWidget(sub)

        self.tabs = QtWidgets.QTabWidget()
        root.addWidget(self.tabs, 1)

        # presets ----------------------------------------------------------
        pw = QtWidgets.QWidget()
        pv = QtWidgets.QVBoxLayout(pw)
        self.preset_tree = QtWidgets.QTreeWidget()
        self.preset_tree.setHeaderLabels(["Preset", "Tool", "Saved",
                                          "Settings"])
        self.preset_tree.setAlternatingRowColors(True)
        pv.addWidget(self.preset_tree, 1)
        row = ToolBarRow(wrap=True)
        row.button("Rename", self.rename_preset, icon="pen")
        row.button("Delete", self.delete_preset, kind="danger", icon="trash")
        row.button("Open the tool", self.open_tool, icon="open")
        row.stretch()
        row.button("Show the file", lambda: reveal_in_files(PRESET_FILE), icon="folder")
        pv.addWidget(row)
        self.tabs.addTab(pw, icons.ic("star", 16), "Presets")

        # workflows --------------------------------------------------------
        ww = QtWidgets.QWidget()
        wv = QtWidgets.QVBoxLayout(ww)
        self.chain_tree = QtWidgets.QTreeWidget()
        self.chain_tree.setHeaderLabels(["Workflow", "Steps", "Saved"])
        self.chain_tree.setAlternatingRowColors(True)
        wv.addWidget(self.chain_tree, 1)
        row2 = ToolBarRow(wrap=True)
        row2.button("Rename", self.rename_chain, icon="pen")
        row2.button("Delete", self.delete_chain, kind="danger", icon="trash")
        row2.button("Open in the workflow builder", self.open_chain, icon="workflow")
        row2.stretch()
        row2.button("Show the file", lambda: reveal_in_files(CHAIN_FILE), icon="folder")
        wv.addWidget(row2)
        self.tabs.addTab(ww, icons.ic("workflow", 16), "Workflows")

        self.status = icon_label("", "faint")
        root.addWidget(self.status)
        self.refresh()

    def refresh(self):
        self.preset_tree.clear()
        for name, data in sorted(load_presets().items()):
            tool = registry.REGISTRY.get(data.get("tool", ""))
            params = data.get("params", {})
            shown = ", ".join(f"{k}={v}" for k, v in list(params.items())[:6]
                              if v not in ("", None, False))
            item = QtWidgets.QTreeWidgetItem(
                [name, tool.name if tool else data.get("tool", "?"),
                 data.get("saved", ""), shown])
            item.setData(0, Qt.UserRole, data.get("tool", ""))
            if tool:
                item.setIcon(0, icons.ic(icons.for_tool(tool.id,
                                                        tool.category), 16))
            self.preset_tree.addTopLevelItem(item)
        for i in range(4):
            self.preset_tree.resizeColumnToContents(i)

        self.chain_tree.clear()
        for name, data in sorted(load_chains().items()):
            steps = data.get("steps", [])
            labels = " → ".join(
                registry.REGISTRY[s["tool"]].name
                if s.get("tool") in registry.REGISTRY else str(s.get("tool"))
                for s in steps)
            item = QtWidgets.QTreeWidgetItem([name, labels,
                                              data.get("saved", "")])
            item.setIcon(0, icons.ic("workflow", 16))
            self.chain_tree.addTopLevelItem(item)
        for i in range(3):
            self.chain_tree.resizeColumnToContents(i)
        n_p = self.preset_tree.topLevelItemCount()
        n_c = self.chain_tree.topLevelItemCount()
        self.status.setText(f"{n_p} preset(s), {n_c} workflow(s).")

    # ------------------------------------------------------------- presets
    def _sel_preset(self):
        items = self.preset_tree.selectedItems()
        return items[0] if items else None

    def rename_preset(self):
        item = self._sel_preset()
        if not item:
            return
        old = item.text(0)
        new, ok = QtWidgets.QInputDialog.getText(self, "Rename preset",
                                                 "New name:", text=old)
        if not ok or not new.strip() or new == old:
            return
        data = load_presets()[old]
        save_preset(new.strip(), data["tool"], data["params"])
        delete_preset(old)
        self.refresh()

    def delete_preset(self):
        item = self._sel_preset()
        if not item:
            return
        if QtWidgets.QMessageBox.question(
                self, "Delete preset", f"Delete '{item.text(0)}'?") \
                == QtWidgets.QMessageBox.Yes:
            delete_preset(item.text(0))
            self.refresh()

    def open_tool(self):
        item = self._sel_preset()
        if not item:
            return
        tool_id = item.data(0, Qt.UserRole)
        if tool_id in registry.REGISTRY:
            self.main.select_tool(tool_id, reveal=True)
            panel = self.main.panels.get(tool_id)
            if panel is not None and hasattr(panel, "preset_box"):
                panel.preset_box.setCurrentText(item.text(0))

    # ----------------------------------------------------------- workflows
    def _sel_chain(self):
        items = self.chain_tree.selectedItems()
        return items[0] if items else None

    def rename_chain(self):
        item = self._sel_chain()
        if not item:
            return
        old = item.text(0)
        new, ok = QtWidgets.QInputDialog.getText(self, "Rename workflow",
                                                 "New name:", text=old)
        if not ok or not new.strip() or new == old:
            return
        save_chain(new.strip(), load_chains()[old]["steps"])
        delete_chain(old)
        self.refresh()

    def delete_chain(self):
        item = self._sel_chain()
        if not item:
            return
        if QtWidgets.QMessageBox.question(
                self, "Delete workflow", f"Delete '{item.text(0)}'?") \
                == QtWidgets.QMessageBox.Yes:
            delete_chain(item.text(0))
            self.refresh()

    def open_chain(self):
        item = self._sel_chain()
        if not item:
            return
        self.main.select_tool("chain", reveal=True)
        panel = self.main.panels.get("chain")
        if panel is not None:
            panel.wf_box.setCurrentText(item.text(0))
            panel.load_workflow()

    def showEvent(self, ev):
        self.refresh()
        super().showEvent(ev)


def build(tool, main):
    return PresetsPanel(tool, main)
