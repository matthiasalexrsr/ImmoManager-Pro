# ImmoManager Pro – QoL: Geschütztes Verwerfen wiedergefundener Fachentwürfe (18.10.2026)

**Isolierter Entwicklungsstand; nicht ausgerollt.** Ausgangspunkt: `pro/full-handover-20261016`, Commit `5eb9bd3c`. Keine Änderung an Backend oder Geschäftslogik.

## Verbesserung

- `CustomDraftNotice` verlangt vor der Löschung eines wiedergefundenen Entwurfs eine **zweite ausdrückliche Bestätigung**. Der erste Klick auf `Entwurf verwerfen` ruft `draft.clear()` nicht auf.
- `Entwurf behalten` und `Escape` brechen die Frage ohne Lösch- oder Fachaktion ab und führen den Fokus zur ursprünglichen Schaltfläche zurück. `Strg/Cmd+Enter` wird innerhalb der offenen Bestätigung abgefangen.
- Der Fokus liegt beim Öffnen der Bestätigung zunächst auf `Entwurf behalten`; `aria-expanded`, ein nur bei geöffneter Frage gesetztes `aria-controls` und eine benannte Gruppe machen den Zustand erkennbar.
- Ein synchroner Busy-Guard verhindert doppelte Löschaufrufe; während der Anfrage und bei externer Sperre bleiben Aktionen gesperrt. Ein später eintreffendes Ergebnis einer älteren Formularsitzung überschreibt keine neue Sitzung.
- Schlägt die Löschung fehl, bleibt der Entwurf samt Bestätigung erhalten. Der Fehler wird sichtbar, ein erneuter Versuch erfolgt **nur durch erneuten bewussten Klick** auf `Endgültig verwerfen`. Nach bestätigtem Abschluss wird der verbleibende Hinweis fokussiert.
- Die gemeinsame Aktion ist nun im offiziellen Katalog als `ui.form.discardDraft` in Deutsch, Englisch und Spanisch enthalten und wird auch im normalen `FormModal` genutzt. Vorhandene Übersetzungen für Behalten und endgültiges Löschen werden wiederverwendet.
- Die bestehenden Quellvergleichs-, Wiederherstellungs-, Revisions- und Berechtigungsmechanismen werden nicht verändert.

## Tatsächliche Prüfungen

- `npm.cmd run test -- src/test/CustomDraftNoticeSafety.test.jsx src/test/CustomBusinessDrafts.test.jsx src/test/WorkspaceForms.test.jsx src/test/FormModal.test.jsx src/test/FormFeedbackRecoveryQol.test.jsx src/test/HandoverProtocolEditor.test.jsx src/test/HandoverProtocolsDialog.test.jsx src/test/HousingConfirmationDialog.test.jsx src/test/HousingConfirmationCommand.test.jsx src/test/RentPayments.test.jsx src/test/WorkCenter.test.jsx src/test/MessageCommandRecovery.test.jsx src/test/translations.test.js --maxWorkers=1 --no-file-parallelism`: **115/115 bestanden**, 13 Testdateien, darunter sieben neue Regressionen.
- `npm.cmd run lint`: erfolgreich, nach Beseitigung eines ungenutzten Testimports ohne eigene Warnung.
- `npm.cmd run build`: erfolgreich, mit der bereits bekannten, nicht blockierenden Warnung `INEFFECTIVE_DYNAMIC_IMPORT` zu `NotificationInbox.jsx`.
- `git diff --cached --check`: erfolgreich.

## Offen und ausdrücklich nicht behauptet

- Die Regressionen wurden in Vitest/jsdom geprüft. **Keine neue native Browser-/Screenreader-Abnahme** für `CustomDraftNotice`, kein realer Provider-/Backend-End-to-End-Nachweis und keine PostgreSQL-Migrationsfreigabe.
- Die WorkCenter-Testdatei gab trotz erfolgreicher Tests React-`act()`-Warnungen aus; das ist ein separater Testqualitäts-Hinweis.
- Keine laufende Installation verändert, kein Deployment. Fremde offene Backend-Migrations- und Backend-Testdateien sowie der zentrale Integrationszweig bleiben unangetastet.
