# I: explicit bootstrap and durable selected keys — Root evidence

2026-10-03. Product commits `98e1bc1`, `22dacfc` and runner isolation
`599bfb0`; factory product independently supplied in `d64c024`. The current
private preview remains Release 126. No private installation was initialized,
converted, restarted or upgraded by these tests.

## Behavior

The actual normal CLI acquires its managed installation lifetime before
Settings, app/SQL imports and state work. `--initialize-integrations` is an
explicit operator action. A normal restart never initializes missing state or
converts plaintext. Fixed safe messages preserve real nonzero failure exits.
Integration HTTP routes centrally return private/no-store 412 for revision
conflicts and 503 for unavailable configuration; HTTP acceptance is separate.

Independent review of the first launcher gate found externally supplied field
keys had bypassed durable-default publication. The actual initializer now
validates the selected active keyring, authenticates existing encrypted state,
and publishes the complete selected field-key/JWT bundle atomically through
the existing configuration sidecar/private-file primitives. Conflicting stored
values refuse before publication. Only after durable key publication can an
absent encrypted state be initialized. Valid encrypted state is unchanged;
damaged, legacy and wrong-key state are never overwritten.

The owned browser runner removes inherited environment aliases for every
actual Settings field, using only Settings class metadata in a bounded 10-second
child. It then supplies its synthetic installation/database/keys explicitly.
No resolved user configuration or secret is emitted by this metadata probe.

## Actual focused gate

On frozen source `22dacfc`, the real Python pytest subprocess completed
**13 PASS in 83.29 seconds**, **84.45 seconds outer elapsed**, no skips or
errors. The outer subprocess timeout was 150 seconds; each actual CLI child
was bounded to 30 seconds. All children exited normally, including the
test-local app-import interception point; no owned server was left running.

- Eight actual CLI cases cover lease/import ordering, explicit first init,
  byte-identical repeat, ordinary missing/legacy refusal, requested legacy and
  wrong-key refusal, and two genuine restarts after removing all external key
  values: single-key and named keyring. The second process reopens the same
  configuration and ciphertext successfully with byte-identical results.
- Five runtime configuration cases include the existing restart/publication/
  duplicate checks plus actual whole-bundle conflict and failed atomic replace
  protection. They use owned temporary files and the actual configuration
  publication path. The failed-replace case injects only that filesystem
  boundary; it does not invent a successful persistence result.

The earlier six-case gate passed separately in 39.14 seconds. Those six are
included in the later eight CLI cases and are **not added again** to produce a
larger distinct-test count. Pure factory evidence remains separate: 48 PASS
in 1.50 seconds. Ruff, Node syntax and diff checks passed for their changed
source files.

These cold launcher cases deliberately stop at actual app import. They prove
no full app login, SQL, PostgreSQL, provider action, backup/restore or shared
release acceptance. The next exact B2 browser case exercises actual integrated
startup and SQLite separately. Genuine authentication/CAS/provider refusal and
factory reopen after full recovery require their own focused native gates.

## Independent review follow-up and actual lossless restart

The independent review found two real edge cases after the first gate: stored
lower/mixed-case key names were not recognized, and accepted signer values
containing boundary quotes/spaces were stripped on restart. `e9ad28e` and
`d019cb1` normalize existing names for both normal defaults and explicit bundle
checks, refuse any alias duplicate/conflict before another key is appended,
and use one shared value decoder plus JSON-quoted serialization where required.
Unchanged safe existing files retain their exact bytes. No ambient expansion,
key rotation or plaintext migration was added.

Frozen `d019cb1`: **20 PASS / 26.27 seconds**, **27.35 seconds outer elapsed**,
hard outer90 seconds and actual CLI children30 seconds, no skips/errors. These
are the 18 actual runtime-environment cases (including seven alias cases and
five actual loader/Settings opaque-value roundtrips), plus the fresh signer
two-process case and the named-keyring two-process restart recheck. The signer
case compares only hashes and preserves its configuration bytes after removing
the externally supplied keys. This repeats some earlier cases and is not added
as 20 completely new distinct cases. Processes closed normally.

The subsequent genuine SQL-authenticated route and fresh full recovered app
gates are recorded separately in
`I_ENCRYPTED_RUNTIME_NATIVE_ACCEPTANCE_HANDOFF_20261003.md`.
