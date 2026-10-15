# PDF Builder

A desktop PDF toolkit for Linux. Merge, split, compress, convert, scan, sign,
redact and edit — **120 tools** across 12 categories, all running on your own
machine. No account, no upload, no network access at any point.

---

## Install

```bash
./install.sh      # creates .venv, installs the Python packages, adds a menu entry
./run.sh          # start the app
```

`install.sh` also reports which **optional** system programs are missing. The
app works without them; each one unlocks extra features:

| Program | Install | Unlocks |
|---|---|---|
| `libreoffice` | `sudo apt install libreoffice` | High-fidelity DOCX/XLSX/PPTX/ODT/RTF conversion |
| `tesseract-ocr` | `sudo apt install tesseract-ocr` | Extra OCR languages and page-orientation detection |
| `ghostscript` | `sudo apt install ghostscript` | Strongest compression, PDF/A output |
| `qpdf` | `sudo apt install qpdf` | Structural repair of damaged files |
| `poppler-utils` | `sudo apt install poppler-utils` | Faster page rasterising |

**OCR works without installing anything.** The app ships a built-in
recogniser (RapidOCR, models bundled in the Python wheel) that handles English
scans at roughly 4 seconds a page. Installing Tesseract adds dozens more
languages and page-orientation detection:
`sudo apt install tesseract-ocr tesseract-ocr-hin tesseract-ocr-fra …`
Pick the engine per job with the **Recogniser** option on any OCR tool.

Without LibreOffice, Office conversions fall back to a built-in converter that
keeps the text and tables but simplifies the layout. The app tells you when
that happens rather than failing.

## Command line

```bash
./run.sh file.pdf          # open with a file already loaded
./run.sh --list-tools      # print every tool
./run.sh --check           # report optional components
```

---

## Finding a tool

The sidebar opens on **Start here**, which lists the fifteen most common jobs
(merge, images to PDF, Word to PDF, compress, sign, OCR…). Everything else is
grouped in the categories below it, and **Ctrl+K** searches all 120 by name.

The two asked about most often:

- **Images → PDF**: *Start here* → “Images to PDF”, or the **Convert** category
- **Word → PDF**: *Start here* → “Word (DOCX) to PDF”, or the **Office documents** category

## What's in it

### Organize pages  (14)

- **Merge PDFs into one** — Join every selected PDF, in list order, into a single document.
- **Split by page ranges** — Each range becomes its own PDF. One range per line.
- **Split into equal page groups** — Cut the document into chunks of N pages each.
- **Split into one file per page** — Every page is saved as its own PDF.
- **Extract selected pages** — Keep only the pages you list, as one new PDF.
- **Delete selected pages** — Remove the listed pages and keep everything else.
- **Reorder pages** — Give the new page order explicitly, e.g. '3,1,2,4-'.
- **Rotate pages** — Rotate every page, or only the ones you list.
- **Duplicate pages** — Repeat the chosen pages a number of times.
- **Reverse page order** — Last page first.
- **Add blank pages** — Insert empty pages, matching the document size by default.
- **Insert pages from another PDF** — Splice pages of a second PDF into this one.
- **Organize with page thumbnails** *(visual panel)* — Drag to reorder, rotate, duplicate or delete pages visually, then export the result.
- **Export chosen pages as new PDF** *(visual panel)* — Pick pages in the thumbnail grid and export just those.

### Compress & optimize  (5)

- **Compress PDF** — Shrink the file. Reports the before/after size and how much was saved.
- **Reduce embedded image resolution** — Resample pictures inside the PDF without touching the text.
- **Remove unused & duplicate objects** — Garbage-collect orphaned objects and merge identical resources such as repeated fonts or logos.
- **Optimise for web viewing** — Linearise the file so a browser can show page 1 before the whole document has downloaded.
- **Compare file sizes** — Show the size, page count and estimated savings for every selected PDF without changing anything.

### Edit & annotate  (9)

