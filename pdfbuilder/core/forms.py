"""Category 9 - forms and signatures."""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz

from pdfbuilder.core.common import MM, open_pdf, save_pdf
from pdfbuilder.job import ToolError
from pdfbuilder.registry import P, tool

PW = P("password", "Password (if protected)", "str", "")

WIDGET_NAMES = {
    fitz.PDF_WIDGET_TYPE_TEXT: "text",
    fitz.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    fitz.PDF_WIDGET_TYPE_COMBOBOX: "dropdown",
    fitz.PDF_WIDGET_TYPE_LISTBOX: "list",
    fitz.PDF_WIDGET_TYPE_SIGNATURE: "signature",
    fitz.PDF_WIDGET_TYPE_BUTTON: "button",
}


def list_fields(path, password="") -> list[dict]:
    doc = open_pdf(path, password)
    out = []
    for i in range(doc.page_count):
        for w in doc[i].widgets() or []:
            out.append({
                "page": i + 1,
                "name": w.field_name or "",
                "label": w.field_label or "",
                "type": WIDGET_NAMES.get(w.field_type, str(w.field_type)),
                "value": w.field_value,
                "options": list(w.choice_values or []),
                "rect": [round(v, 1) for v in w.rect],
                "required": bool(w.field_flags & 2),
                "readonly": bool(w.field_flags & 1),
            })
    doc.close()
    return out


@tool(id="form_inspect", name="List form fields", category="forms",
      summary="Show every fillable field, its type and current value.",
      params=[P("save_json", "Save the list as JSON", "bool", False), PW])
def form_inspect(ctx):
    fields = list_fields(ctx.src, ctx.p["password"])
    if not fields:
        ctx.log("This PDF has no interactive form fields. Use 'Create "
                "fillable fields' to add some, or the Edit panel to type "
                "directly onto the page.")
        return []
    ctx.summary = {
        f"p{f['page']} · {f['name'] or '(unnamed)'}":
        f"{f['type']}"
        + (f" = {f['value']}" if f["value"] not in (None, "") else " (empty)")
        + (" · required" if f["required"] else "")
        for f in fields}
    ctx.log(f"{len(fields)} field(s) found.")
    made = []
    if ctx.p["save_json"]:
        out = ctx.derive("fields", ".json")
        out.write_text(json.dumps(fields, indent=2, default=str),
                       encoding="utf-8")
        made.append(out)
    return ctx.done(*made)


@tool(id="form_fill", name="Fill in form fields", category="forms",
      view="formfill",
      summary="Open the document's form and type into every field, with "
              "checkboxes, dropdowns and date pickers.")
def form_fill(ctx):
    raise ToolError("This tool runs in its own form panel.")


@tool(id="form_fill_data", name="Fill a form from a data file",
      category="forms",
      summary="Apply values from a JSON or CSV file - handy for filling the "
              "same form many times.",
      params=[P("data", "Data file (JSON or CSV)", "file", "",
                help="JSON object of field:value, or a CSV with a header row"),
              P("row", "CSV row (0 = every row, one PDF each)", "int", 0, lo=0,
                hi=100000),
              P("flatten", "Flatten the result", "bool", False),
              P("missing", "If a field is not in the data", "choice",
                "leave it alone", choices=("leave it alone", "clear it")),
              PW])
def form_fill_data(ctx):
    path = Path(str(ctx.p["data"] or ""))
    if not path.exists():
        raise ToolError("Choose a JSON or CSV file with the values to apply.")
    rows: list[dict] = []
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else [raw]
    else:
        import csv
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
    if not rows:
        raise ToolError(f"{path.name} contains no data rows.")
    wanted = int(ctx.p["row"])
    if wanted:
        if wanted > len(rows):
            raise ToolError(f"{path.name} has only {len(rows)} row(s).")
        rows = [rows[wanted - 1]]
    made = []
    for n, row in enumerate(rows, 1):
        ctx.progress(n / len(rows), f"Row {n}")
        doc = open_pdf(ctx.src, ctx.p["password"])
        applied = 0
        for i in range(doc.page_count):
            for w in doc[i].widgets() or []:
                name = w.field_name or ""
                if name in row:
                    if _set_widget(w, row[name]):
                        applied += 1
                elif ctx.p["missing"] == "clear it":
                    _set_widget(w, "")
        if ctx.p["flatten"]:
            from pdfbuilder.core.layout import _burn_widget
            for i in range(doc.page_count):
                for w in list(doc[i].widgets() or []):
                    _burn_widget(doc[i], w)
        tag = "filled" if len(rows) == 1 else f"filled{n:03d}"
        made.append(save_pdf(doc, ctx.derive(tag)))
        doc.close()
        ctx.log(f"Row {n}: set {applied} field(s).")
    return ctx.done(*made)


