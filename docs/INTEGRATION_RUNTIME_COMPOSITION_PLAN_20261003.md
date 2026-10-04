# I/L: encrypted runtime state, recovery and TEHA head coordination

Root pre-code coordination plan, 2026-10-03. Existing encrypted config store,
offline verifier/CAS and actual TEHA assistant receive plan have been read.
This plan alone does not activate a provider, change a schema or migrate data.

## Linear migration reservation

Current integrated head is k2a2b3c4d5e6. Reserve l2a2b3c4d5e6 with down_revision
k2a2b3c4d5e6 exclusively for the actual backend assistant's TEHA mapping/import
receipt domain. Its DDL-free helper product/tests arrive separately before
models/schema/migration. No independent head, generic queue or duplicate
document archive. Root owns registries, recovery/retained/startup/settings/CI.
PDF source/render preview is DDL-free and may not consume this reservation.

External identity JSON contains only necessary opaque source identifiers;
unknown source fields and private content remain protected in the established
encrypted journal. Mapping generations and immutable import receipts bind
confirmed work to actual local identities, source history hashes and original
document versions. Do not infer identity from names/addresses/emails.

## Config activation prerequisites

The global IntegrationManager currently still uses JsonFileIntegrationConfigStore.
The encrypted implementation and offline verifier are integrated but are not
the active production factory. A truthful encrypted-runtime claim requires:

1. Fullbackup/recovery verify the opaque encrypted state with explicit archive
   configuration before target publication. Missing key, invalid AES-GCM/AAD,
   malformed envelope and uncertain source fail with fixed recoverable messages.
   No runtime keyring/settings/auth fallback inside the offline verifier.
2. Explicit fenced maintenance conversion under the installation lifetime lease,
   before settings/logs/workers. A complete encrypted backup including original
   state/key/config/files is actually restored into an isolated environment
   before converting the original. Ordinary startup never converts plaintext.
3. Upgrade phase and checked return state survive process termination. Plaintext
   and encrypted envelopes are never silently confused. After conversion the
   normal factory uses EncryptedJsonIntegrationConfigStore; subsequent reads
   cannot substitute an empty state for missing/corrupt existing storage.
4. Actual config routes preserve mask semantics, authoritative file CAS,
   independent workers and unknown discovery fields, and expose a concrete
   maintenance action if a legacy state requires conversion. Initial empty
   installations use the existing stable keyring and explicit bootstrap.

The separate maintenance helper is already implemented; central installation
fencing/fullbackup/return and live factory selection are additional Root-owned
composition, not evidence supplied by the helper's isolated unit tests.

## Focused acceptance before activation

Pure verifier import blocker, actual encrypted fullcontainer roundtrip,
wrong archived key/tampered state before publication, native lifetime and
independent state writer conflict, interrupted conversion/checked return,
actual old plaintext configuration and unchanged source bytes on refusal,
actual routes with secrets masked and preserved, current production startup
regression. Synthetic data only; private provider credentials never enter
fixtures, logs or chat handoffs. Real external actions remain individually
proved and resumable; receipt outcome is explicit when a response is lost.

This prerequisite sequence does not block DDL-free TEHA source/helper work.
Its received mapping/archive/appointment workflows must be composed later with
the actual durable job and the newly proved existing backup/archive core.
