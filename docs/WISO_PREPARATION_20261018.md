# WISO Steuer Windows: lokaler Übertragungsbogen für Fachjahr 2026

Arbeitsstand in der gemeinsamen Hauptkopie `current-integration-20261016`, Ausgang
`0f6e82220c82a5f8f73206330077dd61c99ce5d1`. Die Erweiterung erzeugt einen
nachvollziehbaren **manuellen Übertragungsbogen**, keine WISO-Importdatei. Sie
fügt keine Steuerfachregeln, AfA-Rechnung oder Eigentümerquoten hinzu. Es gibt
keine neue Tabelle, Migration, Abhängigkeit oder externe Übermittlung.

## Herstellerbefund

Die ältere Aussage des Steuerpaket-Handoffs, dass lediglich generische XMLs
verfügbar seien, beschreibt nicht die gesamte vorhandene historische Evidenz.
`../root-correspondence-integration/docs/BUHL_PRODUCER_EVIDENCE.md` und die lokalen
Originale in `../buhl-research` belegen tatsächlich erzeugte Musterexporte aus
WISO Hausverwalter 365, Produktversion 21.02.1530. Die drei Originaldateien wurden
für diesen Arbeitsstand ausschließlich gelesen; Byteanzahl, SHA-256, Wurzel und
Formular-/Feldanzahlen wurden erneut geprüft. Die Originale bleiben außerhalb des
veröffentlichten Quellcodes.

| Muster | Fachjahr | Bytes | SHA-256 | Vordruck-V-Felder |
|---|---:|---:|---|---|
| Baseline | 2026 | 4572 | `aa80c1780cca793440ae9b5a1ff18c33bcbef6a7dd249a49d1234b6b735b7c12` | 34, 17 |
| Baseline | 2025 | 5094 | `7e786f35295a5a9b61747ca90cb7fb8d85f56d8e11f325c58a64b01b16119598` | 36, 23 |
| Gemeinsame AfA-Änderung | 2026 | 3437 | `aaaaa253466d08747a4463fbd505fad2c85dd5d135733ce938e094aa1d749b8b` | 36 |

Beobachtet sind `Elster`, `DatenTeil/Nutzdatenblock`, `Nutzdatenheader` Version
101, `Jahressteuererklaerung` Version 101 und `Vordruck(name="V", lfdNr)` mit
`Feld(nr,index,wert)`. Das ist ein Strukturvertrag dieser Muster, keine
vollständige fachliche Feldzuordnung. Die Jahresfeldsätze unterscheiden sich.

Im AfA-Fall wurden 2,50 Prozent und 1.234,56 EUR gemeinsam eingegeben. Hinzu kamen
`0703418/index=1/wert=2.5` und `0703422/index=1/wert=1234,56`; 34 bestehende
Feldwerte blieben unverändert. Die isolierte Bedeutung der beiden Einzelparameter
ist dadurch noch nicht bewiesen. Ein pauschaler Zahlenformatter wäre bereits
wegen der unterschiedlichen Dezimaltrennzeichen unbelegt.

Die vorhandenen Originale reichen daher für einen produktiven herstellerspezifischen
Serializer nicht aus. Erforderlich sind kontrollierte Einzelfeldänderungen mit
Basis-/Änderungsoriginal, Programm-/Build-/Fachjahrnachweis, Objekt-/Formular-/
Feld-/Indexbedeutung sowie Grenzfälle für Nullwerte, negative Werte, Erstattungen
und mehrere Objekte. Zusätzlich fehlt die Annahme samt Feld-/Centabgleich im
echten WISO Steuer Windows für Fachjahr 2026. Der Programmname darf nicht als
Fachjahrnachweis verwendet werden. Die fehlende Zielinstallation erklärt nicht
die weiterhin fehlende lokale fachliche Serializer-Spezifikation.

## Benutzerweg

1. Unter **Steueraufbereitung und DATEV** das Verfahren **Jahressteuerbasis
   (neutral)** und ein EUR-Portfolio wählen. Konten-/Kategorienregeln und
   fachliche Begründungen wie bisher erfassen.
2. Bei Steuerjahr 2026 **Manuellen WISO-Übertragungsbogen für Fachjahr 2026
   vorbereiten** aktivieren. Mit **Zielobjekt hinzufügen** Quellobjekt,
   eindeutige Nummer des eigenen Übertragungsbogens und geprüfte Zielbezeichnung
   erfassen. Die Nummer wird nicht als bestätigte WISO-`lfdNr` ausgegeben.
3. Mit **Manuelle Zielzeile hinzufügen** eine vorhandene Quell-Formularzeile
   einschließlich Einnahme-/Ausgabebehandlung einer frei geprüften manuellen
   Zielbezeichnung und Begründung zuweisen. Diese Bezeichnungen sind keine
   Herstellerfeldnummern. Profil fachlich bestätigen und unveränderlich speichern.
