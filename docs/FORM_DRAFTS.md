# Persönliche Formularentwürfe

Optierte gewöhnliche CRUD-Formulare sichern geänderte Formularwerte nach einer kurzen Pause als persönlichen Entwurf. „Wiederherstellen“ übernimmt die Werte ausdrücklich; „Gespeicherten Entwurf verwerfen“ löscht nur den Entwurf. Das Geschäftsobjekt wird ausschließlich durch die bestehende Speicheraktion geändert. Die Speicherung ist serverseitig; der Browser legt keine Formularwerte im Local Storage ab.

Im SQL-Store bleiben Entwürfe über einen Backend-Neustart erhalten. Der Memory-Store hält sie wie seinen Geschäftsbestand ausschließlich während der Prozesslaufzeit; er ist keine dauerhafte Entwurfssicherung.

## Bindung und Berechtigungen

Der Entwurfsschlüssel bindet die authentifizierte Benutzer-ID, Collection, Datensatz-ID beziehungsweise Neuanlage und Formularvariante. Der Request enthält zusätzlich die erwartete Benutzer-ID, damit eine inzwischen gewechselte Anmeldung keine alten Formularwerte unter dem neuen Konto speichern kann. Rolle und Portfolio-Grants werden vor der Verarbeitung und vor Veröffentlichung frisch geprüft. Der gespeicherte Scope-Fingerabdruck muss identisch sein. Direkte Entitäten, fremde Referenzen und geschützte Dateiverweise werden autoritativ geprüft. Ein anderes Konto erhält keine Entwurfswerte. Die schmale Own-Route-Ausnahme erteilt keine allgemeine Benutzerverwaltungsberechtigung.

Die normale Bearbeitungsversion des Geschäftsobjekts bleibt im Entwurf erhalten, einschließlich Mikrosekunden. Die Wiederaufnahme ersetzt sie niemals durch den frischeren Listenstand. Ein späterer Konflikt geht an das vorhandene bewusste CAS-Abgleichpanel. Ein eigener Entwurfs-CAS mit atomarem SQL-UPDATE/DELETE beziehungsweise Memory-Lock schützt vor gegenseitigem Überschreiben durch Fenster. SQL verwendet außerdem die bestehende Kontoverwaltungssperre; Scope-Entzug kann keinen begonnenen Entwurfs-Write unbemerkt erweitern.

## Speichergrenzen und Fehler

`FORM_DRAFT_TTL_DAYS` erlaubt 1–365 Tage, Standard 7. `FORM_DRAFT_MAX_BYTES` erlaubt 1024–16777216 UTF-8-Bytes pro vollständigem Entwurfsumschlag, Standard 262144. Ungültige Einrichtung liefert `DRAFT_CONFIGURATION_INVALID`; ein zu großer Entwurf liefert `DRAFT_TOO_LARGE` mit korrigierbarem Hinweis. Es gibt keine Gesamtzahlgrenze für Geschäftsdatensätze oder Benutzer. Abgelaufene Entwürfe werden nicht wiederhergestellt und beim nächsten Zugriff auf ihren Schlüssel gelöscht.

Bei Speicher-, Berechtigungs-, Schlüssel- oder Konfliktfehlern bleiben die aktuellen Formularwerte erhalten; die Oberfläche zeigt den fehlenden Entwurfsschutz und bewusste Wiederholungs-/Prüfaktionen. Sie behauptet keinen erfolgreichen Autosave. Die ausdrücklich beschriftete Schließaktion erlaubt das Verlassen ohne zusätzliche Entwurfssicherung.

## Unklarer Speicherausgang

Unmittelbar vor der bewussten bestehenden Datensatzspeicherung wird nur der private Entwurf mit `submission_pending=true` gesichert. Das ist keine Befehlswarteschlange und führt nichts aus. Wenn die Fachaktion bestätigt erfolgreich ist, wird der Entwurf anschließend bedingt gelöscht. Bei fehlgeschlagener Bereinigung zeigt die Oberfläche „Datensatz gespeichert“, verhindert eine zweite Fachausführung und bietet ausschließlich Cleanup-Retry beziehungsweise Schließen. Bei Netzwerkfehlern oder unklarem Ausgang muss der Benutzer zuerst den aktuellen Bestand prüfen. Auch ein später geöffnetes Fenster sieht den Prüfhinweis und kann nur ausdrücklich nach Bestandsprüfung weiterbearbeiten. Es gibt keinen automatischen Replay und keine Behauptung einer allgemeinen Idempotenz für historische Stammdaten-POSTs.

## Verschlüsselung und Recovery

AES-GCM verwendet einen aus dem vorhandenen unabhängigen stabilen Encryption-Keyring abgeleiteten eigenen `private-form-draft`-Feldkontext. Version und Key-ID gehören zum authentifizierten Header; die Entwurfsidentität gehört zu den authentifizierten Zusatzdaten. JWT-Signierrotation beeinflusst diese Daten nicht. Fehlende alte Schlüssel oder manipulierte Ciphertexte liefern `DRAFT_ENCRYPTION_UNAVAILABLE`, ohne Werte zu ersetzen oder zu überschreiben. Alte Keyring-Einträge müssen auch für vorhandene Entwürfe erhalten bleiben, solange diese noch benötigt werden.

