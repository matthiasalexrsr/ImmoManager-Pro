# Ungestempelte lokale SQLite-Installationen ausdrücklich übernehmen

Dieser Wartungsweg ist für vollständig erkannte ältere lokale Schemas vorgesehen.
Der Produktionsstart liest und prüft weiter; er migriert, repariert oder stempelt
keinen vorhandenen Bestand. Eine private Installation wurde in der Entwicklung
dieses Wegs nicht benutzt oder geändert.

Die Erkennung vergleicht den gesamten eingefrorenen Release-126-Katalog:
Tabellen und Spalten mit Defaults/Nullability, native Primär-/Fremdschlüssel,
Unique-/CHECK-Constraints, vollständige Indizes und Original-Aufbewahrungswächter.
Sie unterstützt den echten `1910f25`-create-all-Katalog sowie den ausdrücklich
geprüften vollständigen Katalog mit früheren zwei-Ziel-Beleg-/Budgetchecks.
Unbekannte Mischformen, Teilfamilien, geschwächte Wächter und andere Versionen
brechen ab. Eine passende Tabellenzahl ist kein Nachweis.

## Vorprüfung

Die Anwendung einschließlich Hintergrundschreibern vollständig beenden. Die
gewählte Installation braucht ihre unveränderten gespeicherten Schlüssel und
den tatsächlichen Upload-Baum. Der Befehl übernimmt die gleiche native
Installationssperre wie Start und Vollsicherung; eine laufende Instanz blockiert.
Er nimmt keine Prozessnummer an und beendet keinen fremden Prozess.

```powershell
.\.venv\Scripts\python.exe -m backend.maintenance legacy-sqlite inspect --data-dir "D:\Synthetic ImmoManager"
```

Der erkennbare Profilname und der vollständige Kataloghash erscheinen im
Ergebnis. Die Schemaerkennung bestätigt keine nachträgliche fachliche Prüfung
alter Zahlungen oder Abrechnungsquellen.

## Übernahme mit vollständiger Sicherung

```powershell
.\.venv\Scripts\python.exe -m backend.maintenance legacy-sqlite upgrade --offline --data-dir "D:\Synthetic ImmoManager" --output "E:\Private Backups\Before Upgrade.immobak"
```

Die Passphrase wird zweimal interaktiv gelesen und gehört nicht in Argumente
oder Logs. `--database`, `--uploads` und `--integrations` wählen bei Bedarf die
tatsächlichen absoluten alten Speicherorte, genau wie die vollständige Recovery.
Für größere Installationen gelten dieselben positiven `--capacity-file`- und
`--timeout-seconds`-Budgets. Ein vorhandenes Archiv wird nicht überschrieben.

Vor jeder originalen Schemaänderung entstehen das authentifiziert verschlüsselte
Vollarchiv und eine tatsächliche isolierte Wiederherstellung ohne Appstart,
Port oder Provider. Die ursprüngliche Installation behält dabei ihren
Signierschlüssel und ihre Sitzungen. Die reguläre Sicherheitsrotation erfolgt
ausschließlich in der Wiederherstellungskopie.

Zwei isolierte DDL-Probeläufe prüfen das erwartete vollständige Zielschema und
den Erhalt sämtlicher ursprünglichen Spaltenwerte. Danach übernimmt eine native
SQLite-Transaktion dieselben tatsächlichen gebündelten späteren Migrationen.
Erst nach Katalog-, Constraint-, Wächter-, Integritäts- und Bewahrungsprüfungen
wird der tatsächlich fertiggestellte Head eingetragen. Dies behauptet keine
geratene historische Migration. Abbruch vor Commit rollt die Schemaänderung
zurück; Originalsnapshot und eventuell fertiggestelltes Archiv bleiben erhalten.

Neue historische Messbindungen bleiben leer. Ältere Fachzustände werden nicht
als nachträglich bestätigte Quellbelege ausgegeben. Das Ergebnis und die private
Operationsquittung trennen `schema_verified`/Integritätsnachweis von
`legacy_business_states_preserved_require_source_review`. Bei der bereits
unterstützten Belegumstellung kann die zusätzliche Rechnungssaldospalte den
alten Zustand `paid` übernehmen; dabei entsteht kein neuer Zahlungsbeleg.

## Status und geprüfter Rückweg

Die Ergebnis-UUID bezeichnet genau eine Operation derselben Installation.

```powershell
.\.venv\Scripts\python.exe -m backend.maintenance legacy-sqlite status --data-dir "D:\Synthetic ImmoManager" --operation-id "<operation UUID>"
.\.venv\Scripts\python.exe -m backend.maintenance legacy-sqlite rollback --offline --data-dir "D:\Synthetic ImmoManager" --operation-id "<operation UUID>"
```

Status vergleicht den tatsächlichen Original-/Zielkatalog und alle erfassten
Tabellenwerte. Nach einem Prozessabbruch unmittelbar am Commit unterscheidet
dieser Vergleich die noch originale von der fertig übernommenen Datenbank.
Ein unklarer Zustand wird nicht automatisch korrigiert.

Der Rückweg prüft Kernel- und SQLite-Schreibsperre, die genaue Datenbankidentität,
Snapshot, Vollarchiv und sämtliche ursprünglichen Dateien. Er ist nur vor neuen
Geschäftsschreibvorgängen oder Dateiveränderungen zulässig. Danach verweigert er
die Rücknahme, damit keine neueren Daten verschwinden. In einer nativen
Transaktion stellt er ausschließlich die vollständig geprüfte Originalstruktur
und Originalwerte einschließlich Sitzungsfamilien wieder her. Schlüssel,
Upload-Bytes und Einstellungen werden nicht umgeschrieben.

Die privaten Operationsdaten liegen unter `.legacy-sqlite-upgrade/<UUID>` im
ausdrücklich gewählten Datenordner. Der darin erhaltene ursprüngliche
SQLite-Snapshot enthält den vollständigen privaten Bestand und ist mit nativen
privaten Dateirechten geschützt. Für transportable Sicherungen das verschlüsselte
Vollarchiv verwenden. Operationsquittungen, Originalsnapshot und Archiv für den
geprüften Rückweg aufbewahren; keine Sperrdateien manuell löschen.

## Quellen- und Paketgrenzen

Die Referenzen werden mit `scripts.build_legacy_sqlite_reference` ausschließlich
aus archivierter Repositoryquelle und leeren synthetischen Daten erzeugt. Die
Rezeptur und der vollständige aufgelöste Release-Commit stehen im Profildatensatz.
Ein neuer Migration-Head verlangt eine erneut geprüfte Zielreferenz; der Service
bricht bei einem nicht mitvalidierten Head ab. Der Generator läuft nicht beim
Produktionsstart und braucht niemals eine private Datenbank.

`backend/legacy_sqlite_upgrade/release126_profiles.json` muss in Python-Paketen
und eingefrorenen Builds enthalten sein. Ohne diese Referenz ist die Übernahme
gesperrt. Root integriert die schmale positive Altprofil-Erkennung in den
vorhandenen vollständigen Archivprüfer sowie die Paket-/CI-Komposition.
