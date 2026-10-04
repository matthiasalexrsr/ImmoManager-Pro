# UTC des tatsächlichen Notificationwriters – Vorcodeentscheidung

Rootbasis 8703b60. Die isolierten echten PostgreSQL-Gates wurden beendet:
zwei Cursor-/Scope-/NULL-Fälle PASS13,91s (hard120), kompletter 10002-Fall mit
sechs Keysetwalks PASS80,00s (hard300). Keine HTTP-/Migration-/Writecapabilityabnahme.
Der echte Repositorywriter unter Europe/Berlin und America/New_York dagegen:
2 FAIL10,24s (hard90). Keine xfails oder Fixturesperren. UTCwindow Berlin
21:32:24,210921..21:32:24,280595, gespeichert23:32:24,267001; NewYork
21:32:27,544978..21:32:27,615175, gespeichert17:32:27,604507.
Echte Repositorycommits, unabhängige Probeconnection, Returned-/Stored-/Inboxwert
gleich; Quelle ist somit das DateTime-naive-Default func.now() im Writer.
UUID-Schemas/Pools wurden jeweils durch den tatsächlichen finally-Pfad geschlossen.

Vor Änderungen beschlossen: nur NotificationORM.created_at/updated_at/read_at
explizit als UTC-naive führen. Vorhandener UTCNaiveDateTime-Binder normalisiert
bewusst eingegebene aware Zeitpunkte, ohne naive Altwerte neu zu interpretieren.
Eine gemeinsame SQL-Defaultexpression liefert auf PostgreSQL
timezone('UTC', now()); die bisherige Transaktionsanfangssemantik bleibt erhalten.
SQLite bleibt bei CURRENT_TIMESTAMP und seiner historischen Sekundenrepräsentation.
Auch updated_at.onupdate bekommt diesen Ausdruck. Kein Session-/Serverzonenfix,
keine Änderung der übrigen Zeitfelder, keine pauschale Umschreibung gespeicherter
Historie. Diese clientseitigen SQLAlchemy-defaults sind keine serverseitigen
DDL-defaults: die physischen DateTime-Typen und das K2-Schema bleiben gleich.
Alte möglicherweise verschobene naive PostgreSQLwerte sind ohne Herkunft nicht
eindeutig reparierbar und bleiben ein ausdrücklich offener Datenprüfpunkt.

Abnahme: reine Dialektkompilation/physische DDL, danach die beiden tatsächlichen
fehlgeschlagenen Writerfälle, ergänzt um deren updated_at und tatsächlichen
bestehenden globalen Readwriter (aware UTC-bind). Danach nur der SQLitefall,
der native Sekunden-/Mikrosekunden-/NULL-Keysets verwendet, weil dessen Default
berührt wird. Kein erneuter 10002-Vollwalk ohne neue Sorge. Native Gates seriell;
die eigene PostgreSQLinstanz bleibt während der beiden Zonenfälle geöffnet und
wird nach dem gezielten Folgegate explizit beendet.

## Tatsächliche Korrekturabnahme

Source92adf0d: reine UTC-Bind-/Dialekt-/DDL-Prüfung10PASS0,65s (hard30),
Ruff/Diffcheck grün. Beide unverfälschten tatsächlichen PG-Zonenfälle jetzt
2PASS11,44s (hard90), einschließlich created_at/updated_at und tatsächlichem
bestehendem Globalread mit aware UTC-bind. Firstcreated bleibt unverändert;
gespeicherte Zeiten und tatsächliche Rückgaben liegen in den unabhängigen
UTCbefore/after-Fenstern. Kein positiver persönlicher stage_read-/Sidbeleg.
Betroffener SQLite-Default-/Micro-/NULL-Keysetfall1PASS9,16s (hard45), native
Sekundenrepräsentation ausdrücklich geprüft. Keine Wiederholung der zuvor
grünen Großbestandsfälle behauptet. PG1+2+2 verschiedene positive Fälle sind
somit komponiert, kein gemeinsamer neuer5er-Gate und keine Gesamtfreigabe.

Eigener Postmaster2760/Session51498/58112 wurde mit exakt eigenem Clusterpfad
normal beendet (pg_ctl normalExit0). Tatsächliche shutdown-Ausgabe23:36:52CEST,
ServerprozessnormalExit0; danach kein Listener58112. Keine fremden Prozesse,
privaten Daten oder Live126installation angefasst. Native Testprozesse beendet.
