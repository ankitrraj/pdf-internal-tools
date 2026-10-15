"""Declarative tool registry.

Every user-facing feature is a Tool: a spec (id, name, category, accepted
inputs, parameters) plus a function. The GUI builds its form from the spec,
so adding a feature never means writing a dialog.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Iterable


# ---------------------------------------------------------------- parameters

@dataclasses.dataclass
class P:
    """One parameter of a tool. `kind` drives which widget the GUI renders."""
    key: str
    label: str
    kind: str = "str"          # str,text,int,float,bool,choice,pages,color,file,dir,font
    default: object = None
    choices: tuple = ()
    lo: float = 0
    hi: float = 1_000_000
    step: float = 1
    suffix: str = ""
    help: str = ""
    # show this param only when another param has one of these values
    when: tuple = ()           # (other_key, (value, ...))

    def coerce(self, v):
        if self.kind == "int":
            return int(round(float(v)))
        if self.kind == "float":
            return float(v)
        if self.kind == "bool":
            return bool(v)
        return v


# --------------------------------------------------------------------- tools

@dataclasses.dataclass
class Tool:
    id: str
    name: str
    category: str
    fn: Callable
    inputs: str = "pdf"        # pdf | pdf+ | image+ | any | any+ | none
    params: tuple = ()
    summary: str = ""
    batchable: bool = True     # single-input tools can be mapped over many files
    needs: tuple = ()          # external binaries required
    view: str = ""             # custom UI panel id instead of a generated form

    @property
    def multi(self) -> bool:
        return self.inputs.endswith("+")

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.params}


# The jobs people reach for most often, surfaced above the categories so a
# 120-tool app still has an obvious starting point.
POPULAR: tuple[str, ...] = (
    "merge", "split_ranges", "compress", "images_to_pdf", "pdf_to_images",
    "docx_to_pdf", "pdf_to_docx", "organize_visual", "editor", "protect",
    "sign_pdf", "ocr_pdf", "watermark_text", "page_numbers", "view_pdf",
)

CATEGORIES: list[tuple[str, str]] = [
    ("organize", "Organize pages"),
    ("compress", "Compress & optimize"),
    ("edit", "Edit & annotate"),
    ("layout", "Layout & formatting"),
    ("security", "Security"),
    ("convert", "Convert"),
    ("office", "Office documents"),
    ("ocr", "Scan & OCR"),
    ("forms", "Forms & signatures"),
    ("utility", "Document utilities"),
    ("image", "Image utilities"),
    ("batch", "Batch & workflows"),
]
CATEGORY_NAMES = dict(CATEGORIES)

REGISTRY: dict[str, Tool] = {}


def tool(*, id: str, name: str, category: str, inputs: str = "pdf",
         params: Iterable[P] = (), summary: str = "", batchable: bool = True,
         needs: Iterable[str] = (), view: str = ""):
    def deco(fn):
        if id in REGISTRY:
            raise RuntimeError(f"duplicate tool id {id!r}")
        REGISTRY[id] = Tool(id=id, name=name, category=category, fn=fn,
                            inputs=inputs, params=tuple(params), summary=summary,
                            batchable=batchable, needs=tuple(needs), view=view)
        return fn
    return deco


def get(tool_id: str) -> Tool:
    return REGISTRY[tool_id]


def by_category(cat: str) -> list[Tool]:
    return [t for t in REGISTRY.values() if t.category == cat]


def load_all() -> None:
    """Import every core module so the @tool decorators register themselves.

    The imports look unused on purpose - importing *is* the registration.
    """
    from pdfbuilder.core import (  # noqa: F401
        organize, compress, edit, layout, security, convert,
        office, ocr, forms, utility, images, batch,
    )
