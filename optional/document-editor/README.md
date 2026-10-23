# Local DOCX editor

This component is isolated from the default frontend dependency tree. It uses
SuperDoc **2.23.0**, pinned in `package-lock.json`; the package is AGPL-3.0 and
also offers a commercial license. Building it does not grant a distribution
license or change the main application's license. Resolve the applicable terms
before shipping the combined product.

From this directory, run `npm ci --no-audit --no-fund` and `npm run build`.
Then build the main frontend from `frontend` using `npm run build`. Include the
entire generated `document-editor` directory in the frontend distribution,
including `assets` (the local document and review workers), dynamic chunks,
`editor.js`, and `editor.css`. Copying only the entry point is insufficient.
The generated directory is ignored by Git and is reproducible from the lock.

The adapter uses the **v2** `ui.toolbar` contract, keeps native DOCX export, embeds
PNG/JPEG image bytes locally, and disables telemetry. No account, CDN, or cloud
conversion is used. The application retains authorization, revisions, private
recovery drafts, conflict checks, and immutable original storage.

Primary documentation checked 2026-10-16:

- https://docs.superdoc.dev/editor/built-in-ui/configure-the-toolbar/
- https://docs.superdoc.dev/editor/export-options/
- https://docs.superdoc.dev/resources/license/

Use `scripts/run_document_browser_qa.py` with the local Playwright module after
both builds for the owned synthetic browser gate. Native OOXML preservation
must also be checked after export. Complex Word features require visual
comparison in an independent Office application; passing a package validator
does not establish identical pagination or support for every Word feature.