- **Open the visual editor** *(visual panel)* — Add text, pictures, shapes, highlights, freehand drawing, sticky notes and stamps directly on the page. Move and resize anything, undo and redo, then preview before export.
- **Add text at a position** — Place a block of text on chosen pages at exact coordinates.
- **Insert an image** — Drop a picture onto chosen pages at a position and size.
- **Draw a shape or line** — Add rectangles, ellipses, lines, arrows and more.
- **Highlight, underline or strike through text** — Find words or phrases and mark them up. Works on any PDF with a text layer.
- **Add a sticky-note comment** — Attach a pop-up comment to a position, or to every match of a search term.
- **Add a stamp** — Apply a classic rubber stamp such as APPROVED, DRAFT or PAID.
- **Freehand ink from a path** — Draw ink strokes from coordinates - the editor panel writes these for you when you draw with the mouse.
- **Remove annotations** — Delete highlights, comments, ink and stamps - all of them or just one kind.

### Layout & formatting  (12)

- **Crop pages** — Trim a fixed amount off each edge, or crop to the visible content.
- **Adjust page margins** — Add white space around the existing content, or pull it in, by scaling each page onto a new canvas.
- **Change page size** — Rescale every page onto a standard paper size.
- **Portrait / landscape** — Force pages to portrait or landscape, rotating or re-laying out as needed.
- **Add page numbers** — Stamp numbers with a choice of format, position and style.
- **Add text watermark** — Overlay or underlay repeated text with full control of opacity, rotation and colour.
- **Add image or logo watermark** — Stamp a logo or picture, with opacity, scale and rotation.
- **Add headers and footers** — Running text at the top and bottom. Use {page}, {pages}, {file} and {date} as placeholders.
- **Add page borders** — Draw a frame around each page.
- **Combine pages onto one sheet** — N-up printing: place 2, 4, 6, 8, 9 or 16 pages per sheet.
- **Split each page in half** — Cut scanned spreads into single pages.
- **Flatten annotations and form fields** — Burn annotations, highlights and filled form fields into the page so they can no longer be edited.

### Security  (8)

- **Password-protect a PDF** — Encrypt the document. The user password is needed to open it; the owner password controls permissions.
- **Remove a password** — Save an unencrypted copy. You must supply the document's own password - this does not break encryption.
- **Encrypt without an open password** — Apply owner-password encryption: anyone can open the file, but your restrictions are enforced.
- **Set printing / copying / editing limits** — Change what readers are allowed to do. Needs an owner password to be enforceable.
- **View document permissions** — Report the encryption and what the file currently allows.
- **Remove metadata** — Delete document information, and optionally XMP metadata and embedded identifiers.
- **Permanently redact content** — Black out text and remove it from the file for good. Search for words, or draw boxes in the Edit panel.
- **Redact drawn areas** *(visual panel)* — Draw rectangles over anything to delete, then export. The content underneath is destroyed, not just covered.

### Convert  (12)

- **Images to PDF** — JPG, PNG, WebP, TIFF, BMP, GIF and HEIC - one PDF with a page per image, or a separate PDF each.
- **PDF to images** — Render pages as PNG, JPG, WebP, TIFF or BMP files.
- **Extract embedded images** — Pull out the original pictures stored inside the PDF, without re-rendering them.
- **PDF to plain text** — Extract the text layer, keeping reading order.
- **Text file to PDF** — Turn .txt, .log, .csv or source files into a paginated PDF.
- **HTML file to PDF** — Render a local .html file, including its own CSS and images.
- **Markdown to PDF** — Convert .md files, with tables, code blocks and headings.
- **PDF to HTML** — Export as HTML, either with absolute positioning (looks the same) or as reflowable text.
- **PDF to SVG** — Vector export - one SVG per page, text and shapes stay sharp.
- **PDF to PDF/A (archival)** — Produce a self-contained archival PDF/A file.
- **PDF to ZIP** — Package the PDFs - or their pages, text and images - into a single ZIP archive.
- **ZIP of images or documents to PDF** — Unpack an archive and convert everything inside that can become a PDF.

### Office documents  (14)