4. **Vollständige Quellen prüfen** zeigt wie bisher Buchungsquellen, Summen und
   fachliche Probleme. Zusätzlich erscheinen alle vorhandenen Gruppen im
   Übertragungsbogen, einschließlich fehlender Objekt-/Zielzuordnung,
   vorzeichenbehafteter Null-/Negativsummen, Quellanteilanzahl und unbenutzter
   Profilzuordnungen. Zugeordnete plus offene Centwerte müssen die vollständigen
   Einnahme-/Ausgabesummen ergeben. Es werden keine Geldbeträge aus Rechnungen,
   Sollstellungen oder Zahlungszuordnungen zusätzlich erzeugt.
5. Ein Stichtag vor Jahresende wird ausdrücklich als **Teiljahr** gemeldet.
   Ein vollständig geprüftes neutrales Jahresquellenbild kann mit offenen
   manuellen Zuordnungen gespeichert werden; der manuelle Übertragungsbogen
   bleibt dabei erkennbar unvollständig. Weder ein vollständiger Bogen noch ein
   erfolgreicher Download setzt `vendor_file_ready` oder `target_import_verified`.
6. **Geprüfte Jahresfassung unveränderlich speichern** bindet den vorhandenen
   `preview_hash`, die genaue Profilfassung und die verschlüsselten vollständigen
   Originalquellen. Neue Zielbezeichnungen benötigen eine neue Profilfassung und
   Jahresrevision. Vorherige Fassungen ändern sich nicht.
7. In der Historie prüft **Gesicherten Übertragungsbogen prüfen** alle gespeicherten
   Quellbytes und berechnet unabhängig Gruppen, Anzahl und Geldsummen neu. Profil-
   und Snapshot-Hashes sowie die abgeleitete Vorbereitung müssen übereinstimmen.
   **Neutrale Quellen und manuellen Übertragungsbogen herunterladen** liefert
   tatsächlich ein geprüftes ZIP mit JSONL-Originalquellen, neutralen Zahlungs-/
   Steuerzeilen, Manifest, Originalprofil, Übertragungsbogen und Nachweisgrenzen.

**Herstellernachweise anzeigen** zeigt den historischen Producer-/Fachjahrstatus,
die drei Musterhashes und die exakt noch fehlenden Nachweise direkt in der Seite.

## Speicherung und Schnittstellen

Das optionale Feld `wiso_preparation` liegt im bereits versionierten
`annual_tax_profiles.spec_json`. Es enthält `target_product`, Fachjahr 2026,
Nachweisversion `hv365-21.02.1530-observed-2026-v1`, `objects` und `lines`.
Profil-CAS, Idempotenz pro Akteur, Rechte und Schlüsselablage bleiben die bestehenden
Mechanismen. Objekt-IDs, Nummern und Behandlung-/Quellzeilenpaare sind eindeutig.
Fremde Herstellerfeldattribute sind ausdrücklich keine akzeptierten Modellfelder.

Zusätzliche Lesepfade unter `/api/v1/reports/annual-tax`:

- `GET /wiso/evidence`: historische Herstellerbeobachtungen und Nachweisgrenze.
- `GET /projections/{id}/wiso-preparation`: vollständig geprüfter historischer
  Übertragungsbogen, keine Neuberechnung aus heutigen Buchungen.

Vorprüfung, Profilspeicherung, Jahresrevision und Download verwenden die bisherigen
Endpunkte. Das ZIP einer ausdrücklich konfigurierten Vorbereitung enthält zusätzlich:

- `reviewed-profile.json`
- `wiso-manual-preparation.json`
- `manual-transfer-worksheet.csv`
- `README-manual-transfer.txt`

Keine `.xml`-Datei wird erzeugt. Der CSV-Bogen bleibt ausdrücklich neutral. Textzellen
werden gegen Tabellenformeln geschützt; centgenaue Geldwerte werden separat aus
Integern formatiert, einschließlich `-0,01` und `0,00`.

Historische neutrale Profile ohne Vorbereitung behalten ihren bisherigen Hash und
ihre vier ZIP-Mitglieder. Das neue optionale Feld wird bei fehlender Vorbereitung
vor der Hashbildung ausgelassen; alte unsichere Wiederholungsaufträge erhalten
dadurch nicht allein wegen des Upgrades einen Konflikt. ZIPs mit Vorbereitung sind
deterministisch aus den gespeicherten Originalen abgeleitet. Sie werden nicht als
zusätzlich gespeicherte Herstelleroriginale oder Exportjobs ausgegeben.
Der Evidenzkatalog ist Bestandteil dieses versionierten Ableitungsvertrags.
Zusätzliche künftige Herstellerbefunde benötigen eine neue Nachweisversion;
der Katalog für bereits gespeicherte Fassungen muss unverändert erhalten bleiben.

