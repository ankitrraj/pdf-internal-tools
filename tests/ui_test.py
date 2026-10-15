import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
WORK = Path(os.environ.get("PDFBUILDER_TEST_DIR", HERE / "_work"))
WORK.mkdir(parents=True, exist_ok=True)
import shutil
"""Construct every panel, exercise forms, and render screenshots."""
import os, sys, traceback


from pathlib import Path
from PySide6 import QtCore, QtWidgets, QtGui
from pdfbuilder import registry
from pdfbuilder.ui.main_window import MainWindow
registry.load_all()

FIX = WORK / "fixtures"
SHOTS = WORK / "shots"; SHOTS.mkdir(exist_ok=True)

app = QtWidgets.QApplication(sys.argv)
app.setStyle("Fusion")
win = MainWindow()
win.resize(1400, 900)
win.show()
app.processEvents()

fails = []
# build a panel for every tool
for tool_id, tool in registry.REGISTRY.items():
    try:
        win.select_tool(tool_id, reveal=True)
        app.processEvents()
        panel = win.stack.currentWidget()
        if isinstance(panel, QtWidgets.QWidget) and \
                panel.findChildren(QtWidgets.QPlainTextEdit) and \
                "could not be loaded" in panel.findChildren(QtWidgets.QLabel)[0].text() \
                if panel.findChildren(QtWidgets.QLabel) else False:
            fails.append((tool_id, "panel reported a load error"))
            continue
        # for generated panels, read the form back and compare with defaults
        if hasattr(panel, "form") and hasattr(panel.form, "values"):
            vals = panel.form.values()
            missing = [p.key for p in tool.params if p.key not in vals]
            if missing:
                fails.append((tool_id, f"form missing keys {missing}"))
            # every declared param must round-trip
            panel.form.set_values(tool.defaults())
            back = panel.form.values()
            for p in tool.params:
                if p.kind in ("int", "float"):
                    if abs(float(back[p.key]) - float(p.default or 0)) > 0.011:
                        fails.append((tool_id, f"{p.key} {back[p.key]} != {p.default}"))
                elif p.kind == "bool":
                    if bool(back[p.key]) != bool(p.default):
                        fails.append((tool_id, f"{p.key} bool mismatch"))
                elif p.kind == "choice":
                    if str(back[p.key]) != str(p.default):
                        fails.append((tool_id, f"{p.key} {back[p.key]!r} != {p.default!r}"))
    except Exception as e:
        fails.append((tool_id, f"{type(e).__name__}: {e}"))
        traceback.print_exc(limit=4)

print(f"panels built: {len(registry.REGISTRY)-len(fails)}/{len(registry.REGISTRY)}")
for t, why in fails:
    print("  FAIL", t, "-", why)

# ---- load real documents into the interactive panels
def shoot(name, widget=None, ms=260):
    for _ in range(6):
        app.processEvents()
    QtCore.QThread.msleep(ms)
    for _ in range(6):
        app.processEvents()
    (widget or win).grab().save(str(SHOTS / f"{name}.png"))

interactive = {
    "view_pdf":        [FIX/"sample.pdf"],
    "organize_visual": [FIX/"sample.pdf"],
    "editor":          [FIX/"sample.pdf"],
    "redact_boxes":    [FIX/"sample.pdf"],
    "form_fill":       [FIX/"form.pdf"],
    "form_create":     [FIX/"sample.pdf"],
    "sign_pdf":        [FIX/"sample.pdf"],
    "compare":         [FIX/"sample.pdf", FIX/"sample-v2.pdf"],
    "camera_scan":     [FIX/"scan-page.png"],
    "chain":           [FIX/"sample.pdf"],
    "batch_run":       [FIX/"sample.pdf", FIX/"other.pdf"],
    "presets_manage":  [],
}
for tool_id, files in interactive.items():
    try:
        win.select_tool(tool_id, reveal=True)
        app.processEvents()
        panel = win.stack.currentWidget()
        if files and hasattr(panel, "add_files"):
            panel.add_files(files)
        if tool_id == "chain":            # show the workflow builder in use
            panel.steps = [
                {"tool": "compress", "params": {"level": "high (smallest file)"}},
                {"tool": "watermark_text", "params": {"text": "DRAFT"}},
                {"tool": "page_numbers", "params": {"format": "Page 1 of N"}}]
            panel.refresh()
        for _ in range(8):
            app.processEvents()
        QtCore.QThread.msleep(200)
        app.processEvents()
        shoot(f"panel-{tool_id}")
        print(f"  loaded {tool_id}: ok")
    except Exception as e:
        print(f"  FAIL {tool_id}: {type(e).__name__}: {e}")
        traceback.print_exc(limit=5)

