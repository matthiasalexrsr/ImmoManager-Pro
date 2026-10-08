# Parteienkarte und Dokumenteneinsicht — 7. Oktober 2026

## Ausgangsstand

Diese Erweiterung setzt auf Claudes Commit `3223a36a9d0e5db143b993b12a40ba72d5d376f2` vom 5. Oktober 2026 auf, Branch `claude/dreamy-gauss-nmaxhn`. README, pyproject.toml und Testdaten-Generator der installierten Windows-Testversion vom 5. Oktober wurden gegen diesen Stand abgeglichen. Der ältere Integrationszweig vom 4. Oktober wurde nicht als Grundlage verwendet.

Featurebranch: `codex/party-document-workspace-20261007`.

## Bedienung

- Ein Klick auf einen Mieternamen öffnet die Parteienkarte. Dies funktioniert in Mietern, Verträgen, Einheiten, Mietübersicht, Forderungen, Mietforderungen, Kautionen, Buchungen, Abrechnungen, Dokumenten und im Mieterkonto.
- Die Karte enthält Kontaktangaben mit Kopierfunktion, E-Mail-/Telefonlinks, Notizen sowie getrennte aktuelle, frühere, künftige und entworfene Verträge. Mieten werden je Vertrag mit Gültigkeitsdatum angezeigt.
- **Mieterkonto**, **Mieter bearbeiten** und **Dokumente** führen direkt zum jeweiligen Arbeitsbereich. Ein Vertragsdokument-Button setzt den Vertragsfilter.
- Dokumente können gesucht, nach Typ/Vertrag gefiltert und als Liste oder Karten angezeigt werden. Weitere Seiten werden ausdrücklich geladen. Die Vorschau unterstützt PDF/Bilder, OCR-Text und Originaldownload.
- In der Dokumentenverwaltung schränkt die Parteiauswahl die Liste und neue Uploads ein. Eine Datei öffnet die Metadatenprüfung vor dem Speichern; mehrere Dateien werden einzeln importiert und erhalten jeweils einen sichtbaren Ergebnisstatus.
- Der CSV-Export umfasst die vollständige gefilterte Auswahl. Bei Ladefehlern oder erkannten Bestandsänderungen wird kein unvollständiger Export angeboten.
- Lesende Benutzer erhalten die vorhandenen Leseaktionen; Bearbeitungs- und Uploadaktionen richten sich nach Claudes bestehender Rollenverwaltung. Diese Funktion ist kein Mieterportal mit mietervertraglichen Benutzerkonten.

## Daten und Schnittstellen

Die additive Alembic-Migration `6e2f8a4c9b71` folgt auf `a1d6c3f8e2b4` und ergänzt `documents.tenant_id` einschließlich Fremdschlüssel und Index. Bestehende Dokumente behalten ihre Verknüpfungen.

Zu einer Partei gehören direkt zugewiesene Dokumente und Dokumente ihrer Verträge ohne abweichende ausdrückliche Parteizuordnung. Frühere Verträge werden einbezogen. Eine gemeinsame Immobilie oder Einheit allein begründet keine Parteizuordnung. Eine direkte Zuordnung bleibt erhalten, falls später der Mieter eines Vertrags geändert wird.

- `GET /api/v1/tenants/{id}/overview`: Stammdaten, vollständige Vertragsliste mit Objekt-/Einheitsbezeichnung und wirksamer Vertragsmiete, Dokumentanzahl und Typen.
- `GET /api/v1/tenants/{id}/documents`: `skip`, `limit`, `q`, `document_type`, `contract_id`; Antwort mit `items`, `total`, `skip`, `limit`, `has_more`. Stabile Reihenfolge nach Erstellungszeit und ID, neueste zuerst. Eine Seitengröße begrenzt keine Gesamtanzahl.
- Bestehende Dokument-Create/Update/Patch/Import-Schnittstellen unterstützen optional `tenant_id` und prüfen Objekt-, Einheits-, Vertrags- und Parteizuordnung.
- Direkte Dokumentverknüpfungen werden vom vorhandenen Löschschutz berücksichtigt. Ein Downgrade wird vor Änderungen abgelehnt, solange solche Zuordnungen bestehen.

Vor einem Upgrade einer bestehenden Installation Datenbank und Uploads sichern. Die Migration mit der tatsächlich verwendeten `DATABASE_URL` explizit über `python -m alembic upgrade head` einspielen; danach den neu gebauten Frontendstand mit dem neuen Backend starten. Die Windows-EXE vom 5. Oktober ist durch eine Quellcodeänderung nicht automatisch aktualisiert.

## Nachweise

