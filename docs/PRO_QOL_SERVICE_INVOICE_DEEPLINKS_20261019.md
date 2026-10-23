# ImmoManager Pro – QoL: Objektvertrag und Rechnungsprüfung besser vernetzt (19.10.2026)

**Isolierter Frontend-Checkpoint, nicht ausgerollt.** Ausgangspunkt: `pro/full-handover-20261016` bei `4a3a3de4`. Keine Änderung an Backend-Verträgen, Entwurfspersistenz, Berechtigungen oder fachlichen Buchungen.

## Umsetzung

- **Objektvertrags-Detailseite:** Die bestehenden Unterseiten `master`, `locations`, `tariffs`, `deadlines`, `finance`, `documents` sind über `/service-contracts/:id?tab=...` direkt adressierbar. `master` ist der Standardzustand. Ungültige Tabs fallen auf die Stammdaten zurück. Vorhandene andere Query-Parameter bleiben beim Tabwechsel erhalten; Browser-Zurück/Vorwärts aktualisieren den aktiven Abschnitt ohne neue Domain-Aktion.
- **Tastaturnavigation:** Die bestehenden `role=tab`/Tabpanel-Beziehungen behalten ihre Semantik. Nur der aktive Reiter hat `tabIndex=0`; `Pfeil links/rechts`, `Home` und `End` ändern aktiven Reiter, URL und Fokus. Fokusrahmen und mindestens 44 px Höhe sorgen für sichtbare Tastaturbedienung.
- **Kontextlinks:** Bei genau einer sichtbar zugeordneten Immobilie werden deren **konkrete** Detailansicht und Buchungsliste `/bookings?property_id=...` verlinkt. Bei genau einer zugeordneten Einheit ist die konkrete Einheitenakte erreichbar. Mehrere Lieferstellen können einzeln über ihre Tabellenzeile zur jeweiligen Immobilie/Einheit führen. Bei eingeschränkten Objektverträgen werden keine solchen zusätzlichen Zuordnungslinks eingeblendet; bei uneindeutigen Mehrfachimmobilien auch kein irreführender pauschaler Link.
- **Rechnungsprüfung:** Der Prüfdatensatz verlinkt – sofern belegt – zur Finanzansicht der Immobilie, zur Rechnungslisten-Suche über die Rechnungsnummer und zur echten Wartungsfall- oder Objektvertragsakte (letztere direkt im Finanzabschnitt). Fehlende Zuordnungen erzeugen keinen erfundenen Link. Das bestehende Zurück-zur-Rechnungsprüfung bleibt erhalten.
- **Keine Domain-Automatik:** Diese Links öffnen ausschließlich bestehende GET-Detail- oder gefilterte Listenrouten. Keine neue Schreiboperation, Freigabe, Zahlungsaktion oder automatische Quellrevision.

## Verifikation

- `npm.cmd run test -- src/test/ServiceContracts.test.jsx src/test/InvoiceReview.test.jsx src/test/RelatedPageLinks.test.jsx src/test/EntityLinks.test.jsx src/test/PropertyDossier.test.jsx src/test/PartyUnitNavigation.test.jsx src/test/TenantAccount.test.jsx src/test/ShellNavigation.test.jsx src/test/WorkspaceNavigation.test.jsx src/test/BookingReviewWorkflow.test.jsx src/test/BookingReviewIndependent.test.jsx src/test/CustomBusinessDrafts.test.jsx --maxWorkers=1 --no-file-parallelism`: **93/93 Tests bestanden**, 12 Testdateien.
- `npm.cmd run lint`: erfolgreich ohne neue Warnungen. `npm.cmd run build`: erfolgreich; bekannte nicht-blockierende Warnung `INEFFECTIVE_DYNAMIC_IMPORT` für `NotificationInbox.jsx` weiterhin vorhanden.
- Microsoft Edge Chromium Headless mit einer **echten Objektvertrags-React-Detailseite** im isolierten lokalen Vite-Smoke auf `127.0.0.1:5197`, synthetischer nur lesender Vertragsantwort und ersetzten API-Funktionen: **PASS** bei Viewports **320, 375, 1280 px**; kein dokumentweiter horizontaler Überlauf, eigene scrollbar breite Reiter- und Lieferstellentabelle, auf Mobilbreite 44-px-Links. Native `ArrowRight`/`Home`-Tastaturereignisse änderten ausgewählten Abschnitt, Fokus und URL. `Enter` öffnete die konkrete Immobilienroute. `0` Domain-Schreibaufrufe.
- Die Rechnungsprüfungslinks sind mit Vitest und vorhandenen Review-Fachtests geprüft. Es fand **kein vollständiger Echtbrowser-Checkout der Rechnungsprüfung** statt.
- Temporäre Vite-Testoberfläche, CDP-Testtreiber, isolierter Edge-Testprozess und Testserver wurden entfernt bzw. beendet. `git diff --cached --check` vor Commit geprüft.

## Vor Freigabe offen

Manuelle NVDA/JAWS/VoiceOver-Abnahme und Tests mit echten, berechtigten Backend-/PostgreSQL-Daten bleiben erforderlich. Keine reale Installation verändert und kein Deployment. Die fünf zuvor offenen Backend-Migrations-/Testdateien sowie der Integrationszweig bleiben unangetastet.