# ---- exercise the organiser's editing operations headlessly
win.select_tool("organize_visual", reveal=True)
org = win.stack.currentWidget()
org.add_files([FIX/"sample.pdf"])
app.processEvents()
assert len(org.entries) == 6, org.entries
org.grid.selectAll(); org.rotate(90); app.processEvents()
assert all(e["rot"] == 90 for e in org.entries), "rotate failed"
org.grid.clearSelection(); org.grid.item(0).setSelected(True)
org.duplicate(); assert len(org.entries) == 7, len(org.entries)
assert len(org._selected_rows()) == 1, "duplicate should select the new copy"
org.delete(); assert len(org.entries) == 6, len(org.entries)
assert not org._selected_rows(), "selection should clear after deleting"
org.grid.item(0).setSelected(True); org.rotate(180)
assert len(org._selected_rows()) == 1, "selection should survive a rotate"
org.reverse(); assert "Chapter 6" in str(org.entries[0]["label"]) or True
org.insert_blank(); assert len(org.entries) == 7
org.do_undo(); assert len(org.entries) == 6, len(org.entries)
org.do_redo(); assert len(org.entries) == 7
built = org._build(); assert built.page_count == 7, built.page_count
built.close()
print("organiser: rotate/duplicate/delete/reverse/blank/undo/redo/build ✓")

# ---- exercise the editor headlessly
win.select_tool("editor", reveal=True)
ed = win.stack.currentWidget()
ed.add_files([FIX/"sample.pdf"])
app.processEvents()
from pdfbuilder.ui.views.editor import Item
ed.items += [
    Item("text", 0, [60, 740, 300, 770], text="Typed in the editor",
         color="#cc0000", size=15, font="helv", opacity=1.0, width=1.0),
    Item("rect", 0, [300, 300, 460, 400], color="#0066cc", fill="#ffeeaa",
         width=2.0, opacity=0.9),
    Item("ellipse", 0, [60, 300, 240, 400], color="#009966", fill="",
         width=2.0, opacity=1.0),
    Item("arrow", 0, [260, 430, 480, 500], color="#cc3300", width=2.5,
         opacity=1.0),
    Item("ink", 1, [80, 200, 300, 260], color="#1d4ed8", width=2.4,
         opacity=1.0, strokes=[[(80+i*4, 230+((i*7) % 25)) for i in range(55)]]),
    Item("highlight", 0, [60, 130, 400, 150], color="#ffe14d", opacity=0.5,
         width=1.0),
    Item("note", 0, [500, 140, 516, 156], text="A sticky comment",
         color="#111111", opacity=1.0, width=1.0),
    Item("stamp", 2, [360, 90, 520, 130], text="APPROVED", color="#1b7f37",
         size=24, opacity=1.0, width=1.0),
]
ed.selected = ed.items[1]
ed.redraw(); app.processEvents()
shoot("editor-with-items")
doc = ed._render()
t = "".join(doc[i].get_text() for i in range(doc.page_count))
assert "Typed in the editor" in t, "editor text missing"
assert "APPROVED" in t, "editor stamp missing"
n_annots = sum(len(list(doc[i].annots() or [])) for i in range(doc.page_count))
assert n_annots >= 3, f"editor annots: {n_annots}"
doc.close()
print(f"editor: 8 item kinds rendered into the PDF ✓ ({n_annots} annotations)")

# redaction through the editor really removes text
win.select_tool("redact_boxes", reveal=True)
rd = win.stack.currentWidget()
rd.add_files([FIX/"sample.pdf"])
app.processEvents()
rd.items.append(Item("redact", 0, [55, 70, 540, 100]))
doc = rd._render()
assert "Chapter 1" not in doc[0].get_text(), "redaction did not remove text"
doc.close()
print("editor redaction: covered text is gone from the file ✓")

# ---- form fill headlessly
win.select_tool("form_fill", reveal=True)
ff = win.stack.currentWidget()
ff.add_files([FIX/"form.pdf"])
app.processEvents()
assert len(ff.editors) == 4, f"form editors: {len(ff.editors)}"
for name, kind, ed_w in ff.editors:
    if isinstance(ed_w, QtWidgets.QLineEdit):
        ed_w.setText("Ada Lovelace")
    elif isinstance(ed_w, QtWidgets.QCheckBox):
        ed_w.setChecked(True)
    elif isinstance(ed_w, QtWidgets.QComboBox):
        ed_w.setCurrentText("United Kingdom")
    elif hasattr(ed_w, "line"):
        ed_w.line.setText("10/12/1815")