Aktuelle Objektberechtigungen schützen auch die gespeicherten manuellen Zielnamen,
einschließlich unbenutzter Zuordnungen. Eine vorhandene inzwischen fremde Immobilie
darf nicht wie eine gelöschte historische Quelle behandelt werden; eine reine
Existenzprüfung auf der Datenbankverbindung umgeht daher gezielt Session-Scopefilter,
bevor die echte berechtigte Objektabfrage erfolgt.
Dies gilt für Profil-/Historienantworten und Downloads. Die vollständigen Quellen
bleiben verschlüsselt im vorhandenen Jahresarchiv. Vollbackup-/Schlüsselmechanismen
brauchen keine neue Tabelleneinbindung.

## Prüfungen

Abschließende Backendmatrix über den vorgegebenen Interpreter und
`scripts/run_pro_matrix.py`: `artifacts/pro-tests/wiso-preparation-verified-sql-efbae723ca494ddc92fa9efe4935dedc`.
**92 bestanden, 1 vorhandener Skip, keine Fehler.** Enthalten sind 15 neue
WISO-Vorbereitungsfälle einschließlich Memory und echten SQLite-Dateien, die
Jahressteuer-/HTTP-/Rechtefälle, aktuelle Steuerverträge sowie die bestehenden
Migrations-/Vollbackup-/Restoreprüfungen. Übersprungen ist ausschließlich
`test_sql_source_buffers_and_complete_atomic_persistence[memory]`, weil dieser
Fall SQL voraussetzt. `input.json`, `result.json`, `junit.xml` und `pytest.log`
bewahren Ausgangscommit, Quellhashes, isolierte Runtime und tatsächliche Ergebnisse.

Neue Orakel prüfen mehrere Objekte, Einnahmen-/Ausgabenerstattungen, exakte
Centbeträge, Null-/Negativgruppen, offene Zuordnungen und Teiljahre, unveränderte
ZIP-Bytes nach späteren Quell-/Objekt-/Profiländerungen, altes Profilhashformat und
alte ZIP-Mitglieder, CAS-/Idempotenzkonflikte, Ablehnung unbestätigter Hersteller-
Modellfelder, beschädigte Snapshotzuordnungen sowie Leser-/Portfolioentzug und
verschobene unbenutzte Zielobjekte. Der isolierte gezielte Objekt-Rechtelauf
`wiso-object-guard-current-sql-83e929aceee5499fbc3ef0d41764e978` bestand zusätzlich
2/2 Fälle. Diese Zahlen überschneiden sich mit der Endmatrix.

Frühere Fehlerläufe bleiben erhalten: `wiso-preparation-first-memory-94758c07262f4f1abf17151bad5f179b`
hatte zwei berechtigte Alt-ZIP-Orakelfehler durch einen zusätzlichen Profileintrag.
Daraufhin wurde der ursprüngliche neutrale Archivvertrag erhalten. Die Läufe
`wiso-preparation-contract-sql-33e7c55a581e41bba9a26f891098cddc`,
`wiso-preparation-final-sql-dee7faee7d3449e78905301f56095fc1` und
`wiso-unused-object-isolation-sql-607a3756a74e4dc2b2fe9c3b916a31ad` machten jeweils
die unzureichende Existenzprüfung durch Session-Scopefilter sichtbar. Die
Verbindungsprüfung und die abschließende unveränderte Gegenprobe beheben diesen
Fehler; Erwartungen und Rechte wurden nicht gelockert.

`artifacts/wiso-frontend-20261018.json`: **8/8 Komponententests erfolgreich**.
Geprüft sind bestehende Quellenpagination, verlorene Speicherantwort und
Wiederholung nach Reload, spätere Quellen-/Sitzungsänderung, Leserrechte sowie
die neuen manuellen Profilfelder, sichtbare Lücken/Teiljahre, negative Centwerte,
historische Vorschau und tatsächliches Blob-Downloadauslösen. Das unkonfigurierte
Optionalfeld wird auch im Frontendbefehl ausgelassen; die Identität alter privater
Wiederholungsaufträge bleibt erhalten. Der letzte Frontendstand ist separat erneut
geprüft. Gezieltes ESLint, Ruff, mypy der sechs geänderten Backendmodule und
`git diff --check` sind erfolgreich.

Kein Backend-Gesamtsuite-, Produktinstallations- oder echter WISO-Zielimportnachweis
wird daraus abgeleitet. Ein unabhängiger Browserlauf wird durch den
Integrationskoordinator gesondert geprüft.