def _set_widget(w, value) -> bool:
    try:
        t = w.field_type
        if t == fitz.PDF_WIDGET_TYPE_CHECKBOX:
            on = str(value).strip().lower() in ("1", "true", "yes", "y", "on",
                                                "x", "checked")
            w.field_value = on
        elif t == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
            w.field_value = str(value)
        elif t in (fitz.PDF_WIDGET_TYPE_COMBOBOX,
                   fitz.PDF_WIDGET_TYPE_LISTBOX):
            opts = list(w.choice_values or [])
            match = next((o for o in opts
                          if str(o).strip().lower() == str(value).strip().lower()),
                         None)
            w.field_value = match if match is not None else str(value)
        else:
            w.field_value = "" if value is None else str(value)
        w.update()
        return True
    except Exception:
        return False


@tool(id="form_reset", name="Reset form fields", category="forms",
      summary="Clear every entry so the form is blank again.",
      params=[P("which", "Clear", "choice", "all fields",
                choices=("all fields", "text fields only",
                         "tick boxes and choices only")),
              P("keep", "Fields to keep (comma separated names)", "str", ""),
              PW])
def form_reset(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    keep = {k.strip() for k in str(ctx.p["keep"] or "").split(",") if k.strip()}
    cleared = 0
    for i in range(doc.page_count):
        for w in doc[i].widgets() or []:
            if (w.field_name or "") in keep:
                continue
            t = w.field_type
            is_text = t == fitz.PDF_WIDGET_TYPE_TEXT
            if ctx.p["which"] == "text fields only" and not is_text:
                continue
            if ctx.p["which"].startswith("tick") and is_text:
                continue
            if t == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                ok = _set_widget(w, False)
            else:
                ok = _set_widget(w, "")
            cleared += bool(ok)
    target = save_pdf(doc, ctx.derive("reset"))
    doc.close()
    ctx.log(f"Cleared {cleared} field(s).")
    return ctx.done(target)


@tool(id="form_flatten", name="Flatten a completed form", category="forms",
      summary="Turn the answers into permanent page content so they can no "
              "longer be changed.",
      params=[P("keep_appearance", "Keep the exact look (rasterise fields)",
                "bool", False),
              P("dpi", "Raster resolution", "int", 200, lo=72, hi=600,
                suffix=" dpi", when=("keep_appearance", (True,))),
              PW])
def form_flatten(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    count = 0
    from pdfbuilder.core.layout import _burn_widget
    for i in range(doc.page_count):
        page = doc[i]
        widgets = list(page.widgets() or [])
        count += len(widgets)
        for w in widgets:
            if ctx.p["keep_appearance"]:
                try:
                    pix = page.get_pixmap(clip=w.rect,
                                          dpi=int(ctx.p["dpi"]))
                    page.delete_widget(w)
                    page.insert_image(w.rect, pixmap=pix, overlay=True)
                    continue
                except Exception:
                    pass
            _burn_widget(page, w)
    if count == 0:
        ctx.log("No form fields to flatten.")
    target = save_pdf(doc, ctx.derive("flat"), garbage=3)
    doc.close()
    ctx.log(f"Flattened {count} field(s).")
    return ctx.done(target)


FIELD_KINDS = ("text", "checkbox", "radio button", "dropdown", "date",
               "signature")


@tool(id="form_create", name="Create fillable fields", category="forms",
      view="fieldmaker",
      summary="Draw text boxes, tick boxes, radio groups, dropdowns, date "
              "and signature fields straight onto the page.")
def form_create(ctx):
    raise ToolError("This tool runs in the field designer panel.")


@tool(id="form_create_quick", name="Add a field by position", category="forms",
      summary="Add one field at exact coordinates - useful for scripted or "
              "repeated layouts.",
      params=[P("kind", "Field type", "choice", "text", choices=FIELD_KINDS),
              P("name", "Field name", "str", "field1"),
              P("page", "Page", "int", 1, lo=1),
              P("x", "Left", "float", 20, lo=0, hi=2000, suffix=" mm"),
              P("y", "Top", "float", 20, lo=0, hi=2000, suffix=" mm"),
              P("w", "Width", "float", 80, lo=2, hi=2000, suffix=" mm"),
              P("h", "Height", "float", 8, lo=2, hi=2000, suffix=" mm"),
              P("value", "Starting value", "str", "",
                help="Radio buttons always start unselected - the reader "
                     "chooses one"),
              P("options", "Choices (one per line)", "text", "",
                when=("kind", ("dropdown", "radio button"))),
              P("required", "Required", "bool", False),
              P("multiline", "Multi-line", "bool", False,
                when=("kind", ("text",))),
              P("fontsize", "Text size", "float", 10, lo=4, hi=48,
                suffix=" pt"),
              P("border", "Draw a border", "bool", True), PW])
def form_create_quick(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    pno = min(max(1, int(ctx.p["page"])), doc.page_count) - 1
    page = doc[pno]
    rect = fitz.Rect(float(ctx.p["x"]) * MM, float(ctx.p["y"]) * MM,
                     (float(ctx.p["x"]) + float(ctx.p["w"])) * MM,
                     (float(ctx.p["y"]) + float(ctx.p["h"])) * MM)
    opts = [o.strip() for o in str(ctx.p["options"] or "").splitlines()
            if o.strip()]
    add_widget(page, ctx.p["kind"], ctx.p["name"], rect,
               value=ctx.p["value"], options=opts,
               required=bool(ctx.p["required"]),
               multiline=bool(ctx.p["multiline"]),
               fontsize=float(ctx.p["fontsize"]),
               border=bool(ctx.p["border"]))
    target = save_pdf(doc, ctx.derive("with-field"))
    doc.close()
    ctx.log(f"Added a {ctx.p['kind']} field on page {pno+1}.")
    return ctx.done(target)


def add_widget(page, kind: str, name: str, rect, *, value="", options=(),
               required=False, multiline=False, fontsize=10.0, border=True,
               font="helv"):
    """Create one form widget. Shared by the designer panel."""
    radio_state = ""
    w = fitz.Widget()
    w.rect = fitz.Rect(rect)
    w.field_name = (name or "field").strip()
    w.text_fontsize = float(fontsize)
    w.text_font = font
    w.fill_color = (1, 1, 1)
    if border:
        w.border_color = (0.45, 0.45, 0.5)
        w.border_width = 0.8
    kind = kind.lower()
    if kind.startswith("check"):
        w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
        w.field_value = bool(value) and str(value).lower() not in ("", "0",
                                                                   "false",
                                                                   "off")
    elif kind.startswith("radio"):
        w.field_type = fitz.PDF_WIDGET_TYPE_RADIOBUTTON
        # A radio button can only be switched on once its group exists in the
        # file, so it is always created unselected and set afterwards.
        state = str(value or "").strip()
        radio_state = (state if state and state.lower() not in
                       ("off", "false", "0", "no") else "")
        w.field_value = False
    elif kind.startswith("drop"):
        w.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
        w.choice_values = list(options) or ["Option 1", "Option 2"]
        w.field_value = str(value or (w.choice_values[0] if w.choice_values
                                      else ""))
    elif kind.startswith("list"):
        w.field_type = fitz.PDF_WIDGET_TYPE_LISTBOX
        w.choice_values = list(options) or ["Option 1", "Option 2"]
        w.field_value = str(value or "")
    elif kind.startswith("sign"):
        # A visible box a signer can draw or type into. True digital
        # certificate signing is out of scope, so this is an appearance field.
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_name = w.field_name or "signature"
        w.field_value = str(value or "")
        w.text_fontsize = max(10.0, float(fontsize))
    elif kind.startswith("date"):
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_value = str(value or "")
        w.text_format = 0
    else:
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.field_value = str(value or "")
        if multiline:
            w.field_flags = w.field_flags | 4096
    if required:
        w.field_flags = (w.field_flags or 0) | 2
    try:
        annot = page.add_widget(w)
    except Exception as e:
        raise ToolError(f"Could not add the field: {e}") from e
    if kind.lower().startswith("radio") and radio_state:
        try:
            annot.field_value = radio_state
            annot.update()
        except Exception:
            pass          # the group may not accept this state; leave it off
    return annot


@tool(id="sign_pdf", name="Sign a PDF", category="forms", view="signature",
      summary="Draw a signature with the mouse, type one in a handwriting "
              "style, or drop in a scanned signature image, then place it "
              "and add the date.")
def sign_pdf(ctx):
    raise ToolError("This tool runs in the signature panel.")


@tool(id="sign_image", name="Insert a signature image", category="forms",
      summary="Place a signature picture (PNG with transparency works best) "
              "at a chosen spot, with an optional date line.",
      params=[P("image", "Signature image", "file", ""),
              P("page", "Page", "choice", "last",
                choices=("last", "first", "all", "number")),
              P("pageno", "Page number", "int", 1, lo=1,
                when=("page", ("number",))),
              P("position", "Position", "choice", "bottom-right",
                choices=("bottom-right", "bottom-left", "bottom-center",
                         "top-right", "top-left", "exact coordinates")),
              P("x", "Left", "float", 120, lo=0, hi=2000, suffix=" mm",
                when=("position", ("exact coordinates",))),
              P("y", "Top", "float", 240, lo=0, hi=2000, suffix=" mm",
                when=("position", ("exact coordinates",))),
              P("width", "Signature width", "float", 55, lo=5, hi=400,
                suffix=" mm"),
              P("margin", "Margin", "float", 18, lo=0, hi=100, suffix=" mm"),
              P("remove_bg", "Make a white background transparent", "bool",
                True),
              P("date", "Add the date underneath", "bool", True),
              P("date_text", "Date text ({today} allowed)", "str", "{today}",
                when=("date", (True,))),
              P("name_line", "Printed name underneath", "str", ""),
              P("flatten", "Flatten so it cannot be moved", "bool", True),
              PW])
def sign_image(ctx):
    import datetime
    import io

    from pdfbuilder.core.images import load_image
    img_path = str(ctx.p["image"] or "")
    if not img_path or not Path(img_path).exists():
        raise ToolError("Choose a signature image file.")
    img = load_image(img_path)
    if ctx.p["remove_bg"]:
        img = _knock_out_white(img)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data = buf.getvalue()

    doc = open_pdf(ctx.src, ctx.p["password"])
    which = ctx.p["page"]
    if which == "last":
        pages = [doc.page_count - 1]
    elif which == "first":
        pages = [0]
    elif which == "all":
        pages = list(range(doc.page_count))
    else:
        pages = [min(max(1, int(ctx.p["pageno"])), doc.page_count) - 1]

    w = float(ctx.p["width"]) * MM
    h = w * img.height / img.width
    m = float(ctx.p["margin"]) * MM
    today = datetime.date.today().strftime("%d %B %Y")
    for pno in pages:
        page = doc[pno]
        r = page.rect
        pos = ctx.p["position"]
        if pos == "exact coordinates":
            x, y = float(ctx.p["x"]) * MM, float(ctx.p["y"]) * MM
        else:
            vert, horiz = pos.split("-")
            y = (r.y1 - m - h) if vert == "bottom" else (r.y0 + m)
            x = {"left": r.x0 + m, "right": r.x1 - m - w,
                 "center": (r.width - w) / 2}[horiz]
        page.insert_image(fitz.Rect(x, y, x + w, y + h), stream=data,
                          overlay=True, keep_proportion=True)
        ty = y + h + 11
        if ctx.p["date"]:
            text = str(ctx.p["date_text"] or "{today}").replace("{today}",
                                                                today)
            page.insert_text((x, ty), text, fontsize=9, fontname="helv",
                             color=(0.2, 0.2, 0.2))
            ty += 12
        if str(ctx.p["name_line"] or "").strip():
            page.insert_text((x, ty), str(ctx.p["name_line"]), fontsize=9,
                             fontname="helv", color=(0.2, 0.2, 0.2))
    target = save_pdf(doc, ctx.derive("signed"), garbage=3)
    doc.close()
    ctx.log(f"Signature placed on {len(pages)} page(s).")
    return ctx.done(target)


def _knock_out_white(img, cutoff: int = 238):
    """Turn a near-white background transparent, for scanned signatures."""
    rgba = img.convert("RGBA")
    px = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = px[x, y]
            if r > cutoff and g > cutoff and b > cutoff:
                px[x, y] = (r, g, b, 0)
            else:
                dark = 255 - min(r, g, b)
                px[x, y] = (r, g, b, min(255, int(a * min(1.0, dark / 40 + .3))))
    return rgba


@tool(id="sign_fields", name="Add signature and date fields", category="forms",
      summary="Place empty 'sign here' and 'date' boxes for someone else to "
              "complete.",
      params=[P("page", "Page", "choice", "last",
                choices=("last", "first", "all", "number")),
              P("pageno", "Page number", "int", 1, lo=1,
                when=("page", ("number",))),
              P("count", "How many signers", "int", 1, lo=1, hi=8),
              P("labels", "Labels (one per signer)", "text", "Signature"),
              P("date_field", "Also add a date field", "bool", True),
              P("width", "Box width", "float", 70, lo=20, hi=300,
                suffix=" mm"),
              P("height", "Box height", "float", 16, lo=6, hi=80,
                suffix=" mm"),
              P("margin", "Margin from the bottom", "float", 25, lo=0, hi=150,
                suffix=" mm"),
              P("line", "Draw a signing line", "bool", True), PW])
def sign_fields(ctx):
    doc = open_pdf(ctx.src, ctx.p["password"])
    which = ctx.p["page"]
    if which == "last":
        pages = [doc.page_count - 1]
    elif which == "first":
        pages = [0]
    elif which == "all":
        pages = list(range(doc.page_count))
    else:
        pages = [min(max(1, int(ctx.p["pageno"])), doc.page_count) - 1]
    labels = [l.strip() for l in str(ctx.p["labels"] or "").splitlines()
              if l.strip()] or ["Signature"]
    n_sign = int(ctx.p["count"])
    bw = float(ctx.p["width"]) * MM
    bh = float(ctx.p["height"]) * MM
    m = float(ctx.p["margin"]) * MM
    for pno in pages:
        page = doc[pno]
        r = page.rect
        per_row = max(1, int((r.width - 2 * m) // (bw + 10 * MM)))
        for k in range(n_sign):
            col, row = k % per_row, k // per_row
            x = m + col * (bw + 10 * MM)
            y = r.y1 - m - row * (bh + 26 * MM) - bh
            label = labels[k % len(labels)]
            add_widget(page, "signature", f"{label}_{pno+1}_{k+1}",
                       fitz.Rect(x, y, x + bw, y + bh), border=False)
            if ctx.p["line"]:
                page.draw_line((x, y + bh + 2), (x + bw, y + bh + 2),
                               color=(0.3, 0.3, 0.3), width=0.7)
            page.insert_text((x, y + bh + 13), label, fontsize=8,
                             fontname="helv", color=(0.35, 0.35, 0.35))
            if ctx.p["date_field"]:
                dx = x + bw + 6 * MM
                if dx + 32 * MM > r.x1 - m:
                    dx = x
                    y += bh + 20 * MM
                add_widget(page, "date", f"Date_{pno+1}_{k+1}",
                           fitz.Rect(dx, y, dx + 32 * MM, y + bh),
                           border=False)
                if ctx.p["line"]:
                    page.draw_line((dx, y + bh + 2), (dx + 32 * MM, y + bh + 2),
                                   color=(0.3, 0.3, 0.3), width=0.7)
                page.insert_text((dx, y + bh + 13), "Date", fontsize=8,
                                 fontname="helv", color=(0.35, 0.35, 0.35))
    target = save_pdf(doc, ctx.derive("sign-here"))
    doc.close()
    ctx.log(f"Added {n_sign} signing block(s).")
    return ctx.done(target)


@tool(id="form_export", name="Export a completed form", category="forms",
      summary="Save the answers as JSON or CSV, and optionally a flattened "
              "PDF copy.",
      params=[P("format", "Export as", "choice", "CSV",
                choices=("CSV", "JSON", "both")),
              P("include_empty", "Include empty fields", "bool", False),
              P("also_pdf", "Also save a flattened PDF", "bool", True), PW])
def form_export(ctx):
    import csv
    fields = list_fields(ctx.src, ctx.p["password"])
    if not fields:
        raise ToolError("This PDF has no form fields to export.")
    if not ctx.p["include_empty"]:
        fields = [f for f in fields if f["value"] not in (None, "", False)]
    if not fields:
        raise ToolError("Every field is empty. Tick 'Include empty fields' to "
                        "export the blank structure.")
    made = []
    if ctx.p["format"] in ("CSV", "both"):
        out = ctx.derive("form", ".csv")
        with open(out, "w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh)
            wr.writerow(["page", "field", "type", "value"])
            for f in fields:
                wr.writerow([f["page"], f["name"], f["type"], f["value"]])
        made.append(out)
        wide = ctx.derive("form-row", ".csv")
        with open(wide, "w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh)
            wr.writerow([f["name"] for f in fields])
            wr.writerow([f["value"] for f in fields])
        made.append(wide)
    if ctx.p["format"] in ("JSON", "both"):
        out = ctx.derive("form", ".json")
        out.write_text(json.dumps({f["name"]: f["value"] for f in fields},
                                  indent=2, default=str), encoding="utf-8")
        made.append(out)
    if ctx.p["also_pdf"]:
        doc = open_pdf(ctx.src, ctx.p["password"])
        from pdfbuilder.core.layout import _burn_widget
        for i in range(doc.page_count):
            for w in list(doc[i].widgets() or []):
                _burn_widget(doc[i], w)
        made.append(save_pdf(doc, ctx.derive("completed")))
        doc.close()
    ctx.log(f"Exported {len(fields)} field value(s).")
    return ctx.done(*made)