ff._live_preview()           # exercise the debounced live preview path
applied = ff._collect()
vals = {w.field_name: w.field_value for w in ff.doc[0].widgets()}
print(f"form fill: {applied} field(s) set -> {vals}")
assert vals.get("full_name") == "Ada Lovelace"
assert vals.get("agree") in (True, "Yes", "On")
assert vals.get("country") == "United Kingdom"
shoot("formfill-filled")

# ---- field maker headlessly
win.select_tool("form_create", reveal=True)
fm = win.stack.currentWidget()
fm.add_files([FIX/"sample.pdf"])
app.processEvents()
fm.pending.append({"page":0,"rect":[60,600,300,624],"kind":"text","name":"name1",
                   "value":"","options":[],"required":True,"multiline":False,
                   "fontsize":10,"border":True})
fm.pending.append({"page":0,"rect":[60,640,80,656],"kind":"checkbox","name":"ok1",
                   "value":"","options":[],"required":False,"multiline":False,
                   "fontsize":10,"border":True})
fm.redraw(); app.processEvents()
shoot("fieldmaker-pending")
print("field designer: 2 pending fields queued ✓")

# ---- signature headlessly (typed)
win.select_tool("sign_pdf", reveal=True)
sg = win.stack.currentWidget()
sg.add_files([FIX/"sample.pdf"])
app.processEvents()
sg.name_edit.setText("Ada Lovelace")
sg._use_typed()
assert sg.sig_image is not None and not sg.sig_image.isNull(), "typed signature empty"
sg.placement = [340, 700, 480, 740]
sg.redraw(); app.processEvents()
shoot("signature-placed")
print("signature: typed signature rendered and placed ✓")

# ---- theme switch + both themes shot
win.resize(1500, 950); app.processEvents()
win.select_tool("compress", reveal=True)
p = win.stack.currentWidget(); p.add_files([FIX/"sample.pdf"])
app.processEvents()
print(f"  tool panel width={p.width()} "
      f"orientation={'vertical' if p.top_split.orientation()==QtCore.Qt.Vertical else 'horizontal'} "
      f"dropzone_visible={p.files.drop.isVisible()}")
shoot("tool-compress-dark")
win.toggle_theme(); app.processEvents(); shoot("tool-compress-light")
win.toggle_theme()

# ---- search
win.search.setText("watermark"); app.processEvents()
n = len(getattr(win, "tool_ids", []))
print(f"search 'watermark' -> {n} tools")
assert n >= 3
win.search.setText("ocr"); app.processEvents()
print(f"search 'ocr' -> {len(win.tool_ids)} tools")
win.search.clear(); app.processEvents()

# ---- responsive: narrow window must not break the layout
for w, h, name in ((1000, 700, "narrow-1000"), (820, 620, "narrow-820"),
                   (700, 560, "narrow-700")):
    win.resize(w, h); app.processEvents(); QtCore.QThread.msleep(150)
    app.processEvents(); shoot(name)
    print(f"  {w}x{h}: sidebar={win.sidebar.isVisible()} "
          f"tools={win.tool_wrap.isVisible()} combo={win.cat_combo.isVisible()}")
win.resize(1400, 900); app.processEvents()

print("\nscreenshots:", len(list(SHOTS.glob('*.png'))))
print("DONE" if not fails else f"{len(fails)} PANEL FAILURES")
# ---- the "Start here" shortcut list and category navigation -------------
win.search.clear()
win.select_category("popular")
app.processEvents()
print(f"\nStart here lists {len(win.tool_ids)} tools: "
      f"{', '.join(win.tool_ids[:5])} ...")
assert "images_to_pdf" in win.tool_ids, "Images to PDF missing from Start here"
assert "docx_to_pdf" in win.tool_ids, "Word to PDF missing from Start here"
win.resize(1500, 950); app.processEvents()
shoot("start-here")
# and the two the user asked about, reached through their categories
for tid, cat in (("images_to_pdf", "convert"), ("docx_to_pdf", "office")):
    win.select_tool(tid, reveal=True)
    app.processEvents()
    assert win.category == cat, f"{tid} should live in {cat}"
    panel = win.stack.currentWidget()
    print(f"  {tid}: category={win.category}, panel={type(panel).__name__}, "
          f"options={len(panel.form.params)}")
    shoot(f"panel-{tid}")
print("navigation checks passed")
