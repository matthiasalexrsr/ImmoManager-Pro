# ImmoManager Pro – QoL: Sichere Fokusübergabe nach Fachentwurf-Wiederherstellung (18.10.2026)

**Isolierter Frontend-Checkpoint, ohne Deployment.** Ausgangspunkt: Branch `pro/full-handover-20261016`, Commit `3b559c24`.

## Verhalten

- Die geteilte `CustomDraftNotice` übergibt nach **erfolgreichem** `draft.recover()` und der vorhandenen `onRestore`-Fachfeldübernahme den Tastaturfokus an das erste **nachfolgende, bearbeitbare** Feld im selben Layout.
- Die Fokusübergabe erfolgt **erst**, wenn die gespeicherte Recovery-Ansicht verschwunden ist und der Editor freigegeben ist. Während Entwurfssicherung, veränderter Quellakte, Sperre oder laufendem Auftrag wird der Fokus nicht vorschnell in ein gesperrtes Feld gesetzt.
- Auch nach **ausdrücklich bestätigtem erfolgreichem** Verwerfen wird der Fokus in die wieder bearbeitbaren Felder geführt. Während die Löschbestätigung verschwindet, bleibt er auf der weiterhin vorhandenen und benannten Entwurfskomponente erreichbar.
- Versteckte, deaktivierte, schreibgeschützte, inerte und per ARIA gesperrte Steuerelemente werden übersprungen. Die Suche beschränkt sich auf **nachfolgende Geschwisterelemente** der betreffenden Recovery-Komponente, nicht auf fremde globale Suchfelder oder andere Dialoge.
- Hat der aufrufende Fachdialog bereits selbst ein anderes aktives Steuerelement fokussiert, wird seine Entscheidung nicht überschrieben. Ist kein geeignetes Feld vorhanden (z. B. eine andere Einbettung), bleibt die fokussierbare Entwurfskomponente als sicherer Rückfallpunkt; ihr Fokus ist nun visuell markiert.
- Wenn die Quellakte/Sitzung wechselt oder die Wiederherstellung scheitert, wird keine verspätete Fokusaktion für den alten Entwurf ausgeführt. `draft.clear()`, `draft.recover()`, Domain-Speichern und Quellversionsprüfung behalten ihre bisherigen fachlichen Grenzen.

## Prüfungen

- Vitest: `npm.cmd run test -- src/test/CustomDraftFocusQol.test.jsx src/test/CustomDraftNoticeSafety.test.jsx src/test/CustomBusinessDrafts.test.jsx src/test/WorkspaceForms.test.jsx src/test/WorkspaceAnchorDraft.test.jsx src/test/HandoverProtocolEditor.test.jsx src/test/HandoverProtocolsDialog.test.jsx src/test/HousingConfirmationDialog.test.jsx src/test/HousingConfirmationCommand.test.jsx src/test/RentPayments.test.jsx src/test/WorkCenter.test.jsx src/test/MessageCommandRecovery.test.jsx src/test/InternalReplyComposerDraftSafety.test.jsx src/test/FormModal.test.jsx src/test/FormFeedbackRecoveryQol.test.jsx src/test/translations.test.js --maxWorkers=1 --no-file-parallelism`: **139/139 bestanden** in 16 Testdateien; 9 neue Fokus-Regressionsfälle.
- Edge Chromium Headless, isolierte lokale Vite-Testoberfläche auf `127.0.0.1:5189` und CDP-Tastaturbefehle: **PASS** für `Enter` → Wiederherstellung → korrekt fokussiertes bearbeitbares Feld; **PASS** für `Enter` / `Escape` / `Tab` → geschütztes Verwerfen → fokussiertes Eingabefeld. Keine automatische fachliche Speicherung.
- Browser-Akzeptanz mit **synthetischen Entwurfsdaten ohne echten Serververtrag**. Temporäre Browser-Testdateien, Edge-Testprozess und lokaler Testserver nach erfolgreicher Prüfung entfernt/beendet.
- `npm.cmd run lint`: erfolgreich ohne eigene Warnung. `npm.cmd run build`: erfolgreich, mit bekannter nicht blockierender Warnung `INEFFECTIVE_DYNAMIC_IMPORT` für `NotificationInbox.jsx`. `git diff --cached --check` vor dem Commit durchgeführt.

## Abgrenzungen und offene Abnahme

- Keine Änderung an Backend-Migrationen, fachlichen Bestätigungen, Private-Workspace-Zugriffen oder Integrationszweig. Vorhandene fremde Backend-Arbeiten bleiben unangetastet; keine laufende Installation verändert.
- Manuelle NVDA-/JAWS-/VoiceOver-Prüfung, reale Backend-/Provider-/PostgreSQL-Abnahme und vollständige Releasefreigabe bleiben offen.
- Bestehende React-`act()`-Warnungen aus `WorkCenter.test.jsx` sind nicht durch diese Änderung behoben; die Testdatei selbst wurde nicht bearbeitet.
