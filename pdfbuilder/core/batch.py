"""Category 12 - batch processing, chained workflows and presets.

Running one tool over many files is handled by the runner (every tool whose
`batchable` flag is set gets it for free). This module adds the parts that
need their own storage or sequencing: presets and operation chains.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pdfbuilder.job import Ctx, ToolError
from pdfbuilder.registry import P, REGISTRY, tool

CONFIG_DIR = Path.home() / ".config" / "pdf-builder"
PRESET_FILE = CONFIG_DIR / "presets.json"
CHAIN_FILE = CONFIG_DIR / "chains.json"


# ------------------------------------------------------------------ presets

def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def load_presets() -> dict:
    return _read(PRESET_FILE)


def save_preset(name: str, tool_id: str, params: dict) -> None:
    name = (name or "").strip()
    if not name:
        raise ToolError("Give the preset a name.")
    data = load_presets()
    data[name] = {"tool": tool_id, "params": params,
                  "saved": time.strftime("%Y-%m-%d %H:%M")}
    _write(PRESET_FILE, data)


def delete_preset(name: str) -> None:
    data = load_presets()
    if name in data:
        del data[name]
        _write(PRESET_FILE, data)


def presets_for(tool_id: str) -> dict:
    return {k: v for k, v in load_presets().items() if v.get("tool") == tool_id}


# ------------------------------------------------------------------- chains

def load_chains() -> dict:
    return _read(CHAIN_FILE)


def save_chain(name: str, steps: list[dict]) -> None:
    name = (name or "").strip()
    if not name:
        raise ToolError("Give the workflow a name.")
    for step in steps:
        if step.get("tool") not in REGISTRY:
            raise ToolError(f"Unknown tool in the workflow: {step.get('tool')}")
    data = load_chains()
    data[name] = {"steps": steps, "saved": time.strftime("%Y-%m-%d %H:%M")}
    _write(CHAIN_FILE, data)


def delete_chain(name: str) -> None:
    data = load_chains()
    if name in data:
        del data[name]
        _write(CHAIN_FILE, data)


def run_chain(steps, inputs, outdir, *, progress=None, cancelled=None,
              log=None, keep_intermediates=False) -> list[Path]:
    """Feed each step's output into the next one.

    `steps` is a list of {"tool": id, "params": {...}}.
    """
    from pdfbuilder.core.common import is_pdf
    progress = progress or (lambda f, m="": None)
    log = log or (lambda m: None)
    steps = [s for s in steps if s.get("tool")]
    if not steps:
        raise ToolError("Add at least one step to the workflow.")

    outdir = Path(outdir)
    work = outdir / ".chain-work"
    work.mkdir(parents=True, exist_ok=True)
    current = [Path(p) for p in inputs]
    produced_all: list[Path] = []

    for n, step in enumerate(steps, 1):
        tool_obj = REGISTRY.get(step["tool"])
        if tool_obj is None:
            raise ToolError(f"Unknown tool: {step['tool']}")
        if tool_obj.view:
            raise ToolError(f"'{tool_obj.name}' is interactive and cannot run "
                            f"inside a workflow.")
        last = (n == len(steps))
        stage_dir = outdir if last else (work / f"step{n}")
        stage_dir.mkdir(parents=True, exist_ok=True)
        params = {**tool_obj.defaults(), **(step.get("params") or {})}
        log(f"Step {n}/{len(steps)}: {tool_obj.name}")

        def sub(frac, msg=""):
            progress((n - 1 + frac) / len(steps),
                     f"{tool_obj.name}: {msg}" if msg else tool_obj.name)

        made: list[Path] = []
        if tool_obj.multi or len(current) == 1:
            ctx = Ctx(current, params, stage_dir, progress=sub,
                      cancelled=cancelled, log=log)
            try:
                result = tool_obj.fn(ctx) or ctx.produced
            finally:
                ctx.cleanup()
            made = [Path(p) for p in result]
        else:
            for k, one in enumerate(current, 1):
                ctx = Ctx([one], params, stage_dir,
                          progress=lambda f, m="", k=k: sub(
                              (k - 1 + f) / len(current), m),
                          cancelled=cancelled, log=log)
                try:
                    result = tool_obj.fn(ctx) or ctx.produced
                finally:
                    ctx.cleanup()
                made.extend(Path(p) for p in result)

        pdfs = [p for p in made if is_pdf(p)]
        if not made:
            raise ToolError(f"Step {n} ({tool_obj.name}) produced no files, so "
                            f"the workflow cannot continue.")
        produced_all.extend(made)
        current = pdfs or made
        log(f"  -> {len(made)} file(s)")

    if not keep_intermediates:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
        produced_all = [p for p in produced_all if p.exists()]
    progress(1.0, "Workflow complete")
    return produced_all


@tool(id="chain", name="Chain operations into a workflow", category="batch",
      inputs="any+", batchable=False, view="chain",
      summary="Build a sequence such as compress, then watermark, then add "
              "page numbers - and save it to reuse later.")
def chain(ctx):
    raise ToolError("This tool runs in the workflow panel.")


@tool(id="batch_run", name="Apply one tool to many files", category="batch",
      inputs="any+", batchable=False, view="batch",
      summary="Pick any tool, pick your files, and run the same settings "
              "across all of them.")
def batch_run(ctx):
    raise ToolError("This tool runs in the batch panel.")


@tool(id="zip_outputs", name="Bundle files into a ZIP", category="batch",
      inputs="any+", batchable=False,
      summary="Collect any set of files into one archive for easy sharing.",
      params=[P("outname", "Archive name", "str", "pdf-builder-output.zip"),
              P("flatten", "Ignore folder structure", "bool", True)])
def zip_outputs(ctx):
    import zipfile
    if not ctx.inputs:
        raise ToolError("Select the files to bundle.")
    name = str(ctx.p["outname"] or "pdf-builder-output.zip")
    if not name.lower().endswith(".zip"):
        name += ".zip"
    target = ctx.out(name)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for n, path in enumerate(ctx.inputs, 1):
            ctx.progress(n / len(ctx.inputs), path.name)
            arc = path.name if ctx.p["flatten"] else str(path).lstrip("/")
            z.write(path, arc)
    from pdfbuilder.core.common import human_size
    ctx.log(f"{len(ctx.inputs)} file(s) -> {human_size(target.stat().st_size)}")
    return ctx.done(target)


@tool(id="presets_manage", name="Saved presets and workflows",
      category="batch", inputs="none", view="presets",
      summary="Review, rename and delete the presets and workflows you have "
              "saved.")
def presets_manage(ctx):
    raise ToolError("This tool runs in the presets panel.")
