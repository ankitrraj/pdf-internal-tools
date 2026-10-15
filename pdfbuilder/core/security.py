"""Category 5 - security, permissions, metadata and redaction."""
from __future__ import annotations

import pymupdf as fitz

from pdfbuilder.core.common import (open_pdf, parse_pages, save_pdf,
                                    search_text)
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Current password (if protected)", "str", "")

PERM_FLAGS = {
    "print": fitz.PDF_PERM_PRINT,
    "print_hq": fitz.PDF_PERM_PRINT_HQ,
    "copy": fitz.PDF_PERM_COPY,
    "modify": fitz.PDF_PERM_MODIFY,
    "annotate": fitz.PDF_PERM_ANNOTATE,
    "forms": fitz.PDF_PERM_FORM,
    "accessibility": fitz.PDF_PERM_ACCESSIBILITY,
    "assemble": fitz.PDF_PERM_ASSEMBLE,
}

ENCRYPTIONS = {
    "AES-256 (strongest)": fitz.PDF_ENCRYPT_AES_256,
    "AES-128": fitz.PDF_ENCRYPT_AES_128,
    "RC4-128 (legacy readers)": fitz.PDF_ENCRYPT_RC4_128,
}


def _perm_value(p: dict) -> int:
    perm = fitz.PDF_PERM_ACCESSIBILITY
    if p.get("allow_print", True):
        perm |= fitz.PDF_PERM_PRINT
        if p.get("allow_print_hq", True):
            perm |= fitz.PDF_PERM_PRINT_HQ
    if p.get("allow_copy", True):
        perm |= fitz.PDF_PERM_COPY
    if p.get("allow_modify", True):
        perm |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ASSEMBLE
    if p.get("allow_annotate", True):
        perm |= fitz.PDF_PERM_ANNOTATE
    if p.get("allow_forms", True):
        perm |= fitz.PDF_PERM_FORM
    return perm


PERM_PARAMS = [
    P("allow_print", "Allow printing", "bool", True),
    P("allow_print_hq", "Allow high-quality printing", "bool", True),
    P("allow_copy", "Allow copying text and images", "bool", True),
    P("allow_modify", "Allow editing the document", "bool", False),
    P("allow_annotate", "Allow comments and annotations", "bool", False),
    P("allow_forms", "Allow filling in forms", "bool", True),
]


@tool(id="protect", name="Password-protect a PDF", category="security",
      summary="Encrypt the document. The user password is needed to open it; "
              "the owner password controls permissions.",
      params=[P("user_pw", "Password to open the file", "str", ""),
              P("owner_pw", "Owner password (optional)", "str", "",
                help="Leave blank to reuse the open password"),
              P("encryption", "Encryption", "choice", "AES-256 (strongest)",
                choices=tuple(ENCRYPTIONS))] + PERM_PARAMS + [PW])
def protect(ctx):
    user = str(ctx.p["user_pw"] or "")
    if not user.strip():
        raise ToolError("Enter the password that will be needed to open the file.")
    owner = str(ctx.p["owner_pw"] or "").strip() or user
    doc = open_pdf(ctx.src, ctx.p["password"])
    ctx.progress(0.5, "Encrypting")
    target = ctx.derive("protected")
    save_pdf(doc, target, garbage=3,
             encryption=ENCRYPTIONS[ctx.p["encryption"]],
             owner_pw=owner, user_pw=user, permissions=_perm_value(ctx.p))
    doc.close()
    ctx.log(f"Encrypted with {ctx.p['encryption']}.")
    return ctx.done(target)


@tool(id="unprotect", name="Remove a password", category="security",
      summary="Save an unencrypted copy. You must supply the document's own "
              "password - this does not break encryption.",
      params=[P("password", "Current password", "str", ""),
              P("keep_perms", "Keep permission restrictions", "bool", False)])
def unprotect(ctx):
    import pikepdf
    pw = str(ctx.p["password"] or "")
    try:
        with pikepdf.open(str(ctx.src), password=pw) as pdf:
            target = ctx.derive("unlocked")
            pdf.save(str(target))
    except Exception as e:
        if "password" in str(e).lower():
            raise ToolError(
                "That password was not accepted. PDF Builder can only remove "
                "a password when you know it - it does not attempt to crack "
                "encryption."
            ) from e
        doc = open_pdf(ctx.src, pw)
        target = save_pdf(doc, ctx.derive("unlocked"), encryption=fitz.PDF_ENCRYPT_NONE)
        doc.close()
    ctx.log("Saved without encryption.")
    return ctx.done(target)


