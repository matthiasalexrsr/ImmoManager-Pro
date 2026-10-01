# Private installation files

Uploads and authenticated file downloads use the same configured `UPLOADS_DIR`.
When unset, this is the installation's `DATA_DIR/uploads`; source runs without a
custom data directory keep their historical project-root uploads folder.

`/uploads` requires a valid active account even for static resources. Approved
readonly accounts can read installation files under the existing private access
model. Responses disable caching and active content. The SPA serves files only
inside its resolved frontend directory and rejects Windows paths, parent escapes
and links to files outside that directory.

The document viewer and photo gallery fetch `/api/v1/files/download?key=...`
through the authenticated API, including token refresh. Credentials never appear
in a file URL and are never sent to an external file host. Local references and
S3 keys are normalized into installation storage keys. Closing or changing a
viewer aborts pending requests and releases its Blob URL; old OCR results and
photos cannot carry over to a different file or unit.

Only PNG, JPEG, GIF, WebP and PDF files with matching byte signatures are
previewed with fixed MIME types. Verified PDFs use the browser's native viewer;
iframe sandboxing disables that native plug-in. HTML, SVG, XML, unknown formats
and files whose contents do not match their extension are octet-stream downloads
only. An invalid PDF produces a readable message while retaining its download.

## Existing custom-data-dir installations

An older version saved uploads in `uploads` under its process working directory,
even when a different data directory was selected. Existing files in that legacy
folder are preserved. No folder is searched, moved or served automatically.

If a document now reports that its file is missing, stop the server and identify
the actual folder containing its stored relative key, for example
`documents/abc.pdf`. Preserve the database, the legacy uploads folder and any
already-configured uploads before recovery. Create a full installation backup
with the full-backup command's `--uploads` option set explicitly to the legacy
folder containing those bytes. Restore that archive offline into a new empty
data directory, then use the restored uploads folder and verify document/photo
downloads. Keep the original database and folders until verification succeeds.

Alternatively, an installation administrator may explicitly configure
`UPLOADS_DIR` to the absolute legacy folder for that installation and restart.
The same chosen folder is then used for uploads, protected downloads and the
static mount. Choose and back up that folder deliberately; the server has no
fallback that serves another directory when a file is absent.
