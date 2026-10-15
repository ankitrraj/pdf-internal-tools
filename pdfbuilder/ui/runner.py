"""Background execution of tools, batches and chains."""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from PySide6 import QtCore

from pdfbuilder.job import Cancelled, Ctx, ToolError
from pdfbuilder.registry import Tool


class Worker(QtCore.QThread):
    progressed = QtCore.Signal(float, str)
    logged = QtCore.Signal(str)
    finished_ok = QtCore.Signal(list, dict, float)
    failed = QtCore.Signal(str, str)
    cancelled = QtCore.Signal()

    def __init__(self, tool: Tool, inputs, params, outdir, *, batch=False,
                 parent=None):
        super().__init__(parent)
        self.tool = tool
        self.inputs = [Path(p) for p in inputs]
        self.params = dict(params)
        self.outdir = Path(outdir)
        self.batch = batch
        self._stop = False

    def cancel(self):
        self._stop = True

    # ------------------------------------------------------------------ run
    def run(self):
        started = time.monotonic()
        produced: list[Path] = []
        summary: dict = {}
        try:
            if self.batch and not self.tool.multi and len(self.inputs) > 1:
                total = len(self.inputs)
                for n, one in enumerate(self.inputs, 1):
                    if self._stop:
                        raise Cancelled()
                    self.logged.emit(f"--- {n}/{total}: {one.name}")

                    def prog(f, m="", n=n, total=total):
                        self.progressed.emit((n - 1 + f) / total,
                                             m or one.name)
                    ctx = self._ctx([one], prog)
                    try:
                        result = self.tool.fn(ctx) or ctx.produced
                        produced += [Path(p) for p in result]
                        summary.update(getattr(ctx, "summary", {}) or {})
                    except ToolError as e:
                        self.logged.emit(f"  skipped {one.name}: {e}")
                    finally:
                        ctx.cleanup()
            else:
                ctx = self._ctx(self.inputs,
                                lambda f, m="": self.progressed.emit(f, m))
                try:
                    result = self.tool.fn(ctx) or ctx.produced
                    produced = [Path(p) for p in result]
                    summary = getattr(ctx, "summary", {}) or {}
                finally:
                    ctx.cleanup()
        except Cancelled:
            self.cancelled.emit()
            return
        except ToolError as e:
            self.failed.emit(str(e), "")
            return
        except MemoryError:
            self.failed.emit(
                "Ran out of memory on this file.\n\nTry a lower resolution, "
                "or split the document into smaller parts first.", "")
            return
        except Exception as e:                       # unexpected: show detail
            self.failed.emit(f"{type(e).__name__}: {e}",
                             traceback.format_exc())
            return
        self.progressed.emit(1.0, "Done")
        self.finished_ok.emit([str(p) for p in produced], summary,
                              time.monotonic() - started)

    def _ctx(self, inputs, prog) -> Ctx:
        return Ctx(inputs, self.params, self.outdir, progress=prog,
                   cancelled=lambda: self._stop,
                   log=lambda m: self.logged.emit(str(m)))


class ChainWorker(QtCore.QThread):
    progressed = QtCore.Signal(float, str)
    logged = QtCore.Signal(str)
    finished_ok = QtCore.Signal(list, dict, float)
    failed = QtCore.Signal(str, str)
    cancelled = QtCore.Signal()

    def __init__(self, steps, inputs, outdir, *, keep=False, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.inputs = inputs
        self.outdir = outdir
        self.keep = keep
        self._stop = False

    def cancel(self):
        self._stop = True

    def run(self):
        from pdfbuilder.core.batch import run_chain
        started = time.monotonic()
        try:
            made = run_chain(
                self.steps, self.inputs, self.outdir,
                progress=lambda f, m="": self.progressed.emit(f, m),
                cancelled=lambda: self._stop,
                log=lambda m: self.logged.emit(str(m)),
                keep_intermediates=self.keep)
        except Cancelled:
            self.cancelled.emit()
            return
        except ToolError as e:
            self.failed.emit(str(e), "")
            return
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}",
                             traceback.format_exc())
            return
        self.finished_ok.emit([str(p) for p in made], {},
                              time.monotonic() - started)
