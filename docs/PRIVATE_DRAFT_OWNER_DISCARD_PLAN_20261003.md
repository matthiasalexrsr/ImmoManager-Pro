# C/B: owner-only discard after complete draft grant revocation

Pre-code focused correction, Root79ea761, 2026-10-03. The actual draft policy
validates role/nonempty portfolios before all actions, including owner-only
discard. Existing changed-scope evidence retains another portfolio and a write
role; it therefore does not prove the accepted owner-discard promise after
complete portfolio removal or a readonly role change.

Keep fresh active authentication and exact owner identity. Only explicit CAS
discard may skip the target domain's write/nonempty-portfolio prerequisite.
It addresses the current account's own ciphertext key, does not decrypt/read
the old private resource, and cannot modify journal/business data. Read/write
retain their current checks. The account-management lock and fresh principal
check continue before and after deletion. No middleware permission exception
is needed: the existing own-draft route already delegates target checks here.

Actual Memory/SQLite/PostgreSQL HTTP proof: create own draft under a valid
portfolio, revoke all portfolios or change to readonly, deny restore/overwrite,
deny another account's discard, reject stale draft CAS, then allow only the
owner's explicit current-CAS discard. Source is the same common core for
ordinary and journal forms. No preview restore after revocation, no encrypted
content exposure, no schema change. Heavy execution waits for the PDF slot.

## Pending expiry correction before code

An additional source check found unconditional expiry deletes a pending
unknown-outcome command after the ordinary draft lifetime. Keep ordinary
editing expiry; defer automatic deletion for an authenticated pending payload
until explicit outcome/cleanup. Inspect only the protected pending flag
internally; restoration still requires unchanged current grants and references.
Damaged ciphertext/missing key cannot be silently interpreted as an expired
empty draft. The read response may indicate expiry_deferred without changing
any input JSON, UUID or expected business revision.

Explicit owner CAS discard must run before the expiry branch, with no
decryption dependency. Even an expired draft and missing old key can therefore
be deliberately discarded by its fresh owner, while a stale CAS cannot delete
it. Add actual pending expiry/replay and malformed expiry negative checks and
retain the existing ordinary-expiry regression. No new persistence fields.
