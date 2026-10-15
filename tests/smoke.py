import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
WORK = Path(os.environ.get("PDFBUILDER_TEST_DIR", HERE / "_work"))
WORK.mkdir(parents=True, exist_ok=True)
import shutil
import zipfile
"""Run every non-interactive tool against the fixtures and report."""
import shutil, sys, traceback, time
from pathlib import Path


from pdfbuilder import registry
from pdfbuilder.job import Ctx, ToolError
registry.load_all()

FIX = Path(sys.argv[1]); OUT = Path(sys.argv[2])
only = sys.argv[3:] or None
if OUT.exists(): shutil.rmtree(OUT)
OUT.mkdir(parents=True)

F = lambda n: str(FIX / n)

# per-tool inputs and parameter overrides
CASES = {
 "merge":            ([F("sample.pdf"), F("other.pdf")], {}),
 "split_ranges":     ([F("sample.pdf")], {"ranges": "1-2\n3-4", "zip": True}),
 "split_every":      ([F("sample.pdf")], {"size": 2, "zip": True}),
 "split_single":     ([F("sample.pdf")], {}),
 "extract":          ([F("sample.pdf")], {"pages": "2,4-5"}),
 "delete_pages":     ([F("sample.pdf")], {"pages": "1,3"}),
 "reorder":          ([F("sample.pdf")], {"order": "3,1,2"}),
 "rotate":           ([F("sample.pdf")], {"angle": "90", "pages": "1-3"}),
 "duplicate":        ([F("sample.pdf")], {"pages": "1", "times": 2}),
 "reverse":          ([F("sample.pdf")], {}),
 "blank_pages":      ([F("sample.pdf")], {"count": 2, "at": "after page", "after": 2}),
 "insert_pdf":       ([F("sample.pdf")], {"other": F("other.pdf"), "at": "after page", "after": 1}),
 "compress":         ([F("sample.pdf")], {}),
 "downsample":       ([F("sample.pdf")], {"dpi": 90, "gray": True}),
 "clean_objects":    ([F("sample.pdf")], {}),
 "linearize":        ([F("sample.pdf")], {}),
 "size_report":      ([F("sample.pdf"), F("other.pdf")], {}),
 "add_text":         ([F("sample.pdf")], {"text": "Hello there", "background": "#eeeeee"}),
 "insert_image_tool":([F("sample.pdf")], {"image": F("pic1.jpg")}),
 "draw_shape":       ([F("sample.pdf")], {"shape": "arrow", "fill": "#ffeeaa"}),
 "markup_text":      ([F("sample.pdf")], {"terms": "apple", "style": "highlight"}),
 "sticky_note":      ([F("sample.pdf")], {"text": "Check this", "anchor": "on each match of a term", "term": "apple"}),
 "stamp":            ([F("sample.pdf")], {"kind": "APPROVED", "date": True, "rotate": 15}),
 "freehand":         ([F("sample.pdf")], {}),
 "remove_annots":    ([F("sample.pdf")], {}),
 "crop":             ([F("sample.pdf")], {"mode": "auto-detect content"}),
 "margins":          ([F("sample.pdf")], {}),
 "page_size":        ([F("sample.pdf")], {"size": "Letter"}),
 "orientation":      ([F("sample.pdf")], {"to": "landscape", "how": "re-fit content onto new page"}),
 "page_numbers":     ([F("sample.pdf")], {"format": "Page 1 of N", "position": "bottom-outer"}),
 "watermark_text":   ([F("sample.pdf")], {"layout": "tiled across the page"}),
 "watermark_image":  ([F("sample.pdf")], {"image": F("pic2.png")}),
 "header_footer":    ([F("sample.pdf")], {"header_left": "{file}", "header_right": "{date}", "rule": True}),
 "borders":          ([F("sample.pdf")], {"double": True, "radius": 8}),
 "nup":              ([F("sample.pdf")], {"per": "4", "frame": True}),
 "split_page":       ([F("sample.pdf")], {"direction": "into quarters"}),
 "flatten":          ([F("form.pdf")], {}),
 "protect":          ([F("sample.pdf")], {"user_pw": "abc123"}),
 "unprotect":        ([F("locked.pdf")], {"password": "secret"}),
 "encrypt_only":     ([F("sample.pdf")], {"owner_pw": "owner1"}),
 "restrictions":     ([F("sample.pdf")], {"owner_pw": "owner1"}),
 "permissions":      ([F("sample.pdf")], {}),
 "strip_metadata":   ([F("sample.pdf")], {}),
 "redact":           ([F("sample.pdf")], {"terms": "Confidential\nnobody@example.com"}),
 "images_to_pdf":    ([F("pic1.jpg"), F("pic2.png"), F("pic3.webp"), F("pic4.tif"), F("pic5.bmp")], {}),
 "pdf_to_images":    ([F("sample.pdf")], {"pages": "1-2", "format": "JPEG"}),
 "extract_images":   ([F("sample.pdf")], {}),
 "pdf_to_text":      ([F("sample.pdf")], {}),
 "text_to_pdf":      ([F("notes.txt")], {}),
 "html_to_pdf":      ([F("page.html")], {}),
 "md_to_pdf":        ([F("doc.md")], {}),
 "pdf_to_html":      ([F("sample.pdf")], {"pages": "1-2"}),
 "pdf_to_svg":       ([F("sample.pdf")], {"pages": "1"}),
 "pdf_to_pdfa":     ([F("sample.pdf")], {}),
 "pdf_to_zip":       ([F("sample.pdf")], {"contents": "page images (PNG)", "dpi": 72}),
 "zip_to_pdf":       ([F("bundle.zip")], {}),
 "docx_to_pdf":      ([F("letter.docx")], {}),
 "xlsx_to_pdf":      ([F("sheet.xlsx")], {}),
 "pptx_to_pdf":      ([F("deck.pptx")], {}),
 "odt_to_pdf":       ([F("letter.docx")], {}),      # expect a clear error
 "ods_to_pdf":       ([F("sheet.xlsx")], {}),       # expect a clear error
 "odp_to_pdf":       ([F("deck.pptx")], {}),        # expect a clear error
 "rtf_to_pdf":       ([F("note.rtf")], {}),
 "epub_to_pdf":      ([F("note.rtf")], {}),         # expect a clear error
 "pdf_to_docx":      ([F("sample.pdf")], {"pages": "1-2"}),
 "pdf_to_xlsx":      ([F("sample.pdf")], {"pages": "1-2"}),
 "pdf_to_pptx":      ([F("sample.pdf")], {"pages": "1-2"}),
 "pdf_to_rtf":       ([F("sample.pdf")], {}),
 "pdf_to_csv":       ([F("sample.pdf")], {"pages": "1"}),
 "pdf_to_xml":       ([F("sample.pdf")], {"pages": "1"}),
 "images_to_scan_pdf":([F("scan-page.png")], {"ocr": False, "autorotate": False}),
 "ocr_pdf":          ([F("scanned.pdf")], {}),
 "ocr_read":         ([F("scan-page.png")], {}),
 "fix_orientation":  ([F("sample.pdf")], {"method": "page shape only"}),
 "deskew_pdf":       ([F("scanned.pdf")], {"dpi": 110}),
 "remove_blank":     ([F("scanned.pdf")], {}),
 "enhance_pdf":      ([F("scanned.pdf")], {"dpi": 110}),
 "form_inspect":     ([F("form.pdf")], {"save_json": True}),
 "form_fill_data":   ([F("form.pdf")], {"data": F("fields.json"), "flatten": True}),
 "form_reset":       ([F("form.pdf")], {}),
 "form_flatten":     ([F("form.pdf")], {}),
 "form_create_quick":([F("sample.pdf")], {"kind": "dropdown", "options": "A\nB"}),
 "sign_image":       ([F("sample.pdf")], {"image": F("pic2.png")}),
 "sign_fields":      ([F("sample.pdf")], {"count": 2, "labels": "Buyer\nSeller"}),
 "form_export":      ([F("form.pdf")], {"include_empty": True, "format": "both"}),
 "search_text":      ([F("sample.pdf"), F("other.pdf")], {"query": "apple", "save": True}),
 "properties":       ([F("sample.pdf")], {"save": True}),
 "page_info":        ([F("sample.pdf")], {"save": True}),
 "font_info":        ([F("sample.pdf")], {"save": True}),
 "edit_metadata":    ([F("sample.pdf")], {"title": "New title", "author": "Me"}),
 "bookmarks":        ([F("sample.pdf")], {"outline": "Intro @ 1\n  Sub @ 2\nEnd @ 5"}),
 "toc_page":         ([F("sample.pdf")], {}),
 "repair":           ([F("broken.pdf")], {}),
 "compare_report":   ([F("sample.pdf"), F("sample-v2.pdf")], {"dpi": 80}),
 "save_pages":       ([F("sample.pdf")], {"pages": "1-2", "as": "PNG", "dpi": 100}),
 "img_resize":       ([F("pic1.jpg"), F("pic2.png")], {}),
 "img_compress":     ([F("pic1.jpg")], {}),
 "img_convert":      ([F("pic2.png")], {"format": "JPEG"}),
 "img_crop":         ([F("pic1.jpg")], {"mode": "aspect ratio"}),
 "img_rotate":       ([F("pic1.jpg")], {"angle": "custom", "custom": 12}),
 "img_gray":         ([F("pic1.jpg")], {"mode": "sepia"}),
 "img_adjust":       ([F("pic1.jpg")], {"autolevel": True, "contrast": 1.2}),
 "img_passport":     ([F("pic1.jpg")], {}),
 "img_border":       ([F("pic1.jpg")], {"radius": 24}),
 "qr_code":          ([], {"data": "https://example.com", "label": "Scan me", "pdf": True}),
 "zip_outputs":      ([F("pic1.jpg"), F("notes.txt")], {}),
 "print_pdf":        ([F("sample.pdf")], {}),       # expect a clear error
}