@tool(id="encrypt_only", name="Encrypt without an open password",
      category="security",
      summary="Apply owner-password encryption: anyone can open the file, "
              "but your restrictions are enforced.",
      params=[P("owner_pw", "Owner password", "str", ""),
              P("encryption", "Encryption", "choice", "AES-256 (strongest)",
                choices=tuple(ENCRYPTIONS))] + PERM_PARAMS + [PW])
def encrypt_only(ctx):
    owner = str(ctx.p["owner_pw"] or "").strip()
    if not owner:
        raise ToolError("Enter an owner password.")
    doc = open_pdf(ctx.src, ctx.p["password"])
    target = ctx.derive("encrypted")
    save_pdf(doc, target, garbage=3,
             encryption=ENCRYPTIONS[ctx.p["encryption"]],
             owner_pw=owner, user_pw="", permissions=_perm_value(ctx.p))
    doc.close()
    return ctx.done(target)


@tool(id="restrictions", name="Set printing / copying / editing limits",
      category="security",
      summary="Change what readers are allowed to do. Needs an owner "
              "password to be enforceable.",
      params=[P("owner_pw", "Owner password", "str", "pdfbuilder"),
              P("keep_user_pw", "Also require a password to open", "bool", False),
              P("user_pw", "Open password", "str", "",
                when=("keep_user_pw", (True,)))] + PERM_PARAMS + [PW])
