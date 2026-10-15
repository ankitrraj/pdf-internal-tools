"""Capture pages with a camera and build a scanned PDF."""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from pdfbuilder.ui.views.common import ToolBarRow
from pdfbuilder.ui import icons
from pdfbuilder.ui.widgets import icon_label, open_externally

Qt = QtCore.Qt


class Scanner(QtWidgets.QWidget):
    def __init__(self, tool, main, parent=None):
        super().__init__(parent)
        self.main = main
        self.shots: list[Path] = []
        self.capture = None
        self.session = None
        self.sink = None
        self.cam = None
        self._tmpdir = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)
        root.addWidget(icon_label(tool.name, "h1"))
        sub = icon_label("Hold a page flat in good light, press Capture for "
                         "each page, then build the PDF. Pages are "
                         "straightened and cleaned up automatically.", "dim")
        sub.setWordWrap(True)
        root.addWidget(sub)

        bar = ToolBarRow(wrap=True)
        self.cam_box = QtWidgets.QComboBox()
        self.cam_box.setMinimumWidth(220)
        bar.add(QtWidgets.QLabel("Camera"))
        bar.add(self.cam_box)
        bar.button("Refresh list", self.find_cameras, icon="refresh")
        self.btn_start = bar.button("Start camera", self.start, kind="primary", icon="camera")
        self.btn_stop = bar.button("Stop", self.stop, icon="stop")
        bar.sep()
        self.btn_shot = bar.button("Capture page", self.shoot, shortcut="Space",
                                   tip="Capture a page", icon="camera")
        bar.button("Import photos instead...", self.import_files, icon="picture")
        bar.stretch()
        root.addWidget(bar)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(10)
        self.preview_holder = QtWidgets.QStackedWidget()
        self.placeholder = QtWidgets.QLabel(
            "No camera running.\n\nPress 'Start camera', or use "
            "'Import photos instead...' if you already have pictures of the "
            "pages.")
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setProperty("role", "dim")
        self.placeholder.setMinimumHeight(360)
        self.preview_holder.addWidget(self.placeholder)
        body.addWidget(self.preview_holder, 1)

        side = QtWidgets.QFrame()
        side.setObjectName("Card")
        side.setFixedWidth(280)
        sv = QtWidgets.QVBoxLayout(side)
        sv.setContentsMargins(10, 10, 10, 10)
        sv.setSpacing(8)
        sv.addWidget(icon_label("Captured pages", "h2"))
        self.shot_list = QtWidgets.QListWidget()
        self.shot_list.setIconSize(QtCore.QSize(86, 110))
        sv.addWidget(self.shot_list, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Remove")
        b.setProperty("kind", "danger")
        b.clicked.connect(self.remove_shot)
        row.addWidget(b)
        b2 = QtWidgets.QPushButton("Clear all")
        b2.setProperty("kind", "danger")
        b2.clicked.connect(self.clear_shots)
        row.addWidget(b2)
        sv.addLayout(row)

        sv.addWidget(icon_label("Clean-up", "h2"))
        self.opt_deskew = QtWidgets.QCheckBox("Straighten pages")
        self.opt_deskew.setChecked(True)
        self.opt_rotate = QtWidgets.QCheckBox("Correct orientation")
        self.opt_rotate.setChecked(True)
        self.opt_enhance = QtWidgets.QCheckBox("Boost contrast")
        self.opt_enhance.setChecked(True)
        self.opt_gray = QtWidgets.QCheckBox("Greyscale")
        self.opt_gray.setChecked(True)
        self.opt_blank = QtWidgets.QCheckBox("Skip blank pages")
        self.opt_blank.setChecked(True)
        self.opt_ocr = QtWidgets.QCheckBox("Searchable text (OCR)")
        self.opt_ocr.setToolTip("Recognise the words so the PDF can be "
                                "searched and the text copied.")
        for w in (self.opt_deskew, self.opt_rotate, self.opt_enhance,
                  self.opt_gray, self.opt_blank, self.opt_ocr):
            sv.addWidget(w)
        from pdfbuilder.core.ocr import any_engine, engine_choices
        if not any_engine():
            self.opt_ocr.setEnabled(False)
            self.opt_ocr.setToolTip("No text recogniser is installed")
            sv.addWidget(icon_label("OCR needs either:  sudo apt install "
                                    "tesseract-ocr\nor:  .venv/bin/pip "
                                    "install rapidocr-onnxruntime", "faint"))
        elif len(engine_choices()) > 2:
            self.opt_ocr.setToolTip("Tesseract is installed and will be used")
        self.btn_build = QtWidgets.QPushButton("Build the PDF")
        icons.apply(self.btn_build, "to_pdf", 16)
        self.btn_build.setProperty("kind", "primary")
        self.btn_build.clicked.connect(self.build_pdf)
        sv.addWidget(self.btn_build)
        self.status = icon_label("", "faint")
        self.status.setWordWrap(True)
        sv.addWidget(self.status)
        body.addWidget(side)
        root.addLayout(body, 1)

        self.find_cameras()
        self._update()

    # ------------------------------------------------------------- cameras
    def find_cameras(self):
        self.cam_box.clear()
        try:
            from PySide6.QtMultimedia import QMediaDevices
        except ImportError:
            self.cam_box.addItem("camera support not installed")
            self.cam_box.setEnabled(False)
            self.btn_start.setEnabled(False)
            self.status.setText(
                "Camera capture needs the full PySide6 multimedia module.\n"
                "Install it with:  pip install PySide6-Addons\n\n"
                "You can still use 'Import photos instead...'.")
            return
        self.devices = QMediaDevices.videoInputs()
        if not self.devices:
            self.cam_box.addItem("no camera found")
            self.btn_start.setEnabled(False)
            self.status.setText("No camera was detected. Plug one in and "
                                "press 'Refresh list', or import photos.")
            return
        for d in self.devices:
            self.cam_box.addItem(d.description())
        self.cam_box.setEnabled(True)
        self.btn_start.setEnabled(True)

    def start(self):
        try:
            from PySide6.QtMultimedia import (QCamera, QImageCapture,
                                              QMediaCaptureSession)
            from PySide6.QtMultimediaWidgets import QVideoWidget
        except ImportError:
            self.status.setText("Install PySide6-Addons for camera support.")
            return
        if not getattr(self, "devices", None):
            return
        idx = max(0, self.cam_box.currentIndex())
        self.stop()
        self.cam = QCamera(self.devices[idx])
        self.session = QMediaCaptureSession()
        self.session.setCamera(self.cam)
        self.video = QVideoWidget()
        self.session.setVideoOutput(self.video)
        self.capture = QImageCapture(self.cam)
        self.session.setImageCapture(self.capture)
        self.capture.imageCaptured.connect(self._captured)
        self.capture.errorOccurred.connect(
            lambda *a: self.status.setText(f"Camera error: {a[-1]}"))
        while self.preview_holder.count() > 1:
            w = self.preview_holder.widget(1)
            self.preview_holder.removeWidget(w)
            w.deleteLater()
        self.preview_holder.addWidget(self.video)
        self.preview_holder.setCurrentWidget(self.video)
        self.cam.start()
        self.status.setText("Camera running - press Capture (or the space "
                            "bar) for each page.")
        self._update()

    def stop(self):
        if self.cam is not None:
            self.cam.stop()
            self.cam = None
        self.capture = None
        self.session = None
        self.preview_holder.setCurrentWidget(self.placeholder)
        self._update()

    def shoot(self):
        if self.capture is None:
            self.status.setText("Start the camera first.")
            return
        import tempfile
        if self._tmpdir is None:
            self._tmpdir = Path(tempfile.mkdtemp(prefix="pdfbuilder-scan-"))
        target = self._tmpdir / f"page{len(self.shots)+1:03d}.jpg"
        self.capture.captureToFile(str(target))
        QtCore.QTimer.singleShot(700, lambda: self._collect(target))

    def _captured(self, _id, image):
        pass                      # file-based capture is handled in _collect

    def _collect(self, target: Path):
        if target.exists():
            self._add_shot(target)
        else:
            cands = sorted(target.parent.glob(target.stem + "*"))
            if cands:
                self._add_shot(cands[-1])
            else:
                self.status.setText("The capture did not produce a file - "
                                    "try again.")

    def _add_shot(self, path: Path):
        self.shots.append(path)
        item = QtWidgets.QListWidgetItem(f"Page {len(self.shots)}")
        pm = QtGui.QPixmap(str(path))
        if not pm.isNull():
            item.setIcon(QtGui.QIcon(pm.scaled(
                86, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        self.shot_list.addItem(item)
        self.status.setText(f"{len(self.shots)} page(s) captured.")
        self._update()

    def import_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Choose photos of the pages", str(Path.home()),
            "Images (*.jpg *.jpeg *.png *.heic *.webp *.tif *.bmp)")
        for f in files:
            self._add_shot(Path(f))

    def add_files(self, paths):
        from pdfbuilder.core.common import is_image
        for p in paths:
            if is_image(p):
                self._add_shot(Path(p))

    def remove_shot(self):
        row = self.shot_list.currentRow()
        if row < 0:
            return
        self.shot_list.takeItem(row)
        del self.shots[row]
        for i in range(self.shot_list.count()):
            self.shot_list.item(i).setText(f"Page {i+1}")
        self._update()

    def clear_shots(self):
        self.shots.clear()
        self.shot_list.clear()
        self._update()

    def _update(self):
        self.btn_shot.setEnabled(self.capture is not None)
        self.btn_stop.setEnabled(self.cam is not None)
        self.btn_build.setEnabled(bool(self.shots))

    # --------------------------------------------------------------- build
    def build_pdf(self):
        if not self.shots:
            return
        from pdfbuilder.job import Ctx, ToolError
        from pdfbuilder.registry import REGISTRY
        tool = REGISTRY["images_to_scan_pdf"]
        params = {**tool.defaults(),
                  "deskew": self.opt_deskew.isChecked(),
                  "autorotate": self.opt_rotate.isChecked(),
                  "enhance": self.opt_enhance.isChecked(),
                  "gray": self.opt_gray.isChecked(),
                  "drop_blank": self.opt_blank.isChecked(),
                  "ocr": self.opt_ocr.isChecked(),
                  "outname": "scan.pdf"}
        outdir = self.main.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        prog = QtWidgets.QProgressDialog("Building the document...", "Cancel",
                                         0, 100, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        cancelled = {"v": False}
        prog.canceled.connect(lambda: cancelled.update(v=True))
        logs = []
        ctx = Ctx([str(p) for p in self.shots], params, outdir,
                  progress=lambda f, m="": (prog.setValue(int(f * 100)),
                                            prog.setLabelText(m or ""),
                                            QtWidgets.QApplication
                                            .processEvents()),
                  cancelled=lambda: cancelled["v"],
                  log=logs.append)
        try:
            made = tool.fn(ctx) or ctx.produced
        except ToolError as e:
            prog.close()
            QtWidgets.QMessageBox.warning(self, "Scan", str(e))
            return
        except Exception as e:
            prog.close()
            QtWidgets.QMessageBox.warning(self, "Scan",
                                          f"{type(e).__name__}: {e}")
            return
        finally:
            ctx.cleanup()
        prog.close()
        self.status.setText("\n".join(logs[-4:]))
        if made and QtWidgets.QMessageBox.question(
                self, "Scan complete",
                f"Written to:\n{made[0]}\n\nOpen it now?") \
                == QtWidgets.QMessageBox.Yes:
            open_externally(made[0])

    def hideEvent(self, ev):
        self.stop()
        super().hideEvent(ev)


def build(tool, main):
    return Scanner(tool, main)
