# I: actual authenticated HTTP and fresh full recovered runtime

2026-10-03. Root plan `cdb0ee2`, tests `49ce533`, focused route correction
`7b97cb6`. No real mail, portal action, preview upgrade or private conversion.
All datasets, keys and users were synthetic and all SQL/temp paths owned.

## Actual SQL-authenticated HTTP

The first one-case native gate found a product composition gap: 1 FAIL,
10.23 seconds / 13.12 outer. Real owner/member login, masked GET, actual cipher
CAS success and stale412 were reached, but the actual global HTTPException
handler converted the structured domain detail into an INTERNAL_ERROR string.
The isolated fake-auth test had not proved this actual app behavior.

`7b97cb6` returns the fixed safe ConfigStoreError envelope directly from the
existing route class: canonical `error` with code/message/request_id and fixed
`detail` for documented /api/v1 compatibility. 412 retains the actual reload
instruction; other configuration failures retain actionable503. Private/no-store
and Vary:Authorization survive the actual app. No unrelated global exception
semantics or success authorization were changed.

Exact SQL case repeated on `7b97cb6`: **1 PASS / 16.55 seconds**, **19.86 outer**,
hard150 seconds, no skips. Real SQL users and actual HTTP login, normal app and
portfolio middleware, actual encrypted factory/temporary file and sidecar CAS.
Passwords stayed masked; unknown fields survived decrypt/reopen. The stale
write and the selected member's normal403 GET/PATCH left ciphertext byte-equal.
After deleting only its owned temporary state, native GET/PATCH/run returned
safe503 without creating replacement state, altering any actual journal-table
count or reaching the provider tripwire. TestClient/session/engine closed.

## Actual encrypted full recovery and global factory reopen

Source `7b97cb6`, only the existing explicitly encrypted full-roundtrip case:
**1 PASS / 21.56 seconds**, **22.95 outer**, hard210 seconds; seed child90 and
fresh recovered-app child30 seconds. No skips, mocks of auth/responses, external
actions or persistent test server. The legacy fixture remains unchanged for
other cases; its conversion occurs only in this explicitly encrypted case.

An actual encrypted full archive restored into a new owned directory. The
configured runtime factory reopened exact archived keys/content after JWT
signer rotation; source DB/state stayed byte-equal. A fresh child deliberately
received wrong ambient DATA_DIR/DB/JWT values, loaded only the actual recovered
configuration, started the actual app, logged in through its normal endpoint
and read a masked actual connection-state response from the global manager.
The same child checked actual secret-dependent account decryption, receipt/
reversal/bank allocation, billing period, uploaded original bytes and unknown
private nested fields. Restored ciphertext stayed byte-equal, no first-init
permission was used, wrong ambient data directory was never created. Children
and actual TestClients closed normally. Private child failure output is withheld
by the test rather than exposing configuration diagnostics.

These are two actual composed cases, not the entire I/L/shared release gate.
PostgreSQL/private Docker full backup, operational scheduling and legacy startup
remain separate requirements. The old Release126 preview is unchanged.
