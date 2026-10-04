# Inboxvalidator: enger Korrekturhandoff

03.10.2026; eigener Checkout `work/dashboard-notification-timestamps`.

Root meldet für die Integration bis `62f138e` den tatsächlichen zwölfteiligen
Pure-/Raw-Gate: **7 PASS / 5 FAIL, 1.43s, normaler Exit1**, mit
`--noconftest` und hart30s. Das ist keine vollständige Pureabnahme.
Roots isolierte Rawfixture zeigt den TypeError aus Set/Dictvergleich in
`notification_inbox_validation._schema`; derselbe Fehler steht im tatsächlichen
SQLAlchemy-Inspectorzweig. App/Auth/Settings/Store wurden im isolierten
Rootdebugpfad nicht gestartet.

Saubere neue Commitfolge:

1. `11ac66c`: tatsächlicher Korrekturhinweis im A1Plan **vor** Sourceänderung.
2. `594cb78`: genau zwei Vergleiche korrigiert auf
   `set(FIELDS) <= set(columns)`, jeweils tatsächliche Spaltennamensets.

Keine folgende Form-/Nullability-/PK-/FK-/Zeitprüfung und keine Testassertion
wurde verändert. Keine Änderung an anderen Featurequellen oder Sharedcore.
`git diff --check` erfolgreich; hier kein neuer Pythonimport, Test-, App-,
DB-, Server-, Browser- oder PGstart. Der korrigierte Stand hat noch keinen
Runtime-/Fix-PASS. Vorherige generische TypeError-Abweisungen können keinen
gezielten fachlichen Negativnachweis ersetzen.

Root übernimmt den Fix und wiederholt deshalb zunächst sämtliche zwölf
Pure-/Rawfälle; erst anschließend die sechs eigenen native SQLitefälle.
Positive Writecapability-/HTTP-/Race-/PG-/Migration-/Restorekomposition bleibt
weiterhin offen. Ursprünglicher A1-Handoff `3260997` bleibt separat verfügbar;
dieser neue Nachtrag benötigt dessen Dokument nicht als Cherry-Pick-Vorbedingung.