Die vollständige SQL-Sicherung enthält `form_drafts`; die allgemeinen JSON-Teilmengen enthalten sie nicht. `guard_destructive_reset(store)` sperrt vorhandene persönliche Entwürfe vor einem inkompletten Replace/Reset. Der Offline-SQLite-Prüfhook `form_draft_crypto.verify_database(database, configuration, deadline=...)` streamt alle Ciphertexte mit den ausdrücklich gesicherten Schlüsselwerten, ohne Runtime-Fallback. Fehlende Tabellen in älteren Sicherungen sind kompatibel. Die Migration x1 folgt w1 und verweigert einen Downgrade vor jeder DDL-Mutation, wenn noch Entwürfe vorhanden sind.

## Integrierte Sicherungs- und Wartungspfade

Schema, Router und genau abgegrenzte Own-Route-Ausnahmen sind integriert. `clear_all` und der Replace-Import rufen den Entwurfsschutz vor Geschäfts-DML auf; im SQL-Store wird zuerst der gemeinsame Kontoverwaltungsmarker gesperrt, bei PostgreSQL außerdem das Entwurfsjournal gegen gleichzeitige Schreiber. Memory hält `_form_drafts` als privaten Sidecar unter seiner bestehenden Schreibsperre. JSON-Teilexporte enthalten keine Entwurfsciphertexte.

Vollbackup und Vollrestore prüfen jede gespeicherte Entwurfshülle mit dem tatsächlich mitgesicherten unabhängigen Encryption-Keyring. Fehlende alte Schlüssel, falsche Schlüssel, manipulierte Ciphertexte oder unvollständige bestehende Tabellen verhindern die Veröffentlichung eines neuen Ziels. SQL begrenzt die einzelne gelesene Hülle auf das gespeicherte Bytebudget; es gibt keine Grenze für die Anzahl gespeicherter Entwürfe. Der private PostgreSQL-Restorehook streamt einzelne Hüllen innerhalb derselben Offline-Transaktion vor dem Sitzungswiderruf. Sein tatsächlicher PostgreSQL-Nachweis bleibt ein CI-Gate.

`Settings`, der Standalone-Starter, das private Compose-Profil und dessen geschützte Backup-Konfiguration erhalten `FORM_DRAFT_TTL_DAYS` und `FORM_DRAFT_MAX_BYTES`. Ältere vollständige Sicherungen ohne Entwurfstabelle bleiben kompatibel. x1 übernimmt eine vollständig passende, beim additiven Standalone-Start bereits angelegte Tabelle unter Erhalt aller Zeilen; eine beschädigte Struktur wird vor DDL verweigert.

Gemeinsame lokale Abnahme: 96 vollständige/private Recovery- und Konfigurationsfälle bestanden (ein expliziter PostgreSQL-Skip), darunter Quellordner tatsächlich entfernt, frischer authentifizierter Prozess, fremde Runtime-Schlüssel, erhaltener originaler Bearbeitungsstand und keine Fachausführung. Weitere acht reale SQLite/Edge-Abläufe verbinden Bankbelege, mobilen Vertragsdownload und Entwurfswiederaufnahme mit bestätigtem Save/Cleanup. Die Gesamtfreigabe bleibt von den gemeinsamen CI-Gates abhängig.

## UI-Umfang

Explizit optiert sind die generischen CRUD-Adapter sowie Portfolios, Immobilien, Einheiten, Mieter, Kontakte, Instandhaltung, Aufgaben, gewöhnliche Kalendereinträge, Inserate, Interessenten, Besichtigungen, Benachrichtigungsvorlagen, Eskalationsregelpflege, Budgets, Kautionsstammdaten, sonstige Forderungsstammdaten, Mietanpassungen, Verteilerschlüssel, Übergabeprotokolle und Zählerstammdaten. Die ursprünglichen readonly-Forderungsquellen `status`/`statement_id` werden zusätzlich zum Formularsnapshot erhalten.

Accounts, Bookings, Invoices und der geprüfte Vertragswizard bleiben in ihren parallel betreuten eigenen Paketen ohne generischen Opt-in. Passwort-/Benutzerverwaltung, Zahlungs-/Storno-/Guthabenbefehle, Monatsgenerierung, Batch-Ausführung, E-Mail-Sendeaktionen und Abrechnungsfinalisierung sind nicht optiert. Datei-/Uploadbytes und persönliche Sicherheitsfelder werden nicht durch das Formulardraftmodul gespeichert. Kalenderplanung und Zählerablesebefehle behalten ihren gesonderten Ablauf. Die API unterstützt ausschließlich deklarierte gewöhnliche CRUD-Collections; sie ist keine allgemeine JSON- oder Befehlsspeicherung.