def restrictions(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    owner = str(ctx.p["owner_pw"] or "").strip()
    if not owner:
        raise ToolError("Permissions can only be enforced with an owner password.")
    user = str(ctx.p["user_pw"] or "") if ctx.p["keep_user_pw"] else ""
    target = ctx.derive("restricted")
    save_pdf(doc, target, garbage=3, encryption=fitz.PDF_ENCRYPT_AES_256,
             owner_pw=owner, user_pw=user, permissions=_perm_value(ctx.p))
    doc.close()
    ctx.log("Permissions updated.")
    return ctx.done(target)


@tool(id="permissions", name="View document permissions", category="security",
      summary="Report the encryption and what the file currently allows.",
      params=[PW])
def permissions(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    perm = doc.permissions
    info = {
        "Encrypted": "yes" if doc.is_encrypted or doc.needs_pass else "no",
        "Needs a password to open": "yes" if doc.needs_pass else "no",
        "Printing": _yn(perm & fitz.PDF_PERM_PRINT),
        "High-quality printing": _yn(perm & fitz.PDF_PERM_PRINT_HQ),
        "Copying text / images": _yn(perm & fitz.PDF_PERM_COPY),
        "Editing content": _yn(perm & fitz.PDF_PERM_MODIFY),
        "Annotating": _yn(perm & fitz.PDF_PERM_ANNOTATE),
        "Filling forms": _yn(perm & fitz.PDF_PERM_FORM),
        "Page assembly": _yn(perm & fitz.PDF_PERM_ASSEMBLE),
        "Accessibility extraction": _yn(perm & fitz.PDF_PERM_ACCESSIBILITY),
    }
    doc.close()
    ctx.summary = info
    for k, v in info.items():
        ctx.log(f"{k}: {v}")
    return []


def _yn(v) -> str:
    return "allowed" if v else "not allowed"


META_KEYS = ("title", "author", "subject", "keywords", "creator", "producer")


@tool(id="strip_metadata", name="Remove metadata", category="security",
      summary="Delete document information, and optionally XMP metadata and "
              "embedded identifiers.",
      params=[P("fields", "Clear", "choice", "everything",
                choices=("everything", "author and creator only",
                         "dates only")),
              P("xmp", "Also remove XMP metadata", "bool", True),
              P("ids", "Reset the document ID", "bool", True),
              P("drop_toc", "Also remove bookmarks", "bool", False), PW])
def strip_metadata(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    mode = ctx.p["fields"]
    meta = {k: "" for k in META_KEYS}
    meta.update({"creationDate": "", "modDate": "", "trapped": ""})
    if mode == "author and creator only":
        meta = {**doc.metadata, "author": "", "creator": "", "producer": ""}
    elif mode == "dates only":
        meta = {**doc.metadata, "creationDate": "", "modDate": ""}
    doc.set_metadata({k: v for k, v in meta.items() if v is not None})
    if ctx.p["xmp"]:
        try:
            doc.del_xml_metadata()
        except Exception:
            pass
    if ctx.p["drop_toc"]:
        doc.set_toc([])
    target = ctx.derive("no-metadata")
    save_pdf(doc, target, garbage=4, clean=True)
    doc.close()
    if ctx.p["ids"]:
        try:
            import pikepdf
            with pikepdf.open(str(target), allow_overwriting_input=True) as pdf:
                if "/ID" in pdf.trailer:
                    del pdf.trailer["/ID"]
                pdf.save(str(target))
        except Exception:
            pass
    ctx.log("Metadata removed.")
    return ctx.done(target)


@tool(id="redact", name="Permanently redact content", category="security",
      summary="Black out text and remove it from the file for good. Search "
              "for words, or draw boxes in the Edit panel.",
      params=[P("terms", "Words or phrases to redact (one per line)", "text", "",
                help="Every occurrence is found and destroyed, not just hidden"),
              P("regex", "Treat each line as a regular expression", "bool",
                False),
              P("case", "Match upper/lower case exactly", "bool", False),
              P("fill", "Box colour", "color", "#000000"),
              P("label", "Text to print over the box", "str", ""),
              P("images", "Also remove images that overlap a match", "bool",
                True),
              P("keep_layout", "Keep the removed text's space", "bool", True),
              P("all_metadata", "Strip metadata as well", "bool", True),
              P("pages", "Pages", "pages", "all"), PW])
def redact(ctx):
    import re as _re
    doc = open_pdf(ctx.src, ctx.p["password"])
    idxs = parse_pages(ctx.p["pages"], doc.page_count)
    terms = [t for t in str(ctx.p["terms"] or "").splitlines() if t.strip()]
    if not terms:
        raise ToolError("Enter at least one word or phrase to redact.")
    from pdfbuilder.core.common import parse_color
    fill = parse_color(ctx.p["fill"])
    hits = 0
    for n, i in enumerate(idxs, 1):
        page = doc[i]
        boxes = []
        if ctx.p["regex"]:
            flags = 0 if ctx.p["case"] else _re.IGNORECASE
            words = page.get_text("words")
            for t in terms:
                try:
                    pat = _re.compile(t, flags)
                except _re.error as e:
                    raise ToolError(f"Invalid regular expression {t!r}: {e}")
                for w in words:
                    if pat.search(w[4]):
                        boxes.append(fitz.Rect(w[:4]))
        else:
            for t in terms:
                boxes.extend(search_text(page, t, case=bool(ctx.p["case"])))
        for b in boxes:
            page.add_redact_annot(b, text=str(ctx.p["label"] or "") or None,
                                  fill=fill, fontsize=8,
                                  text_color=(1, 1, 1))
        hits += len(boxes)
        img_mode = (fitz.PDF_REDACT_IMAGE_REMOVE if ctx.p["images"]
                    else fitz.PDF_REDACT_IMAGE_NONE)
        try:
            page.apply_redactions(images=img_mode)
        except TypeError:
            page.apply_redactions()
        ctx.progress(n / len(idxs))
    if ctx.p["all_metadata"]:
        doc.set_metadata({})
        try:
            doc.del_xml_metadata()
        except Exception:
            pass
    target = ctx.derive("redacted")
    save_pdf(doc, target, garbage=4, clean=True, deflate=True)
    doc.close()
    if hits == 0:
        ctx.log("No matches found - nothing was redacted.")
    else:
        ctx.log(f"Redacted {hits} occurrence(s) and removed the underlying text.")
    return ctx.done(target)


@tool(id="redact_boxes", name="Redact drawn areas", category="security",
      view="editor",
      summary="Draw rectangles over anything to delete, then export. The "
              "content underneath is destroyed, not just covered.")
def redact_boxes(ctx):
    raise ToolError("This tool runs in the visual editor panel.")
