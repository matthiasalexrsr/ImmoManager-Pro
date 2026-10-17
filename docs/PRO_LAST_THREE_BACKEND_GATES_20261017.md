# Letzte drei Backend-Gates: historischer Index, Rechnungsprüfung und echtes FinTS

**17. Oktober 2026.** Eigenständiger Entwicklungszweig
`pro/stage-full-matrix-20261016`, Ausgangsstand `329cda33`.
Die zentrale Referenz `claude-review-20261013`, die laufenden
Benutzerinstallationen und die produktiven Daten blieben unverändert.

## Ausgangslage: belastbarer vollständiger Memory-/Coverage-Lauf

`artifacts/pro-tests/complete-backend-329cda33-memory-dadc824d02694ff79054f40d13649041`:

- **2.670 bestanden, 3 fehlgeschlagen, 114 übersprungen**,
  Code-Commit `329cda33`, Zeilenabdeckung **84,29 %**.
- Die übersprungenen Fälle stammen überwiegend aus ausdrücklich
  nativen PostgreSQL-Suites, die niemals als Memory-PG-Test
  ausgegeben werden dürfen. Separate native Suites existieren;
  sie decken nicht automatisch alle 114 Gegenproben ab.
- Fehler 1: Die echte `fints==5.0.1`-Library war im gemeinsam
  verwendeten Python-Runner nicht installiert. Der Test
  verweigert bewusst jede simulierte oder still übersprungene
  FinTS-Prüfung.
- Fehler 2: Das historische Index-Roundtrip-Orakel versuchte,
  vom **heutigen** Alembic-Gesamthead zurück bis zum
  `6e2f8a4c9b71`-Vorgänger zu gelangen. Spätere private
  Quelldaten-, Zahlungs-, TEHA- und Kommunikationsbelege
  machen einen solchen Downgrade ausdrücklich unzulässig.
- Fehler 3: Analog versuchte der alte Rechnungsprüfungs-Roundtrip,
  vom aktuellen Gesamthead über die neueren unveränderlichen
  Familien zurück bis `5e8b2d4f7a19` abzubauen. Der
  gesicherte Merge-Downgradeguard lehnte dies korrekt ab,
  bevor der historische `invoice_reviews`-Guard geprüft wurde.

## Korrektur ohne Sicherheitsaufweichung

- Die historischen Roundtrips prüfen ihre **genau benannten
  reversiblen Revisionen**: Booking-Index
  `6e2f8a4c9b71 → 8c4d2e6f1a93 → 6e2f8a4c9b71`,
  danach zusätzlich erneut zum Gesamt-`head`; SQL-Abfrageplan,
  belegte Buchung und Betrag bleiben erhalten.
  Rechnungsprüfungsbelege
  `5e8b2d4f7a19 → c9f4a2e7b1d5` blockieren einen
  Downgrade bei belegten Review-/Event-/Transferdaten,
  behalten Rechnungsoriginale bei, und erlauben den
  alten Roundtrip erst nach ausdrücklicher Löschung
  der synthetischen eigenen Testreviews. Danach erneuter
  Upgrade zum vollständigen Head.
  **Keine Produktdowngradeguard wurde entfernt oder gelockert.**
- Die echte Bibliothek `fints==5.0.1` und ihre angepinnten
  transitive Abhängigkeiten wurden mit
  `pip --target artifacts/pro-tools/fints-libs -r requirements-bank.txt`
  frisch im **eigenen ignorierten Testverzeichnis** installiert.
  Die gemeinsame Python-venv wurde nicht verändert.
- `scripts/run_pro_matrix.py --optional-libs
  artifacts/pro-tools/fints-libs` nimmt dieses ausschließlich
  ausdrücklich gewählte, im eigenen Test-Checkout
  befindliche Library-Verzeichnis in den isolierten
  Prüftestprozess auf. Es verweigert unpassende Pfade,
  fehlendes Versionsmanifest und falsche Bibliotheksversion.
  Das Prüflauf-JSON enthält SHA256 des
  `fints-5.0.1.dist-info/METADATA`, der gesperrten
  `requirements-bank.txt` sowie des QA-Starters.
  Weder echte Bank-/TAN-Zugangsdaten noch eine Livebank
  werden für den Bibliothekstest verwendet.

## Nachweise, pro Code- und Laufprovenienz getrennt

- `artifacts/pro-tests/guarded-historic-revision-sql-0b173a72a9444323a658859f48852921`:
  **2/2 SQLite** auf dem vorherigen Commit mit geänderten
  Testquellen, also **historical_working_tree**.
- `artifacts/pro-tests/final-three-original-failures-memory-d297a80c0029452393d7dcabceab83e1`:
  **3/3 Memory**, echter offline FinTS-Wire-/TAN-Vertrag plus
  beide historischen Revisionen; Quellprovenienz
  **historical_working_tree**.
- `artifacts/pro-tests/final-three-original-failures-sql-1be00d9c79a447ae8c6d8d7e42c3b695`:
  **3/3 SQLite**, unveränderte Geld-/Original-/Downgradeguards,
  ebenfalls **historical_working_tree**.
- Der komplette Check auf dem neu eingecheckten Codehash
  wird **separat** ausgewertet; keiner dieser selektiven
  Prüfläufe ist bereits die Gesamtmatrix.

## Weiter offen

Selbst wenn alle drei Einzelursachen gelöst sind, ist ein
**erneuter kompletter Memory-/Coverage- und SQLite-Lauf auf
exakt dem endgültigen Codehash** nötig, ebenso die native
PostgreSQL-Gesamtmatrix, Browser/Restore auf dem kombinierten
Frontend- und Backendstand, reale Provider- und Zielorakel,
und die noch nicht übernommenen Handoverpakete.
Die Feature- und Versionsprüfungen allein ersetzen
keine Freigabe.
