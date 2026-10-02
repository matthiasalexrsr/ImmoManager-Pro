# Explicit Windows OCR tools

This local administration command provisions the previously exercised Poppler
26.09.0 and Tesseract 5.5.3 packages into a **new**, freely chosen Windows x64
directory. It does not start the application, edit an environment file, initialize
a shell, change PATH, install a system service or modify existing tools. A
document request never downloads or installs tools.

Use the application's Python environment with its `ocr` extra installed
(`Pillow`; ReportLab and cryptography are existing application dependencies).
The command is also packaged as `immomanager-ocr-tools`; the lock JSON is included
in the wheel. This is a Python administration tool, not a newly built desktop EXE.

## Verified inputs and installation

The committed `scripts/windows_ocr_tools.lock.json` records all **52** exact
Conda-Forge packages, their versions/builds, immutable artifact URLs, SHA-256,
sizes and declared licenses. It also pins the Micromamba 2.9.0 bootstrap archive
and its executable. The default installation uses only these local artifacts;
there is no dependency solve or update to a newer release.

For an already populated package cache:

```powershell
$Python = '.\.venv\Scripts\python.exe'
& $Python -m scripts.windows_ocr_tools preflight `
  --package-cache 'D:\OCR-cache\pkgs' `
  --bootstrap-archive 'D:\OCR-cache\micromamba.tar.bz2'
& $Python -m scripts.windows_ocr_tools install `
  --package-cache 'D:\OCR-cache\pkgs' `
  --bootstrap-archive 'D:\OCR-cache\micromamba.tar.bz2' `
  --target 'D:\Meine Werkzeuge\Dokumenterkennung' `
  --staging-parent 'D:\OCR-stage'
& $Python -m scripts.windows_ocr_tools verify `
  --target 'D:\Meine Werkzeuge\Dokumenterkennung'
```

Target and staging **parent directories must already exist**. The target itself
must not exist. Cache paths may contain Unicode; the optional staging parent
must have an ASCII path and should be short. The target can contain spaces and
Unicode. With an ASCII target, staging is optional; a short staging directory is
still useful for long paths. No existing target is ever repaired, deleted or
overwritten. A failed attempt retains its own incomplete directory without a
success manifest; choose a new target for the next attempt.

Read-only `preflight` checks every archive's size and SHA-256 before any target is
created. Installation repeats these checks after copying to its own protected
cache. It uses `--offline --no-rc --no-env --always-copy --no-shortcuts
--skip-run-link-scripts` with its own root/prefix and a sanitized child environment.
The exact HTTPS cache layout avoids Micromamba's local percent-encoded file-URL
problem. No inherited database, JWT, encryption, proxy or Conda configuration is
passed to Micromamba. No shell command is constructed.

Micromamba 2.9.0's native archive reader failed in our actual Windows test with a
Unicode extraction path; its native library also encountered a long nested
package-documentation path. `--staging-parent` addresses both without restricting
the final destination. Micromamba's `--relocate-prefix` writes the final target
into prefix-sensitive text files before publication. Only newly created runtime,
bootstrap and license directories are moved, after path/type/ownership checks.
For another volume they are copied into new directories instead. No generic
Conda updater should be run on this immutable runtime; provision a new target
from a newly reviewed lock when an update is needed.

The private stage retains its own authenticated archives, extraction cache and
diagnostics, and is reported as `staging_workspace`. The runtime does not require
it after successful verification. This command never recursively deletes it;
administrators can retain it for provenance or remove exactly that new directory
after checking the completed installation and backup. Neither the supplied cache
nor its existing environments are modified.

Tesseract's native Windows language-directory enumeration additionally uses the
active ANSI code page. When the final path contains characters it cannot carry,
the setup uses Windows' existing short-name alias only after checking that it
identifies the **same final directory**. It creates no junction and does not
enable 8.3 names or change the system locale. On a volume without a usable alias,
pass `--tessdata-parent 'D:\OCR-languages'` explicitly. That existing ASCII parent
receives a **new** owner-private persistent language directory containing only the
exact hash-verified `deu` and `eng` models, their original source hashes and the
Tesseract license. `OCR_TESSDATA_PATH` then refers to that new directory while
executables remain in the freely chosen final target. The toolchain manifest
binds and verifies both locations. The language directory must remain available;
it is not a disposable stage. Existing models/parent files are never overwritten
or deleted. Other languages require separately reviewed language data when this
two-language fallback is chosen.

## Explicit reproduction from the fixed sources

When the reviewed archives are unavailable, the separate **opt-in** fetch command
downloads only the 53 fixed artifacts (52 packages plus Micromamba) to a new cache:

```powershell
& $Python -m scripts.windows_ocr_tools fetch --target 'D:\OCR-cache-2026-10'
& $Python -m scripts.windows_ocr_tools install `
  --package-cache 'D:\OCR-cache-2026-10' `
  --target 'D:\Meine Werkzeuge\Erkennung 2026-10' `
  --staging-parent 'D:\OCR-stage'
```

