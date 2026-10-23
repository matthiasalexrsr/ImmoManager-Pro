# Fortsetzung des vollständigen Implementierungsauftrags – 16.10.2026

## Tatsächlich vorgefundener Stand

Zentraler Checkout `codex/claude-review-20261013` sauber auf `04021da57e009419ae8d07346ad890fdabad6533`; unverändert. Der eigene Gesamtentwicklungszweig `pro/full-handover-20261016` war sauber auf `05e71b0802978949f2cb0f6b5dc9229753254dc1`. Er enthält bereits Nachrichten-, Verbindungs- und Bankimportpakete. Paket-Arbeitskopien werden ausschließlich gelesen. Ihre historischen Teilergebnisse sind keine Prüfung dieses Gesamtzweigs. Die früheren Entwicklungshelfer wurden laut ihren Abschlussprotokollen durch das Codex-Nutzungslimit beendet; diese Fortsetzung bearbeitet den Code direkt.

Kein Zugriff auf Anwenderdaten, produktive Konfigurationen oder Liveports 8000/8765. Keine Anbieteraktion, Zahlung, Nachricht, Veröffentlichung, Migration einer Anwenderinstallation oder Auslieferung. Der Gesamtauftrag und die unabhängige Codex-Abnahme bleiben vollständig bestehen.

## FinTS: dauerhaften Claim korrekt abschließen

Der gemeinsame Bank-/Connection-Lauf `bank-connection-integrated-sql-b84f9a9e555349a9aa9bdbfd32f81c79` enthielt 105 bestandene und drei fehlgeschlagene Fälle. Zwei Fehler beruhten auf einem tatsächlichen Integrationsfehler: FinTS legte beim Ergebnisabschluss erneut denselben bereits bestätigten Business-Command-Beleg an. Der aktuelle Belegvertrag erlaubt diese doppelte Neuanlage bewusst nicht.

`backend/services/bank_fints.py` speichert jetzt die Revision des bestätigten Claims und schreibt ausschließlich diesen Beleg mit `advance_command` fort. Identität, Fingerprint und ursprünglicher Erstellungszeitpunkt bleiben erhalten. Die erneute Prüfung von Bankkonto, Akteur, Sessionrevision und Zustand bleibt unverändert. Belegfortschreibung und Sessionergebnis liegen in derselben Transaktion. Ein zwischenzeitlich veränderter Beleg erzeugt 409; die späte Antwort überschreibt weder fremden Zustand noch den laufenden Claim.

Neue Regressionen prüfen die tatsächliche Sichtbarkeit des Claims während des Adapteraufrufs, unveränderte Belegidentität, identische Wiederholung ohne zweiten Adapteraufruf sowie die atomare Zurückweisung einer verspäteten Antwort nach Belegänderung.

Der dritte Fehler war eine veraltete Migrations-Testannahme: `run_migrations` erreicht den aktuellen Merge-Head, nicht mehr ausschließlich den früheren Connection-Pakethead. Der Test prüft nun zuerst weiterhin exakt die veröffentlichte Paketrevision einschließlich verweigertem verlustbehaftetem Downgrade. Anschließend prüft er zusätzlich den vollständigen aktuellen Graphen, Startfähigkeit und bytegleiche vorhandene Verbindungsdaten samt erhaltenem Versuchsbeleg. Keine Schutzassertion wurde entfernt.

## Tatsächlich ausgeführte Läufe dieser Fortsetzung

- `resumed-fints-sql-0b6204c31aa2458d8294036cefd06d0a`: 6/6 bestanden, 32,31 Sekunden; bestehende FinTS-Zustandsfälle nach Produktkorrektur.
- `fints-fenced-final-sql-fee788002de14ddfa021641f68d56bb7`: 9/9 bestanden, 46,64 Sekunden; FinTS einschließlich neuer Gegenproben plus Paket- und Gesamtgraphmigration.
- `fints-fenced-final-memory-ce353ac0505f4639901abf5ac32ab505`: 8/8 bestanden, 9,19 Sekunden; sämtliche FinTS-Gegenproben.

Alle drei Läufe verwendeten den unveränderten Review-Interpreter, eigene Runtimeverzeichnisse und deaktivierte Scheduler. `input.json`, `result.json`, `junit.xml` und `pytest.log` unter `artifacts/pro-tests/` tragen den Ausgangscommit und die tatsächlichen Dateihashes. Dies sind Arbeitsbaumprüfungen; sie werden nicht nachträglich als Prüfung späterer Gesamtänderungen ausgegeben. Es gab keinen übersprungenen Fall in diesen Läufen. Keine Livebankabnahme ist damit behauptet.

Die zusätzliche vollständige Prüfumgebung für die tatsächlich installierte FinTS-Bibliothek wird separat angelegt; ihre Installation und ihr Ergebnis sind erst nach dem tatsächlichen Abschluss zu bewerten.