EXPECT_ERROR = {"odt_to_pdf", "ods_to_pdf", "odp_to_pdf", "epub_to_pdf",
                "print_pdf"}
NEEDS_TESS = {"ocr_pdf", "ocr_read"}
from pdfbuilder import deps

results = []
tools = [t for t in registry.REGISTRY.values() if not t.view]
if only:
    tools = [t for t in tools if t.id in only]
for tool in tools:
    if tool.id not in CASES:
        results.append((tool.id, "NO-CASE", "", 0)); continue
    inputs, over = CASES[tool.id]
    params = {**tool.defaults(), **over}
    d = OUT / tool.id; d.mkdir(parents=True, exist_ok=True)
    logs = []
    ctx = Ctx(inputs, params, d, log=logs.append)
    t0 = time.monotonic()
    try:
        made = tool.fn(ctx) or ctx.produced
        dt = time.monotonic() - t0
        made = [Path(m) for m in made]
        bad = [m for m in made if not m.exists() or m.stat().st_size == 0]
        summary = getattr(ctx, "summary", {})
        if tool.id in EXPECT_ERROR:
            results.append((tool.id, "UNEXPECTED-OK", f"{len(made)} files", dt))
        elif bad:
            results.append((tool.id, "EMPTY-OUTPUT", str(bad[0].name), dt))
        elif not made and not summary:
            results.append((tool.id, "NO-OUTPUT", "; ".join(logs[-2:]), dt))
        else:
            info = f"{len(made)} file(s)" if made else f"{len(summary)} report rows"
            results.append((tool.id, "ok", info, dt))
    except ToolError as e:
        dt = time.monotonic() - t0
        msg = str(e).splitlines()[0][:110]
        if tool.id in EXPECT_ERROR or (tool.id in NEEDS_TESS and not deps.have("tesseract")):
            results.append((tool.id, "ok (clear error)", msg, dt))
        else:
            results.append((tool.id, "TOOLERROR", msg, dt))
    except Exception as e:
        dt = time.monotonic() - t0
        results.append((tool.id, "CRASH",
                        f"{type(e).__name__}: {e}".replace("\n"," ")[:160], dt))
        traceback.print_exc(limit=6)
    finally:
        ctx.cleanup()

bad = [r for r in results if not r[1].startswith("ok")]
print("\n" + "="*78)
for tid, st, info, dt in results:
    flag = "    " if st.startswith("ok") else " >> "
    print(f"{flag}{tid:22s} {st:16s} {dt:6.2f}s  {info}")
print("="*78)
print(f"{len(results)-len(bad)}/{len(results)} ok   ·   {len(bad)} need attention")