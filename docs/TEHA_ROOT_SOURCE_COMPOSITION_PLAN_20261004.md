# TEHA: korrigierte Quellen in Root zusammenführen

Vorcodeentscheidung auf e3f399d, nach Quellenreview und geschlossenem Handoff
cc28e09. Der bisherige externe Backendchat hat seine Gesprächslängengrenze
erreicht; die ausdrücklich beauftragte lokale GPT6.1Solxhigh-Review hat seine
Quellen weitergeführt. Neue persönliche Readwrites sind eine andere Operation
und keine TEHA-Capability.

## Quellkomposition vor Aktivierung

Root übernimmt nur die abgegrenzte Persistenz-/Commandreihe ab2ce5e86 und ihre
Korrekturen biscc28e09. Die schon vorhandenen DDLfreien Domainquellen werden
nicht doppelt entwickelt. Finales initiales L2 ist unabhängig vom aktuellen
ORM eingefroren; Actor-only-Fakes schalten keinen Write frei.

Die eingefrorene L2-Datei wird nach der gemeinsamen Übernahme unmittelbar
in `backend/db/migrations/proposals` abgelegt. Der zugehörige Operations-
Testimport verweist ebenfalls auf diese inaktive Quelle. K2 bleibt damit der
entdeckte tatsächliche Roothead; die bereits inaktive M2-Vorlage folgt später
erst nach vollständiger K2→L2→M2-Komposition. Kein privates Schema und keine
laufende Vorschau werden jetzt migriert.

## Tatsächliche Prüfungsreihenfolge

1. Reine neue Manifesttests ohne Runtime-/Settings-/Authkontext, begrenzter
   eigener Prozess. Mapping, Original, Verbindung, Portfolio, Eltern und
   Klassifikation müssen zusammenpassen; Kopien gleicher Digestfelder allein
   gelten nicht als Zuordnungsbeweis.
2. Separater Runtime-Grenzgate mit ausschließlich eigener synthetischer
   Konfiguration. Fehlende/defekte Familie liefert einen konkreten 503 statt
   falschem Leerbestand oder rohem 500. Alle drei öffentlichen Write-Aufrufe
   bleiben vor History/Auth/Fachwriter/DML geschlossen.
3. Eigenes natives SQLite-Schema-/Operationsbild: eingefrorene DDL entspricht
   Modellen, vorhandene/alte Entwicklungsfamilie wird nicht repariert,
   Unveränderlichkeit und native FKs/Unique/CHECKs werden tatsächlich geprüft.
4. PostgreSQL, vollständige gemeinsame Migration, DDLfreier Start und echtes
   Recovery folgen separat. Ein reiner Manifest-/Operationspass behauptet
   keines dieser Ergebnisse.

## Offene Anschlüsse vor produktiver Freigabe

Zentrale Modell-/Router-/Retained-Familienregistrierung, reiner ausgewählter
Imagevalidator mit dem tatsächlichen verschlüsselten Historykern und vollständigen
Originalbytes, Schutz der Content-History-Referenz ohne SQL-FK und ausdrückliche
Vor-L2-/Vor-M2-Profilqualifikation. Der heutige Commanddigest allein rekonstruiert
offline nicht den ursprünglichen gesamten Auftrag; erforderliche unveränderliche
Commandbelege sind vor tatsächlicher Writeaktivierung zu ergänzen. Danach eigene
op-/zielgebundene Rootunit, native Sid-/Scope-/CAS-Races und tatsächliche
HTTP-/Browserabläufe. Keine neue Anbieteraktion innerhalb gehaltenen DB-Locks.
