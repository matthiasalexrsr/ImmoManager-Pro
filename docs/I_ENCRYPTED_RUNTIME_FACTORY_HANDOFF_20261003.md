# I: encrypted runtime factory handoff

2026-10-03. Isolated checkout `work/encrypted-runtime-factory`, branch
`assist/encrypted-runtime-factory`, clean base `d2c2cbd`. Plans `2567b2f` and
`bf0dec0`; frozen product and own pure test source `f64351d`.

## Exact composition API

`backend.services.integrations.runtime_factory.configured_runtime_store(configuration)`
accepts the explicit selected Settings `model_dump(mode="json")` or archived
string configuration; field names are case insensitive and ambiguous duplicate
names are refused. It constructs without reading/creating/initializing state.
A missing configured path selects the existing memory store for compatible
direct/test construction. A configured path selects a cached, thread-safe
delegation to the existing `EncryptedJsonIntegrationConfigStore`. Even file-store
construction/path normalization is deferred until an actual operation. The
delegation forwards load/save/update/revision/CAS to the existing implementation.

The snapshot includes only explicit durable field-key configuration:
`encryption_key`, `encryption_keyring`, `encryption_active_key_id`,
`encryption_index_key`, `encryption_legacy_jwt_keys`. It is detached from caller
mutation and passed as a non-None mapping. Ambient configuration and the current
JWT signer are never fallback keys. No new key is generated. Missing, plaintext,
damaged or wrong-key file state remains an error at actual use, never empty state.

`initialize_new(configuration, *, expected_missing=True)` is separate. Only
literal boolean True is accepted. It requires a persistent path and a valid
active explicit field key before invoking the existing actual store's
`initialize`. Missing state is encrypted; existing valid encrypted state is an
authenticated exact-byte no-op. Plaintext, damaged and wrong-key originals are
refused without replacement. The returned object is the actual encrypted store.
Root must call this only for the explicit `--initialize-integrations` launcher
flag while the actual installation ManagedRuntime lifetime lease is held and
before app import. The factory cannot establish that lease itself and never
grants ordinary starts initialization permission.

`runtime_state_instruction(code)` returns only fixed safe actions. Revision
conflict requires loading the current state and reviewing the intended changes.
`state_io_failed` and `lock_close_failed` explicitly describe uncertain
publication and require checking the current state/full backup before retry.
Unknown codes receive a fixed generic instruction and are not echoed. Paths,
keys, exception messages and configuration values are not interpolated. The
legacy maintenance instruction is the read-only help command
`python -m backend.integration_state_upgrade convert --help`.

The global manager now constructs this store from its selected Settings and
uses `seed_defaults(load_state=False)`. Existing `IntegrationManager()` and
`seed_defaults()` callers retain memory construction and default state-load
behavior. Existing actual provider actions still read/authenticate the store
before execution. No launcher, router, auth, schema, registry, UI, backup or
maintenance service source was edited in this packet.

## Capacity and compatibility

The only new Settings fields are positive `integration_state_payload_bytes`
(default 1 MiB), positive integer `integration_state_json_depth` (64), and
positive finite `integration_state_lock_timeout_seconds` (5 seconds). There are
no artificial upper ceilings. Booleans/fractional integer limits/nonpositive
values/NaN/infinity are refused. Numeric strings remain compatible with explicit
archived configuration and Settings parsing. Tests exercise a 17 MiB selected
budget, depth 128 and wait 120, an actual state larger than the default 1 MiB,
and an actual nested state deeper than the default 64 without truncation.

An existing plaintext installation needs the already prepared explicit offline
maintenance conversion and its stable field keys before integration reads work.
A restored legacy full container, or a checked return to plaintext, deliberately
requires that maintenance path again. A missing existing file requires complete
recovery; normal restart does not fabricate an empty file. Unrelated modules can
register providers while integration state is unavailable. Runtime and full
archive resource profiles remain separate selected budgets.

## Actual completed evidence

On unchanged frozen source `f64351d`:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'C:/Users/matth/Documents/Codex/2026-10-01/wi/outputs/ImmoManager-Pro/.venv/Scripts/python.exe' -m pytest --noconftest backend/tests/test_integration_runtime_factory_pure.py -q
```

Actual result: **48 passed in 1.50 seconds**, zero skips/failures; normal process
exit 0, no remaining execution handle. Ruff and Mypy passed on all four scoped
Python files. The initial static check found four own test typing errors; these
were corrected before the first actual test run. No failed product run is being
reclassified as passed.

These synthetic file tests cover no-I/O construction, deferred path errors,
memory compatibility/CAS, missing-state read/write refusal, exact plaintext
preservation, explicit encrypted creation and reopen, exact encrypted no-op,
explicit permission/key refusal, malformed/wrong-key/tampered/unknown-format
refusal, detached explicit keys/JWT rotation, stale CAS refusal with retained
secrets/unknown fields, concurrent first-use delegation, adjustable budgets and
safe instructions. Every case checks that app/config/dependencies/database
session/manager/providers/huggingface/history_store modules remain unimported.
Tripwires refuse SQLite, network connections, subprocess creation, ambient key
lookup and key generation. Only temporary synthetic state and fixed synthetic
keys are used.

The file tests use the existing actual cipher/sidecar implementation, including
four threads for concurrent materialization. They do not prove an independent
process holding that sidecar or the Root-owned installation lifetime lease.

## Remaining coordinated central acceptance

Root owns the prepared launcher/runner/bootstrap and fixed HTTP 503/412 mapping.
Its six real CLI/ManagedRuntime boundary cases must run on the integrated clean
product: ordinary missing/legacy read refusal, explicit fresh initialization,
authenticated repeat with unknown fields, wrong keys and refusal before lease.
Cold application import/global registration, actual integration action refusal,
auth/SQL/PostgreSQL and an actual complete backup/restore using the new runtime
factory remain separate coordinated proofs. In particular, restore must retain
archived field keys while rotating JWT/session state and then load the restored
cipher with the explicit archived configuration. This handoff claims neither
that native composition nor overall I or A-L acceptance.

No private installation/database/key was touched and no migration, native
server, database or browser gate was run for this packet.
