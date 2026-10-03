# Nebenwirkungsfreie Verbindungsprüfung: Root-Komposition

Backendvertrag `a864946`, verschlüsselter Store `e75f857`/`3e15341`; Store
noch nicht global aktiviert. Der UI-Testknopf verwendet nur `connection-test`,
kein festes Mailziel und keinen Fachpayload. Tatsächlich bestätigter Netzwerk-
transport, reine Konfigurationsprüfung, ungültige Einstellungen, Fehler und
unklares Ergebnis bleiben getrennt. Ein wartender Knopf erzeugt keinen zweiten
Aufruf. Eine behebbare Störung erlaubt bewusste Wiederholung. Alte Antworten
werden bei Actor-/Grantwechsel verworfen.

24 UI-Fälle bestanden im gezielten Lauf. Sie prüfen alle drei Sprachkataloge,
konfiguriertes SMTP ohne Fach-/Historyaufruf, verspätete private Antworten und
Fehler, Transportzustände und bewusste Wiederholung. Die neue Backend-/Migration-
Auswahl bestand 12 Fälle: tatsächlicher SQLite-Upgrade-/Downgrade-Neuaufbau und
synthetische verschlüsselte Konfiguration/Probeverträge, ohne Provider-I/O.

Die gemeinsame tatsächliche PostgreSQL-Auswahl hatte zunächst 19 erfolgreiche
Fälle und acht Fixturefehler durch die f2-Metadatenmutation. f2 erzeugt nun
dieselben Indizes ohne Änderung globaler ORM-Metadaten. Der fokussierte zweite
strikte Lauf bestand 10 Fälle ohne Skips, darunter zwei erneute Parentmigrationen
und alle acht offenen HistoryRuntime-Fälle. Damit sind 27 unterschiedliche
native Fälle über beide abgeschlossenen Läufe belegt. Ein neuer kompletter
Gesamtlauf wird nicht behauptet; CI verlangt künftig die gesamten ausgewählten
nativen Fälle mit dem Runner, der Skips und fehlende Testausführung ablehnt.

Rest: zentraler expliziter Legacy-Konvertierungs-/Recoveryweg vor globaler
Storeaktivierung, dauerhafte Connection-/Mappingakte, echte Netzwerkadapter-
abnahme und Browserprüfung der Integrationsseite im freigegebenen Gesamtstand.
Keine Behauptung fertiger TEHA-Schreibaktionen oder WISO-Windows-Importprüfung.
