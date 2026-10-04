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

## Final codec composition with the actual backup parser

The above20-case gate verified the then-current launcher/Settings codec only.
Further independent review found that ordinary `#` comments and some JSON
control escapes changed values in the actual backup dotenv parser; the JSON
decoder also reinterpreted legacy simply quoted Windows paths. Final product
`b74c25f` writes risky values using recognized dotenv double-quote escapes and
a fixed version comment. Only this explicit comment permits escaped decoding
by the shared launcher/persistence helper; old simply quoted paths stay literal.
Recovery's actual `dotenv_values(interpolate=False)` needs no new secret format
or parser patch. Dollar expressions stay literal. Physical records split only
on newline so quoted Unicode separators do not become fake configuration lines.

Actual26-case gate on `b74c25f`: **25 PASS / 1 FAIL, 28.75 seconds**, **29.81
outer**, hard90 seconds. All nine actual dotenv/loader/Settings roundtrips,
alias/conflict/atomicity/legacy path cases and both fresh restart cases passed.
The signer child now separately selects actual `recovery._plan` and compares
its signer hash with the actual runtime hash across restart. The existing
two-process canonical key-pair assertion caught one unnecessary empty record
from splitting a newly absent file; its assertion was not relaxed.

`1719abb` removes only the final newline split sentinel through a shared helper,
preserving true interior records and Unicode values. Exactly that two-process
case plus the nine actual codec roundtrips were rechecked: **10 PASS / 5.12
seconds**, **6.71 outer**, hard60 seconds, no skips. All children closed normally.
Together these establish **26 different positive focused cases**, not a single
all26 green run and not 20+25+10 newly different cases. Ruff/diff checks passed.
The earlier JSON-codec evidence is retained as historical evidence, not the
final backup-compatible implementation. Other actual app/SQL/fullarchive gates
remain in their separate handoff; no private key was changed or transmitted.

## Case-insensitive stored names in the actual backup planner

Independent review found recovery._plan selected signer/path names before its
existing lowercase Settings conversion. Normalize known dotenv names before
selection and before strict recovered JSON precedence. Distinct case aliases
are refused with a value-free instruction; historical same-name dotenv last
assignment remains compatible. Original source bytes are not rewritten.

Actual pure gate with plugin autoload disabled/--noconftest, hard45 seconds:
8 PASS/2 FAIL in2.09 seconds. Both failures were new tests comparing POSIX path
spelling with the existing Windows-native configuration path representation;
actual selected Path identities and signer had already matched. Correct those
two assertions to compare Path identities, retaining every selected-path/value
and no-source-write assertion. Exact two-case rerun, hard30: 2 PASS/1.11 seconds.
Thus10 different positive cases compose the evidence, including9 new alias/
precedence cases and one existing same-name dotenv regression; no all10 green
rerun claimed. No app, SQL, archive, CLI child or private installation opened.