HTTPS certificate checks remain enabled; redirects and inherited proxies are
refused. Each file is bounded by its locked size and verified by SHA-256 before
success. No arbitrary URL, channel or executable can be supplied. There is no
`latest` endpoint, automatic fallback or downloaded script execution. If an old
artifact becomes unavailable, obtain the matching archived cache or review a new
lock; do not silently substitute packages. Fetch and install default to finite
900-second command budgets; `--timeout` accepts a positive finite value when more
time is necessary. Verification defaults to 90 seconds. These are operation
budgets and impose no application stock/annual limit.

## Positive verification and activation

The install success manifest is written **last**, after all four native version
checks, `deu`/`eng` data checks and actual recognition of a synthetic PNG and
PDF containing only a raster image. Both must recognize `161803` and
`1.234,56`, report one OCR page/zero embedded-text pages and retain the original
SHA-256. This verifies local tool execution, not accuracy for arbitrary documents.
There are no application database writes or automatic financial operations.

`ocr-toolchain.json` records source hashes, declared licenses, copied license
texts, versions, recognition hashes and hashes of all runtime files, DLLs,
language data, bootstrap files and package metadata. `verify` refuses modified,
missing or added runtime files before execution and then repeats the real native
probes. It briefly creates/removes only its own diagnostic file. The manifest is
an owner-protected local attestation, not a separately signed supply-chain proof.
Keep the original lock and artifact cache for independent reproduction.

The result contains exactly these non-secret configuration values:

```text
OCR_LANGUAGES=deu+eng
OCR_PDFINFO_PATH=<target>\env\Library\bin\pdfinfo.exe
OCR_PDFTOTEXT_PATH=<target>\env\Library\bin\pdftotext.exe
OCR_PDFTOPPM_PATH=<target>\env\Library\bin\pdftoppm.exe
OCR_TESSERACT_PATH=<target>\env\Library\bin\tesseract.exe
OCR_TESSDATA_PATH=<target>\env\share\tessdata
```

Activation is a separate administrator step after the actual installation is
accepted and a fresh full backup is verified: persist these paths in the chosen
installation's private runtime environment, then restart it. The Windows starter
already invokes `backend.__main__`, which loads that environment. Native EXEs are
not bundled by `immomanager.spec`; its Pillow hidden import alone supplies no
Poppler/Tesseract executable. This package does not alter the starter or frozen
worker dispatch and makes no claim that an EXE was built.

Full recovery preserves configured paths, but it does not package an external
tool directory. On a new host, reproduce the tools into a new target, verify
them and explicitly update those paths. Keep OCR operation budgets independent
of tool installation. PNG/PDF probes use the existing bounded native OCR runner;
setup commands themselves run in a private kill-on-close Windows job with a
default 1-GiB memory budget (`--memory-mib` accepts a larger positive value within
the native Windows SIZE_T range), finite elapsed time and 1-MiB retained diagnostics. A missing
DLL, language or resource failure produces a correctable failure rather than a
verified success marker.

## Origins and licenses

The [Micromamba explicit spec format](https://mamba.readthedocs.io/en/latest/user_guide/mamba.html#explicit-spec-files)
pins package/version/build/checksum. Its
[manual installation workflow](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html)
supports a separate local prefix without a base Python environment.
[Poppler's package](https://github.com/conda-forge/poppler-feedstock) is
GPL-2.0-or-later; [Tesseract's package](https://github.com/conda-forge/tesseract-feedstock)
is Apache-2.0. Feedstock repository licenses are distinct from package licenses.

The dependency bundle is not entirely open source: UCRT and Visual C++ runtime
packages declare Microsoft runtime licenses. Preserve those terms and the other
declared dependency licenses when redistributing. The setup retains all 60
license files supplied by the 52 packages plus Micromamba's bundled license
files; `libfreetype`, `libfreetype6` and the `vc` metapackage provide only license
metadata in these particular artifacts, explicitly marked in the inventory.
No missing license text is invented or replaced with the application's MIT
license. This is a provenance inventory, not a legal compatibility opinion.

Actual local acceptance on 2026-10-02: offline installation and re-verification
in a new ASCII path with spaces; a separate ASCII-stage installation into a new
Unicode target; all four versions and actual `deu+eng` PNG/raster-PDF recognition
with unchanged original hashes. The existing application, private environment,
preview, initial test toolchain and user databases were not changed.
An additional actual Japanese-path probe verified the existing short-name alias;
a separately installed Japanese target passed real native recognition with
`--tessdata-parent` while unavailability of 8.3 aliases was explicitly simulated
without changing OS settings. The opt-in fetch also downloaded and authenticated
all 53 fixed artifacts into a new private Unicode cache before offline reuse.
