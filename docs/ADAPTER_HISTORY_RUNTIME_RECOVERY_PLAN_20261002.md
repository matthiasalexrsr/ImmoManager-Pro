# Laufzeit und vollständige Wiederherstellung der Adapterhistorie

Vor Implementierung festgelegt: Das getrennte Paket A in
`work/integration-history` ergänzt ein verschlüsseltes dauerhaftes SQL-Journal.
Die fünf zusammengehörenden Tabellen heißen `integration_history_heads`,
`integration_runs`, `integration_run_events`, `integration_run_chunks` und
`integration_history_clears`. Migration `d2a2b3c4d5e6` folgt ausschließlich auf
den tatsächlichen vorhandenen Head `c2a2b3c4d5e6`. Die Root-Integration übernimmt
die folgenden Grenzen; deren vollständiger Nachweis gehört zum gleichen Paket.

1. Metadatenregistrierung in normaler Laufzeit und Alembic. Vor lokalem
   `create_all` muss eine beschädigte/teilweise vorhandene Familie rein lesend
   abgewiesen werden. Die Migration besitzt DDL; ein Validator repariert weder
   Tabellen noch technische Singleton-Zeilen. Die Historie verwendet dieselbe
   `DATABASE_URL` und eigene kurzlebige Sessions auch bei bewusst gewähltem
   Memory-Domänenmodus. Keine unbemerkte RAM-Historie bei Datenbankfehlern.
2. Synthetische Tests erhalten ausschließlich eigene temporäre Datenbanken und
   Schlüssel. Die vorhandene Produktdatenbank und aktive Vorschau bleiben
   unberührt. Eine dauerhafte SQL-Historie darf nicht durch einen späteren
   Business-/Testreset aus der gemeinsamen Metadatenliste gelöscht werden.
3. Vollarchive behalten ihr vorhandenes Format. Eine vollständig fehlende
   Journalfamilie bleibt mit älteren Archiven kompatibel. Jede teilweise Familie,
   beschädigte verschlüsselte Originalausgabe, falsche AAD-Bindung oder falsche
   Schlüsselkonfiguration verweigert die gesamte Freigabe. Entschlüsselung nutzt
   ausschließlich den expliziten Schlüsselring des Archivs, nie den derzeitigen
   Prozessschlüssel. SQL-, SQLite- und PostgreSQL-Offlineschritte benutzen die
   konkreten validierten APIs des Historiepakets.
4. Beweisprüfung erfolgt vor Dateireferenzänderungen, Claimreset, Sitzungswiderruf
   und neuer Signierkonfiguration. Ein fehlgeschlagener Schritt veröffentlicht
   kein Ziel und hinterlässt keinen teilweise gesicherten Sicherheitsabschluss.
   Begonnene externe Adapteraufrufe werden nach Restore als Ausgang ungewiss
   dokumentiert; kein automatischer Replay und keine erfundene Zustellbestätigung.
5. Der bestehende Business-Teiltransfer enthält das Journal nicht. Vorhandene
   Lauf-/Ergebnishistorie muss deshalb ausdrücklich auf das Vollarchiv verweisen.
   Der bereits geplante berechtigte Telemetrie-Clear ist der nachvollziehbare
   Weg, entbehrliche Historie zu löschen. Technische Köpfe und minimale Clear-
   Nachweise bleiben erhalten; sie erzeugen keinen unauflösbaren Resetkonflikt.
   Die Serialisierungs- und Pending-DML-Grenzen der bisherigen Guards bleiben
   erhalten, auch bei realem konkurrierendem Adapterstart.
6. Prüfungen: tatsächliche frische Alembic-Migration, beschädigte Familie vor DDL,
   Legacy-Vollarchiv ohne Journal, echtes verschlüsseltes SQLite-Roundtrip und
   PostgreSQL-Offlineschritt, falscher Archivschlüssel/AAD, offene Ausführung,
   Pending-/Parallel-Reset und bestehende Recovery-/Transfer-/Startuphooks.
   Typ-/Lintprüfung und CI-Gruppen beziehen die neuen Produktmodule ausdrücklich
   ein. Erfolgreiche Coretests allein sind kein vollständiger Recovery-Nachweis.

Die genaue Journal-API und Normalisierung werden am ersten versionierten
Corestand überprüft. Dieses Dokument behauptet noch keine implementierten oder
bestandenen Archiv-/Startuptests für das neue Journal.
