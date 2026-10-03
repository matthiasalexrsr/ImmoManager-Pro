# I: explicit encrypted runtime factory and fresh bootstrap contract

Pre-code plan, 2026-10-03. Clean isolated source `d2c2cbd`, checkout
`work/encrypted-runtime-factory`, branch `assist/encrypted-runtime-factory`.
Root's fenced maintenance has 33 distinct actual native passing cases; this
packet changes the normal manager's still-legacy store construction. It does
not claim overall I/A–L acceptance or convert any private installation.

## Chosen Root contract and exact APIs

New import-pure module `backend/services/integrations/runtime_factory.py`:

```python
configured_runtime_store(explicit_configuration: Mapping) -> IntegrationConfigStore
initialize_new(explicit_configuration: Mapping, *, expected_missing=True)
runtime_state_instruction(code: str) -> str
```

Normal construction performs no state load, initialize, migration, key generation,
provider call, network access, Settings construction or ambient key lookup.
Without a configured state path it returns the existing memory store with the
chosen payload/depth budgets. With a path it returns the existing encrypted
store using an immutable snapshot of explicit field-key configuration. Keyring
validation is deferred to actual store work, so missing/invalid integration keys
or files do not abort unrelated application modules during global registration.
The cipher uses the existing stable field-keyring implementation; no second
encryption format or persistence service is introduced.

Actual load/config/provider actions authenticate the entire selected encrypted
file. Missing, plaintext, malformed, tampered or wrong-key state raises the
existing fixed ConfigStoreError code. No such error becomes an empty legacy
dictionary or default configuration, and no provider action runs after a failed
state read. The factory never calls migrate_legacy_plaintext.

Global manager construction passes `settings.model_dump(mode="json")` to this
factory and registers defaults with `seed_defaults(load_state=False)`. Existing
direct callers retain `IntegrationManager()` and `seed_defaults()` behavior;
the latter defaults to loading as before. Remove the end-module JsonFileStore
initialize call. Registering defaults performs no state I/O.

`initialize_new` is a separate explicit first-initialization operation. Root must
call it only for the explicit launcher `--initialize-integrations` flag, inside
the actual ManagedRuntime installation lifetime lease and before app import,
after stable selected-installation field keys have been durably configured.
The normal factory and ordinary restarts never grant this permission. No marker,
PID, table count or file timestamp is used to guess a fresh installation.

`expected_missing` must be the literal boolean True; False/nonbool fails before
state work. A persistent configured path and active explicit field key are
required before initialization. Reuse the actual encrypted-store `initialize`
sidecar/atomic-publication implementation. An absent file gets an encrypted
empty initial state. A concurrently/already present valid encrypted file is
authenticated as an idempotent no-op, preserving byte identity and every unknown
field. Existing plaintext or damaged/wrong-key content is never replaced.
Return the validated encrypted store, without secret data or an invented
created-versus-existing result that was not observed under the sidecar lock.

## Three actual settings and capacity contract

Add exactly these settings and their numeric type validator:

- `integration_state_payload_bytes`: positive integer, default 1 MiB.
- `integration_state_json_depth`: positive integer, default 64.
- `integration_state_lock_timeout_seconds`: positive finite number, default 5 s.

No maximum ceilings, booleans, fractional integer budgets, NaN or infinities.
Normal Settings environment parsing retains numeric-string compatibility;
explicit archived string configuration passed directly to the factory is also
supported. Map them to the existing encrypted store's max_plaintext_bytes,
max_json_depth and lock_timeout. Default capacities stay unchanged. No startup,
auth, schema, registry, CI, UI, manager business action or provider refactor.

## Maintenance, recovery and activation boundary

An existing plaintext file requires the already proved explicit offline command;
the read-only help instruction is
`python -m backend.integration_state_upgrade convert --help`. Operators stop
application/background writers, choose the actual existing installation and
create a new encrypted complete backup through that CLI. There is no browser
approval, automatic migration, empty fallback or plaintext shadow backup.

The ordinary encrypted global factory is the code switch in manager.py; no
legacy opt-out is added. Root owns actionable HTTP error mapping and the explicit
launcher/runner bootstrap composition. Existing deployments need the maintenance
path and stable keys before their integration reads work; unrelated modules can
remain available while integration reads refuse. A missing existing file needs
full recovery rather than an ordinary restart silently creating an empty file.

Root's existing complete-container proof retains encrypted integration bytes and
archived field keys while rotating JWT/session signing state. The new factory
must read the restored encrypted file with that explicit archived configuration.
A restored legacy container is still legacy and requires explicit maintenance
before integration reads; a checked state-only return to plaintext similarly
causes a deliberate maintenance requirement, not empty-data recovery.

Runtime payload and archive resource profiles are separate explicit budgets:
large runtime state also needs a backup metadata/file profile sufficient for the
encrypted envelope. New settings are included by existing complete-configuration
serialization/validation automatically; do not change container code here.

## Focused gates, source ownership and unresolved composition

Own pure tests run with plugin autoload disabled and `--noconftest`; they import
the factory and ExplicitSettings, not app/config/dependencies/manager/providers.
Tripwires refuse SQL, network, ambient keyring and key generation. Cover normal
construction with no state I/O, missing/legacy/damaged/wrong-key load refusal,
explicit-only fresh encrypted initialization, exact encrypted no-op, unknown
field preservation, signer rotation, immutable key snapshot, memory construction,
positive adjustable budgets and actual payload/depth refusal without truncation.
Fresh initialization in these tests is lower-level unit evidence; it does not
claim a real launcher lifetime fence. Native independent sidecar waits, cold
startup/auth/SQL/PG, global registration and actual complete backup/restore with
the new factory require coordinated later slots and honest separate counts.

Only allowed product sources: manager.py, runtime_factory.py and the three
Settings fields/type validator. Own tests and this plan/handoff are separate.
Root alone edits launcher/runner/startup, routers/error mapping and fixture
composition, and integrates commits. No Root/Main/Preview file edits/cherry-picks,
uncommitted Root copying, private data, DB/schema action or heavy gate in this
planning/pure-test packet. First commit this exact plan, then implement.