- **Word (DOCX) to PDF** — Convert .docx/.doc to PDF.
- **Excel (XLSX) to PDF** — Convert .xlsx/.xls/.csv spreadsheets to PDF.
- **PowerPoint (PPTX) to PDF** — Convert slides to PDF.
- **ODT to PDF** — OpenDocument text to PDF.
- **ODS to PDF** — OpenDocument spreadsheet to PDF.
- **ODP to PDF** — OpenDocument presentation to PDF.
- **RTF to PDF** — Rich Text Format to PDF.
- **EPUB to PDF** — E-book to PDF, chapter by chapter.
- **PDF to Word (DOCX)** — Rebuild an editable Word document, keeping layout, tables and images.
- **PDF to Excel (XLSX)** — Detect tables and write them into a spreadsheet, one sheet per page.
- **PDF to PowerPoint (PPTX)** — One slide per page. Choose a picture-perfect image slide or an editable text slide.
- **PDF to RTF** — Rich Text output that any word processor can open.
- **PDF to CSV** — Write detected tables to CSV - one file per table, or all rows in one.
- **PDF to XML** — Structured XML with pages, blocks, lines and coordinates.

### Scan & OCR  (8)

- **Create PDF from scanned images** — Build a tidy document from photos or scans: straighten, boost contrast, drop blank pages, and optionally OCR.
- **Make a scanned PDF searchable** — Recognise the text on every page and add an invisible text layer, so the PDF becomes searchable and selectable.
- **Recognise text (copy out)** — Read printed text out of images or PDFs and save it as text you can copy.
- **Correct page orientation** — Detect upside-down or sideways pages and turn them the right way up.
- **Deskew scanned pages** — Straighten pages that were fed in crooked. Pages are re-rendered, so use this on scans, not on text documents.
- **Detect and remove blank pages** — Find near-empty pages and drop them. Run the detection first to see what would go.
- **Improve scan contrast and brightness** — Make faint photocopies readable: whiten the paper, darken the ink.
- **Scan with a camera** *(visual panel)* — Capture pages with a connected webcam or phone camera, straighten them and build a PDF.

### Forms & signatures  (11)

- **List form fields** — Show every fillable field, its type and current value.
- **Fill in form fields** *(visual panel)* — Open the document's form and type into every field, with checkboxes, dropdowns and date pickers.
- **Fill a form from a data file** — Apply values from a JSON or CSV file - handy for filling the same form many times.
- **Reset form fields** — Clear every entry so the form is blank again.
- **Flatten a completed form** — Turn the answers into permanent page content so they can no longer be changed.
- **Create fillable fields** *(visual panel)* — Draw text boxes, tick boxes, radio groups, dropdowns, date and signature fields straight onto the page.
- **Add a field by position** — Add one field at exact coordinates - useful for scripted or repeated layouts.
- **Sign a PDF** *(visual panel)* — Draw a signature with the mouse, type one in a handwriting style, or drop in a scanned signature image, then place it and add the date.
- **Insert a signature image** — Place a signature picture (PNG with transparency works best) at a chosen spot, with an optional date line.
- **Add signature and date fields** — Place empty 'sign here' and 'date' boxes for someone else to complete.
- **Export a completed form** — Save the answers as JSON or CSV, and optionally a flattened PDF copy.

### Document utilities  (13)

- **View PDF** *(visual panel)* — Open the document: scroll, zoom, fit to page, search for text, print, and save single pages.
- **Search for text** — Find a word or phrase across one or many PDFs and list every hit with its page number.
- **View document properties** — Everything about the file: pages, size, metadata, encryption, page dimensions, fonts and images.
- **Page count, size and dimensions** — A quick per-page table of dimensions, rotation, text and image counts.
- **Font and image information** — List every font and image the document uses, with sizes and whether fonts are embedded.
- **Edit title, author and subject** — Set the document information fields.
- **Add and edit bookmarks** — Replace or extend the outline. One bookmark per line - indent with two spaces for sub-levels, and end with ' @ 12' for the page number.
- **Create a table of contents page** — Build a contents page from the bookmarks - or from detected headings if there are none - and put it at the front.
- **Repair a damaged PDF** — Rebuild the file structure to recover what can be read. Tries several strategies and keeps the best result.
- **Compare two PDFs** *(visual panel)* — Side-by-side visual comparison with differences highlighted, plus a text-level diff.
- **Compare two PDFs (report)** — Generate a PDF showing both documents page by page with the changed areas highlighted.
- **Print** — Send the document to a printer using the system print dialog.
- **Download individual pages** — Save chosen pages as separate files, as PDFs or images.

### Image utilities  (10)