Die Abnahme verwendete eine eigene lokale SQLite-Datenbank und eigene Uploads. Bestehende Benutzerdateien und die installierte Windows-Testversion wurden nicht verändert.

| Prüfung | Ergebnis |
| --- | --- |
| Frontend, vollständiger vorhandener Testbestand einschließlich neuer Regressionen | **101 bestanden**, 23 Dateien; Vitest, drei Worker |
| Frontend ESLint | Bestanden |
| Frontend Produktionsbuild | Bestanden, 557 Module |
| Ruff für sämtliche geänderten Python-Dateien mit Repository-Regeln | Bestanden |
| Backend-Parteien-/Dokument- und Migrationsregressionen | **39 bestanden**, ein bewusst übersprungener SQL-Abfragebudgettest beim reinen Memory-Store |
| Weitere gezielte Backend-CRUD-/Miet-/Lösch-/Uploadregressionen | **89 bestanden**, ein Memory-Store-Skip; separater Lauf mit überschneidenden Prüfungen |
| Migration nach abschließender SQLite-Downgrade-Korrektur | **9 bestanden**, einschließlich übernommener ORM-Schemata und Erhalt eingehender Rechnungsverweise |
| Tatsächliches Alembic-Upgrade vor Start der isolierten Vorschau | Bestanden |
| Browserabnahme mit laufendem Backend und echten Uploads | **14 Abläufe bestanden**, keine Browser-/API-Fehler oder fehlgeschlagenen Testdaten-Bereinigungen |

Die Backend-Läufe wurden mit Python 3.12 unter Windows und SQLite/Memory ausgeführt. Eine PostgreSQL-Gesamtabnahme oder Freigabe sämtlicher früher geplanter Projektpakete ist damit nicht erklärt. Vitest meldet weiterhin nicht fehlschlagende Hinweise zu einzelnen asynchronen Testupdates (`act`) und jsdoms fehlendem `scrollTo`.

Die Browserprüfung umfasst echte Anmeldung als Eigentümer und Leser, historische Verträge, Ausschluss anderer Parteien derselben Einheit, Parteidokumente ohne Vertrag, 26 Dokumente über Seitengrenzen, Suche/Typfilter, CSV mit 26/1/13 passenden Einträgen, Einzel-/Mehrfach-PDF-Upload mit anschließender Datenbankprüfung über die API, bytegleichen Download, verschachtelte Vorschau/Escape/Fokusrückgabe und Ansichten bei **1440, 360 und 320 Pixeln**. Zusätzliche Frontendtests prüfen den vollständigen Export von 501 Dokumenten, veraltete Antworten und Parteienwechsel während eines Uploads.

Lokale Testausgaben liegen unter `artifacts/frontend-acceptance.xml`, `artifacts/frontend-acceptance.log` und `artifacts/party-browser/`. Screenshots wurden zusätzlich visuell geprüft. Generierte Artefakte sind nicht Teil der Versionsverwaltung.

## Prüfungen wiederholen

```sh
cd frontend
npm ci
npm run test -- --maxWorkers=3
npm run lint
npm run build
```

Backendtests in einer isolierten Entwicklungsumgebung mit temporärem `DATA_DIR`, eigener `DATABASE_URL`, deaktivierter automatischer Demodatenerstellung und `TEST_STORE_BACKEND=memory` ausführen. Die neuen Workspace-Tests parametrisieren Memory und SQLite selbst:

```sh
python -m pytest backend/tests/test_tenant_workspace.py backend/tests/test_migrations.py -q
```

Die Browserprüfung `scripts/party_workspace_browser_qa.mjs` läuft aus dem Repository-Verzeichnis. Sie benötigt einen separat gestarteten lokalen Testserver, ein vorhandenes Playwright mit Chromium sowie folgende Umgebungsvariablen:

- `QA_BASE_URL`: Ursprung des isolierten Servers, z. B. `http://127.0.0.1:8765`.
- `QA_PASSWORD`: Passwort der Testkonten; wird nicht ins Protokoll geschrieben.
- `QA_ALLOW_TEST_WRITES=1`: bestätigt die ausschließliche Verwendung dieser isolierten Testinstanz; der Lauf erstellt und entfernt eigene Testdatensätze.
- Optional `QA_OWNER` und `QA_READONLY` für die Benutzernamen.
- `QA_PLAYWRIGHT_PATH`: absoluter Pfad zu einer vorhandenen `@playwright/test/index.mjs`, falls Playwright nicht im Frontend-Entwicklungsumfeld installiert ist.

```sh
node scripts/party_workspace_browser_qa.mjs
```

Die Prüfung setzt keine produktiven Zugangsdaten voraus. Die eigentlichen Vorschaudaten stammen aus Claudes unverändertem Testdaten-Generator.
