"""Job execution context: output naming, progress, cancellation."""
from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path


class Cancelled(Exception):
    pass


class ToolError(Exception):
    """Expected, user-facing failure (bad input, missing dependency...)."""


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w.\- ]+", "_", stem).strip() or "output"
    return stem[:80]


class Ctx:
    """Handed to every tool function."""

    def __init__(self, inputs, params, outdir: Path, *, progress=None,
                 cancelled=None, log=None, overwrite=False):
        self.inputs = [Path(p) for p in inputs]
        self.p = dict(params)
        self.outdir = Path(outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self._progress = progress or (lambda f, m="": None)
        self._cancelled = cancelled or (lambda: False)
        self._log = log or (lambda m: None)
        self.overwrite = overwrite
        self.produced: list[Path] = []
        self._tmp: Path | None = None

    # -------------------------------------------------------------- plumbing
    @property
    def src(self) -> Path:
        if not self.inputs:
            raise ToolError("No input file selected.")
        return self.inputs[0]

    def progress(self, frac: float, msg: str = "") -> None:
        self.check()
        self._progress(max(0.0, min(1.0, frac)), msg)

    def log(self, msg: str) -> None:
        self._log(msg)

    def check(self) -> None:
        if self._cancelled():
            raise Cancelled()

    @property
    def tmp(self) -> Path:
        if self._tmp is None:
            self._tmp = Path(tempfile.mkdtemp(prefix="pdfbuilder-"))
        return self._tmp

    def cleanup(self) -> None:
        if self._tmp and self._tmp.exists():
            shutil.rmtree(self._tmp, ignore_errors=True)
        self._tmp = None

    # ---------------------------------------------------------------- output
    def out(self, name: str, *, suffix: str | None = None) -> Path:
        """Reserve a unique output path inside the output directory."""
        p = self.outdir / name
        if suffix:
            p = p.with_suffix(suffix)
        if not self.overwrite:
            base, ext, n = p.stem, p.suffix, 2
            while p.exists():
                p = self.outdir / f"{base} ({n}){ext}"
                n += 1
        return p

    def derive(self, tag: str, ext: str = ".pdf", src: Path | None = None) -> Path:
        src = src or self.src
        return self.out(f"{safe_stem(src.name)}-{tag}{ext}")

    def done(self, *paths: Path) -> list[Path]:
        for p in paths:
            if p and Path(p).exists():
                self.produced.append(Path(p))
        return self.produced

    def zip_up(self, files, name: str) -> Path:
        target = self.out(name, suffix=".zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, Path(f).name)
        return target
