# Daily integration, 16 October 2026

This supplements the historical `PRO_PACKAGE_DAILY_20261016.md` handoff. The current integration includes later daily work from the full candidate: session families, contract number reservations, document and cost defaults, bank import profiles, preferred connections and a 10,037-item keyset inbox. No original worktree, installed application or port 8000/8765 was changed. No email was sent to an external account; all delivery checks use synthetic local transports.

## Completed integration work

- Personal notification email now prepares a real immutable MIME preview in the existing encrypted communication outbox/evidence tables. `POST /notifications/{id}/email-preview` uses the authenticated account's current email address and a chosen existing email connection. There is no arbitrary recipient field and no automatic preview creation on a preference update.
- The existing confirmation command explicitly releases the exact MIME hash. The existing worker handles the private `notification` kind and rechecks the current notification/source revision, current recipient address, current source rights, personal read receipt, email preference and Europe/Berlin quiet hours at release, claim and immediately before DATA. Business correspondence keeps its existing policy.
- Private notification items use an owner-filtered outbox page and cannot appear in the shared business outbox. Immutable evidence, leases, DATA ambiguity and explicit retry retain the existing communication behavior. A preview or accepted email does not acknowledge the in-app notification.
- The full personal inbox offers connection selection, actual subject/body/recipient preview, explicit release, status recovery and explicit retry after a known failure. Lost preview/release answers keep the same command in the private tab buffer. A rejected source preview can be discarded and recreated against the current source. Unknown DATA results do not offer an automatic resend.
- Memory session revoke now holds the auth revocation lock across mutation and rollback; inventory snapshots use that lock too. An auth reader cannot reject a token solely because it observed a session mutation which later rolled back.
- Settings audit appends now use the journal lock. The coordinator also made memory archive read units hold the account and archive locks; an added interleaving regression checks that a preference reader sees the old committed value after a failed write.
- Settings search supports multiple words, accent-insensitive German text and scope names. Currency and inbox labels were repaired. Reset works even with an unfinished invalid input. A late successful save from an unmounted card cannot erase a newer same-setting draft after remount.
- The shared connection page's cursor-owner argument was renamed internally so an actual `actor_id` row filter no longer collides with the function argument. This repairs existing private draft listing as well as the new private notification page.
- Bank profile consumption in the bank import UI belongs to the coordinator. The existing hook returns the exact staging format and CSV options; it changes defaults for a new import only.

## Operational boundaries

Only a user-confirmed `ready` row is picked up by the existing communication worker. Quiet hours or revoked rights conservatively block delivery; this work does not create an automatic delayed-send schedule. A known failed/blocked item requires explicit retry after review. An ambiguous DATA result retains the existing manual reconciliation contract. An SMTP acceptance proves server acceptance, not mailbox delivery.

Legacy tokens without session-family identifiers retain their old expiry/revocation contract and receive no invented inventory entries. Currency display chooses symbol or ISO code for the actual source currency; the older currency preference remains read-only and does not relabel historical financial data.

Native PostgreSQL concurrency/upgrade gates, browser screenshot/focus evidence and whole-product release validation remain coordinator work. Focused tests and their isolated runtime directories are recorded in the final handoff; no production-readiness claim follows from these tests alone.