- **Resize images** — Scale by percentage, or fit within a width and height.
- **Compress images** — Reduce file size, optionally capping the longest edge.
- **Convert image format** — Convert between JPG, PNG, WebP, TIFF, BMP and HEIC input.
- **Crop images** — Crop by edge amounts, to a ratio, or to the image's own borders.
- **Rotate and flip images** — Rotate by any angle and mirror horizontally or vertically.
- **Convert images to greyscale** — Black-and-white conversion, with optional high-contrast document mode.
- **Adjust brightness and contrast** — Fine-tune exposure, contrast, saturation and sharpness.
- **Create passport-size photos** — Crop to an official size and lay out a printable sheet.
- **Add image borders** — Add a solid border, and optionally rounded corners or a drop shadow.
- **Generate a QR code** — Make a QR code to save as PNG, or stamp straight onto a PDF.

### Batch & workflows  (4)

- **Chain operations into a workflow** *(visual panel)* — Build a sequence such as compress, then watermark, then add page numbers - and save it to reuse later.
- **Apply one tool to many files** *(visual panel)* — Pick any tool, pick your files, and run the same settings across all of them.
- **Bundle files into a ZIP** — Collect any set of files into one archive for easy sharing.
- **Saved presets and workflows** *(visual panel)* — Review, rename and delete the presets and workflows you have saved.

---

## How it works

**Every feature is a declarative tool.** A tool is a spec — id, name, accepted
inputs, typed parameters — plus one function. The UI reads the spec and builds
the form, so the options you see, the batch runner, the workflow builder and
the preset system all come from the same definition. Adding a feature never
means writing a dialog.

```
pdfbuilder/
  registry.py        tool + parameter definitions
  job.py             execution context: output naming, progress, cancellation
  deps.py            optional-program detection with install hints
  core/              the operations, one module per category
  ui/
    toolpanel.py     the generated panel every non-visual tool uses
    widgets.py       drop-target file list, generated forms, results panel
    icons.py         the line-icon set, drawn at runtime and theme-aware
    views/           the visual panels (viewer, organiser, editor, forms,
                     signature, compare, scanner, workflow, batch, presets)
```

### Things worth knowing

- **Nothing is uploaded.** All processing is local. The app never opens a
  socket; it works with networking switched off.
- **Long jobs run on a worker thread** with a live progress bar and a Cancel
  button that actually stops the work between pages.
- **Password-protected files** are supported throughout: enter the password in
  the tool's Password box. Removing a password requires knowing it — the app
  does not attempt to break encryption.
- **Redaction really deletes.** The covered text and overlapping images are
  removed from the file, not just painted over.
- **Batch is free.** Any single-file tool can be run across a whole list of
  files with the same settings, and the results saved individually or zipped.
- **Workflows** chain tools together (compress → watermark → number → stamp)
  and can be saved and re-run on other files.
- **Presets** remember a tool's settings. Both live in `~/.config/pdf-builder`.

### Keyboard

| Key | Action |
|---|---|
| `Ctrl+O` | Add files |
| `Ctrl+K` | Search all tools |
| `Ctrl+Enter` | Run the current tool |
| `Ctrl+D` | Dark / light mode |
| `Ctrl+Tab` | Next tool in this category |
| `Ctrl+S` | Save, in the visual panels |
| `Ctrl+Z` / `Ctrl+Shift+Z` | Undo / redo in the editor and organiser |
| `Ctrl+Shift+O` | Open the output folder |
| `Delete` | Remove the selected files or page |
| `F11` | Full screen |

Results are written to `~/PDF Builder` by default; change it with the
**Save to** button on any tool.

## Tests

```bash
./tests/run.sh
```

Builds a set of sample documents (a text PDF with tables and bookmarks, a
form, a crooked scan, an encrypted file, a deliberately truncated file, images
in seven formats, Office documents, a ZIP) and then checks:

| Suite | What it proves |
|---|---|
| `smoke.py` | every one of the 107 scriptable tools runs and writes real, non-empty output |
| `deep.py` | the output is *correct* — deskew angles, permission bits, bookmark nesting, n-up order, table extraction, path-traversal refusal, and more |
| `ui_test.py` | all 120 panels build; the organiser, editor, form filler, field designer and signature pad are driven headlessly and their exports verified |
| OCR step | drives the real tesseract if installed, otherwise `tests/fakebin/tesseract`, a stand-in with the same command-line contract |

Screenshots of every panel land in `tests/_work/shots/`.

## Uninstall

```bash
./uninstall.sh
```

