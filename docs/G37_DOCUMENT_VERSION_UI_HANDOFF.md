# G37.1 document version history UI

The independent component is `frontend/src/components/DocumentVersionHistory.jsx`.
Root owns the small hook in Documents.jsx and the integrated browser gate:

```jsx
<DocumentVersionHistory
  document={selectedDocument}
  onClose={() => setSelectedDocument(null)}
  onViewOriginal={openExistingOriginalViewer}
/>
```

Use a separate document-ID-bound table action with `type="button"` and
`stopPropagation()`, translated by `pages.documents.versions.openHistory`.
The callback is optional and receives the unchanged Document object. Keep the
existing original viewer route unchanged. The history dialog handles archived
downloads itself; version URLs must not be passed through the legacy
`/files/download?key=...` converter. It does not query live OCR for historical bytes.

The UI provides original hash review and explicit archive confirmation, uploads,
append-only restoration, comments, actor/reference/hash evidence, keyset paging,
and comparison of stored hashes and metadata. The comparison does not claim text,
visual, or legal equivalence. Readonly users can read/download; write actions use
fresh `useWriteAccess('/documents')` checks before and after confirmation.

Failed or malformed command responses preserve selected file/comment and the
idempotency reference. Repeat is an explicit confirmed user action. All close
paths and duplicate submissions are blocked while a command is pending; owned
requests abort on unmount and opener focus is restored. Changing actor/document
unmounts the private unfinished choices. Rights/ownership failures clear cached
history. A download uses a constructed authenticated endpoint, validates size and
SHA256 before creating its object URL, and cleans up that URL.

Only the new component, scoped CSS, focused tests, and additive
`pages.documents.versions` DE/EN/ES keys are included. Documents.jsx, shared
FileViewer, useProtectedFile, global styles, API transport, and dependencies are
unchanged.

Verification on the isolated branch: 20 focused UI cases, 749 complete frontend
cases across 60 files, ESLint and the production build passed. The standard build
will include the component once Root adds its Documents.jsx import. An actual
integrated browser flow remains Root's follow-up; no browser result is claimed by
this separate UI commit.
