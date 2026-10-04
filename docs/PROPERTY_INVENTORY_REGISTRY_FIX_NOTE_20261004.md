# Enger Anschlussfix nach wirklichem HTTP-Gegenbeleg

Root b1fd1ea führte den tatsächlich montierten HTTPpfad mit SQLFachstore aus:
genau503 statt200, 20.77s unter hard150, kein positiver SQLnachweis. Die
vorherigen401-Prüfungen liefen korrekt. Memorypage200 war ein Teilbefund;
Roots weitere Assertion erwartete Vary zu eng, obwohl echte CORS-Middleware
zulässig Origin ergänzt. Das ist getrennt vom SQLsourcefehler.

Tatsächliche dependencies.py erzeugt SQLAlchemyStore mit scoped_session,
sql_store.py behält diesen Registryadapter. Der eigene _engine-Vorvertrag
prüfte bisher ausschließlich Session. Nach Roots expliziter Freigabe löst
der enge Sourcefix zusätzlich **nominalen sqlalchemy.orm.scoped_session**
über dessen eigenen aktuellen Sessionzugriff auf. Ergebnis muss weiterhin
eine echte Session sein. Keine beliebige Callable-/Duckfactory, kein globaler
Store, kein Auth-/Router-/Sharedquellenwechsel. Die Registry wird nicht
entfernt/geschlossen/zurückgesetzt; Caller-DML, identity-map und Bind bleiben.

Der alreadycommitted eigene Boundarytest b21111b ist ein echter positiver
scoped_session(sessionmaker)-Fall mit frischem tatsächlichem SQLUser/Sid,
aktivem CurrentSession-Transactionobjekt, realem Driver und unflushed Dirtyrow.
Er prüft Page+Summary aus tatsächlicher Datenbank, unveränderte Registry-
Session/Transaction/Driver und Kaufpreis0. Cleanup betrifft nur die eigene
Testregistry. Testsource wurde vorbereitet, nicht ausgeführt.

Der separate Sourcefix ersetzt den belegten Fehler, ist aber **noch kein
grüner Native-/HTTPnachweis**. Root übernimmt und prüft actual mounted HTTP,
eigene Registryboundary, Memory-/SQLite-/PG-/Exportkomposition seriell.
