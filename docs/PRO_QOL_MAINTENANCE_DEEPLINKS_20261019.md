# ImmoManager Pro – QoL: Wartungs-Projektakte mit direkten Seitenverknüpfungen (19.10.2026)

**Isolierter Frontend-Checkpoint, nicht ausgerollt.** Ausgangspunkt: Branch `pro/full-handover-20261016` bei Commit `9449271a`. Die bestehenden fremden Backend-Migrations- und Backend-Teständerungen, zentrale Integrationsarbeit und produktive Installationen sind nicht Teil der Änderungen.

## Bedienung und Navigation

- Die sieben vorhandenen Reiter der Wartungs-Projektakte (`overview`, `work`, `appointments`, `procurement`, `costs`, `protocols`, `documents`) sind nun direkt über `/maintenance/:id?tab=...` adressierbar. Ein fehlender oder unbekannter Wert führt sicher zur Übersicht.
- Ein Tabwechsel ändert die echte Browser-URL ohne fachliche Aktion, erhält vorhandene andere Query-Parameter/Hash und ist per Zurück/Vorwärts rückgängig. Die bestehenden `role=tab` und Tabpanel-Beziehungen behalten ihre Semantik. Nur der aktive Reiter ist in der normalen Tab-Reihenfolge; `Pfeil links/rechts`, `Home` und `End` setzen Reiter, URL und Tastaturfokus.
- Eine wiederverwendete `RelatedPageLinks`-Leiste bietet bei tatsächlicher Zuordnung Links zur **Instandhaltungsansicht der Immobilie** (`/properties/:id?tab=maintenance`), zur **Einheitenakte** (`/units/:id`) und zu den **Buchungen der Immobilie** (`/bookings?property_id=...`). Sie verändert keine Daten.
- Im Bereich **Rechnungen & Kosten** können zugeordnete Rechnungen mit tatsächlicher ID direkt in der Rechnungsprüfung (`/invoice-review/:id`) und Zahlungen bei bekannter Buchungs-ID als konkreter Buchungsdatensatz (`/bookings?booking_id=...`) geöffnet werden. Ohne diese ID erscheint kein irreführender Link.
- Die Linkleisten-Überschrift und die neuen Links sind in den vorhandenen feature-spezifischen Deutsch/Englisch/Spanisch-Wörterbüchern übersetzt. Für andere Seiten bleiben die bisherigen Standardbeschriftungen des gemeinsamen Bausteins unverändert.

## Layout, Fokus und Grenzen

- Visueller Fokusrahmen und mindestens 44 px hohe Reiter verbessern die Tastaturbedienung. Die breite Reiterleiste scrollt innerhalb ihres Bereichs statt die ganze Seite horizontal zu erweitern.
- Rechnungs- und Buchungslinks sind umbruchfähig, mit Fokusrahmen und auf sehr schmalen Viewports (`max-width: 480px`) einer CSS-Mindesthöhe von 44 px.
- Keine Änderung an POST-/PATCH-/DELETE-/Idempotenzkommandos, Quellrevisionen, Berechtigungen oder Entwurfspersistenz. Die Backend-Router und verknüpften Datensatz-IDs wurden nicht verändert.

## Tatsächlich geprüfte Abläufe

- Vitest: `npm.cmd run test -- src/test/MaintenanceProject.test.jsx src/test/RelatedPageLinks.test.jsx src/test/EntityLinks.test.jsx src/test/PropertyDossier.test.jsx src/test/PartyUnitNavigation.test.jsx src/test/TenantAccount.test.jsx src/test/InvoiceReview.test.jsx src/test/ServiceContracts.test.jsx src/test/BookingReviewWorkflow.test.jsx src/test/BookingReviewIndependent.test.jsx src/test/Dunning.test.jsx src/test/CustomBusinessDrafts.test.jsx src/test/ShellNavigation.test.jsx src/test/WorkspaceNavigation.test.jsx src/test/translations.test.js --maxWorkers=1 --no-file-parallelism`: **120/120 Tests bestanden in 15 Testdateien**. Darin fünf neue Wartungs-Navigationsfälle sowie die erweiterte Prüfung lokalisierter Linkleisten.
- Echte Microsoft-Edge-(Chromium-)Headless-Session mit **wirklich gerenderter MaintenanceProject-Komponente**, synthetischen Projektdaten, isolierter Vite-Testoberfläche auf `127.0.0.1:5198` und ersetzten GET/POST-Funktionen: **PASS** bei **320, 375 und 1280 px** ohne globales horizontales Überlaufen; die Verknüpfungsleiste zeigt drei echte Ziele, die Reiter bleiben scrollbar. Im Kostenbereich sind Rechnung und Buchung anklickbar. `Pfeil rechts`/`Home` wechselten Abschnitt, URL und Fokus. `Enter` öffnete genau `/properties/p1?tab=maintenance` bei **0** Fachschreibaktionen.
- Die Edge-Session prüfte den Stand vor der abschließenden rein visuellen Erhöhung der Rechnungs-/Buchungslink-Mindesthöhe auf kleinen Bildschirmen. Für diese nachträgliche CSS-Regel liegt kein erneuter separater Edge-Messwert vor.
- `npm.cmd run lint`: erfolgreich. `npm.cmd run build`: erfolgreich. Die bisherige nicht-blockierende `INEFFECTIVE_DYNAMIC_IMPORT`-Warnung zu `NotificationInbox.jsx` ist unverändert. `git diff --cached --check` vor Commit erfolgreich.
- Temporäre Browser-Testdateien, isolierter Edge-Prozess und lokaler Vite-Testserver nach dem Durchlauf entfernt/beendet.

## Noch offen für Release

Keine vollständige reale Daten-/Server-/Provider-/PostgreSQL-End-to-End-Abnahme und keine manuelle NVDA/JAWS/VoiceOver-Prüfung. Im PropertyDossier-Test wurden weiterhin die bekannten React-`act()`-Warnungen beobachtet; der Testbestand war erfolgreich. Fünf bereits fremd geänderte Backend-Dateien bleiben uncommittet und unangetastet. **Kein Deployment.**
