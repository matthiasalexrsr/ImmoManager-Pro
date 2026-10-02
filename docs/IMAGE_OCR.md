# Bounded local image OCR

PNG, JPEG, TIFF, BMP and WebP use the same native worker limits as scanned PDFs.
Pillow header inspection and RGB/PNG normalization execute outside the API
process. The original bytes are retained unchanged. Each TIFF frame is read
and recognized in order; the page setting `OCR_MAX_PDF_PAGES` also caps image
frames. Pixel budgets apply per frame and across all frames. A conservative
32 bytes per pixel preflight accounts for decoding, conversion and OCR buffers;
the worker's actual memory is also observed/enforced by the shared runner.

There is one deadline for metadata inspection, normalization, language probing
and all Tesseract calls. Worker diagnostics, text, temporary output and process
tree cleanup use the PDF runner contract, including its documented sampled
Linux memory/disk limits. No cost, invoice, booking or payment is created by
extraction. Recognition remains a draft for manual review.

The configured `OCR_TESSERACT_PATH`, `OCR_TESSDATA_PATH` and `OCR_LANGUAGES` apply
to standalone images too. Poppler is needed for PDFs, not standalone images.
Install the Pillow extra with `pip install '.[ocr]'`; missing Pillow produces
`ocr_image_dependency_missing`/503 rather than silently skipping the image.
No new budget/settings fields are introduced. The frozen launcher dispatches
`--ocr-image-worker` before private configuration, startup logs or application
startup. Packaging collects Pillow's lazy image-format plugins. A native
dispatcher test does not claim a newly built executable was tested.

## Private deployment and recovery

`OCR_TESSDATA_PATH` is an explicit application setting alongside the tool paths.
All fourteen OCR keys are persistent desktop defaults, private-server Compose
values and permitted private-backup configuration. Optional blank paths remain
valid; malformed language specifications and numeric budgets fail configuration
validation. Full SQLite recovery preserves these declared settings through its
Settings-based allowlist, while excluding unrelated shell variables. An actual
source-gone test verifies private OCR settings load before config/app import and
override unrelated ambient OCR values after restoration. This backs up paths
and budgets, not external native binaries or traineddata files.

Page/pixel/byte budgets are positive integers and the shared operation timeout
is positive and finite. Safe defaults remain, while administrators can choose
larger budgets without fixed product ceilings. These settings grant resources
per operation; they do not limit the number of documents or years stored. Actual
input/pixel preflight, native allocation failures and operation timeouts remain
recoverable. Windows uses a native `SIZE_T` job-memory limit; an unrepresentable
RAM setting is rejected before tool startup rather than silently truncated.

The private production image installs Poppler/Tesseract plus `deu`/`eng` and
Pillow. `scripts/ocr_native_gate.py` is the required Linux CI entry: tool versions
and language presence are checked before tests, real PDF/image extraction and
POSIX cleanup run for Memory and SQLite, and JUnit skips cause failure. Only the
two Windows batch-wrapper cases are explicitly deselected on Linux; the native
thread-child/RSS and detached-pipe cleanup cases must execute. Toolchain and
JUnit reports are retained. The preexisting backend and independent PostgreSQL
gates remain separate requirements.

`POST /documents/import` returns 201 and the existing Document fields when the
original upload and metadata succeeded. It adds **response-only** fields:

- `ocr_status`: `completed`, `empty`, `failed` or `unsupported`;
- `ocr_error`: null or `{code, message}`;
- `ocr_url`: null or the extracted-text URL.

These fields report this attempt, not a new persisted document state. Correctable
OCR failure does not roll back the successfully retained original or masquerade
as a document 500. Upload size/type failures still reject the upload. A separate
`POST /documents/ocr-analyze` returns the typed `{error: {code, message}}` and
original 422/503/504 OCR status. Scope/auth failures keep the common handlers.

The Documents page preserves successful upload state and shows the actual
failure message, code, status when available, and a translated correction path.
Retry acts only on the already stored original. Metadata is saved only through
the explicit document form; neither upload nor retry creates a financial record.

## Actual validation

Windows isolated tools: Tesseract 5.5.3 with explicit `deu+eng` tessdata in
`work/OCR-tool-validation`; no global install, PATH or private environment change.
Native PNG/JPEG/TIFF/BMP/WebP gates recognize synthetic `271828` and `1.234,56`,
including both TIFF frames, and retain each original SHA-256. Native header,
missing dependency and frozen-dispatch gates also run. Memory and SQLite HTTP
cases preserve downloadable original bytes and document IDs after missing-tool,
pixel-budget and timeout failures; typed errors remain recoverable.
## Rendering resolution

`OCR_RENDER_DPI` is a positive integer with no product ceiling. An explicitly
higher resolution uses the same per-operation pixel, RAM, disk and time budgets.
Pixel preflight uses exact arithmetic so extreme settings produce the corrective
pixel-budget error before rendering, rather than a floating-point overflow.
