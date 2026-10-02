# Local scanned-PDF extraction

The PDF path reads embedded UTF-8 text page by page with Poppler `pdftotext`.
Only pages with no extracted text are rendered with `pdftoppm` and passed to
Tesseract. Mixed documents retain embedded text in its original page order.
Pages with a text header and a scanned body are not automatically treated as
blank pages. The original upload is unchanged; extracted text is a sidecar.
The billing OCR endpoint returns a reviewable cost draft and creates no cost,
booking or payment. OCR text and proposed amounts must be checked against the
original. Existing regex confidence is not a measured Tesseract confidence.

## Local prerequisites and configuration

Install actual Poppler `pdfinfo`, `pdftotext`, `pdftoppm` and Tesseract, including
the requested language data (default `deu+eng`). Use executable files on PATH or
`OCR_PDFINFO_PATH`, `OCR_PDFTOTEXT_PATH`, `OCR_PDFTOPPM_PATH`,
`OCR_TESSERACT_PATH`. DLLs and language files must remain available alongside
the chosen binaries. A Python wrapper alone does not provide these tools.
No tool is fetched or installed by a document request.

`OCR_TESSDATA_PATH` passes an explicit `--tessdata-dir` to both the language
probe and extraction through `OCRLimits.tessdata_path`. With its default blank
value, the native executable's usual language directory or inherited
`TESSDATA_PREFIX` applies. An explicit missing directory
or requested language produces `ocr_language_missing` (503).
Paths with spaces/metacharacters are single arguments; no shell is invoked.
Windows `.cmd`/`.bat` wrappers are rejected even when found via PATH, because
Windows can implicitly run them through `cmd.exe` with `shell=False`.

Official references: [Tesseract installation and language data](https://tesseract-ocr.github.io/tessdoc/Installation.html),
[Poppler Windows distribution](https://github.com/oschwartz10612/poppler-windows),
[conda-forge Poppler package](https://github.com/conda-forge/poppler-feedstock),
[conda-forge Tesseract package](https://github.com/conda-forge/tesseract-feedstock).
An isolated test environment can be provisioned with the project's documented
[Micromamba manual Windows workflow](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html),
an explicit root/prefix under a work directory, `--no-rc`, and conda-forge. Do not
initialize a shell, change global PATH, or invoke a machine-wide installer.
For the conda-forge Windows layout, explicitly select `<prefix>/share/tessdata`;
otherwise the executable can search the working directory instead.
For a reproducible private Windows installation using the reviewed exact package
lock and a real PNG/raster-PDF acceptance probe, use the explicit administration
workflow in [WINDOWS_OCR_TOOLS.md](WINDOWS_OCR_TOOLS.md). It does not activate tools
or change an existing installation.

## Budgets and cancellation

Settings bound pages, render DPI, per-page/total pixels, retained text, temporary
files, estimated working memory and elapsed time. Input and raster preflight
checks run before rendering. The native runner observes temporary files and
worker memory while tools are running, not just after completion. Diagnostic
stdout and stderr each retain at most 256 KiB; overflow terminates the worker
with `ocr_tool_output_budget`. Executable/startup errors return a correctable
`ocr_tool_unavailable` (503), rather than an unhandled OS exception.

Windows starts the tool suspended, attaches it to a private kill-on-close job,
then resumes it. The job bounds aggregate committed memory and owns launcher
children. Every success/failure closes the job and joins the process/readers.
See Microsoft's [job memory and kill-on-close limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information).
POSIX uses a new process group and terminates the entire group on completion or
failure; Linux also samples resident memory including descendants created by
every thread via `/proc`. Observed Linux children retain PID handles for safe
termination even if they detach into another session; diagnostic pipes use
nonblocking selectors so cleanup does not wait indefinitely on a remaining
writer. This is still a trusted-tool contract, not containment of hostile
launchers that deliberately escape before they can be observed.
Other POSIX platforms retain input/pixel checks but do not have Linux `/proc`
monitoring. They have not been validated in this package.

The file and Linux resident-memory checks sample at 10 ms and can briefly
overshoot their configured thresholds. They are not an OS filesystem quota or
an arbitrary-code sandbox. Deployments needing hard Linux memory/disk isolation
should run trusted native tools inside the deployment's resource-limited worker
or container. PDF processing uses a private temporary directory removed after
success, budget rejection, timeout and tool failure. Structured error codes
explain missing tools/languages or budgets; no financial mutation follows a
failed extraction. Standalone images now use the same bounded native runner;
see [IMAGE_OCR.md](IMAGE_OCR.md) for image headers, normalization and upload
failure semantics.

## Actual tool validation

On 2026-10-02 the independent Windows gate used Poppler 26.09.0 and Tesseract
5.5.3 with `deu+eng`, provisioned only in `work/OCR-tool-validation`.
Bundled runtime inspection found `pdfinfo`/`pdftoppm` but no `pdftotext` or
Tesseract on PATH. A ReportLab PDF containing only a synthetic bitmap was
visually rendered and checked. `pdftotext` emitted only its page separator;
the service reported one OCR page and no embedded-text page, recognized
`SYNTHETIC OCR 314159` and `Gesamtbetrag: 1.234,56`, and retained the original
SHA-256. The cost-review endpoint proposed 1234.56 and made zero financial writes.
Printed `RE-9988` was recognized as `RE-9983`; this is direct evidence that manual
review is necessary, not a claim of OCR accuracy.

The optional real-tool regression uses ReportLab's bundled Vera font, so it
does not skip Linux merely because a Windows Arial file is unavailable. Tests
also execute real child processes for pipe overflow, growing output files,
RAM allocation, timeout, launcher/descendant cleanup, pipe-setup failures and
unavailable executables.
Windows native execution was verified locally; Linux-native execution belongs
to the Linux CI gate and is not claimed by a Windows test run.
