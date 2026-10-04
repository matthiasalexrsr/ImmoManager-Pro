# Fortsetzbare operative Verarbeitung – minimaler P1-Entwurf

Stand: 2. Oktober 2026. Prüfgrundlage: Release127, Laufzeitcode von `68256f4`, Browserprüfstand `7ccee8ca4518966d1dbb07ef625eb31d2133337a`. Dies ist ein Architekturentwurf; keine der nachfolgend beschriebenen Tabellen oder Funktionen wurde durch den Prüfagenten implementiert.

## 1. Belegter Ausgangspunkt und unveränderte Zusagen

Im vollständigen SQL-/Edge-Lauf waren beim Beginn des Korrespondenzfalls 182 Mietforderungen vorhanden. 124 waren positiv offen und vor dem angefragten Stichtag 2026-11-05 fällig; 120 stammten aus fünf vorhergehenden Abrechnungsfixtures mit je 24 absichtlich nur teilweise bezahlten Monatsforderungen. Der globale operative Lauf mit `max_items=100` scheiterte beim 101. neuen Benachrichtigungseintrag. Die Tabellen `operational_dispatches`, `operational_occurrences` und `operational_ticks` waren nach dem Fehler jeweils leer: vollständiger Rollback, keine Teilveröffentlichung.

Der Ablauf in `backend/services/operational_schedule.py` ist: globale Sperre → `resolve_alerts` → Serien → Kalenderfristen → `_notifications` → Korrespondenzprojektion → Laufbeleg. `_notifications` verbraucht das gemeinsame Budget, bevor die Korrespondenz überhaupt erreicht wird. Ferner materialisieren `list_tasks`, `list_rent_charges`, `list_receivables`, `schedules`, `occurrences` und `resolve_alerts` große Listen. `_Budget.scan` bricht bei `max(10000, limit*20)` oder nach 30 Sekunden den ganzen Lauf ab. `catch_up` wirft bei einer weiteren passenden Serieninstanz hinter dem Limit, anstatt eine Fortsetzungsposition zurückzugeben.

Die atomare Legacysemantik ist durch `test_full_catchup_and_limit_are_atomic_across_multiple_series` und den echten PostgreSQL-Test `test_pg_catchup_budget_rolls_back_whole_transaction` geschützt. Diese Tests bleiben bestehen. Der P1-Ersatz ist ein neuer Dienst mit ausdrücklich anderer, sichtbarer Jobsemantik; keine versteckten Zwischencommits im alten `operational_tick`.

Der globale Endpunkt bleibt installationsweit. `PortfolioScopeMiddleware` blockiert ausgewählte Portfolios vor `/tasks/operational*` ausdrücklich. Eine allgemeine Aufweichung würde Journal- und Laufdaten offenlegen. Ein gesonderter künftiger fachlicher Aktualisierungsendpunkt für ausgewählte Portfolios braucht eigene Rechte und Ausgabenprüfungen.

## 2. Kleinster dauerhafter Kern: drei zusätzliche Tabellen

SQLite und PostgreSQL, vorhandenes SQLAlchemy, kein zusätzlicher Broker und keine neue Schedulerbibliothek.

| Tabelle | Kernfelder und Zweck |
|---|---|
| `operational_jobs` | `id`, `actor_id`, `idempotency_key`, `request_hash`, `semantics_version`, unveränderliche Stichtags-/Zeitraumparameter, Zustand, Revision, Anfang/Ende, dauerhafte Ergebniszähler. Eindeutig `(actor_id, idempotency_key)`; dieselbe Kennung mit anderem Requesthash ist ein Konflikt. |
| `operational_job_lanes` | `id`, `job_id`, `family`, gegebenenfalls Regel-/Quellart, Zustand, versionierter Cursor, obere Scanposition, `lease_token`, `lease_owner`, `lease_expires_at`, monotoner `fence`, `last_served`, Scan-/Fortschrittszähler. Eindeutig `(job_id, family, partition_key)`. Index auf Zustand/Fälligkeit/letzter Bedienung. |
| `operational_work_items` | `id`, `lane_id`, stabile fachliche Kandidatenkennung, Quelltyp/-ID, geprüfter Quell-/Regelstand, Aktion, Zustand, Revision, Versuchszähler, nächster Versuch, begrenzter Fehlercode, Ergebnisreferenz. Eindeutige Kandidatenkennung je Lane; keine Passwörter, vollständigen Schreiben oder Finanzbelegkopien im Jobpayload. |

Eine Lane ist eine unabhängig fortsetzbare Arbeitsliste. Mindestens getrennt: Alert-Auflösung, Aufgabenserien, Kalenderserien, Aufgaben-/Wartungsfristen, offene Mietforderungen, sonstige offene Forderungen, fällige Aufgaben, Vertragsende, Eskalationen und bestätigte Korrespondenz. Eskalationen besitzen zusätzlich eine Position aus Regel-ID und Quell-ID. Ein überfüllter Benachrichtigungslauf kann die Korrespondenz-Lane damit weder zurückrollen noch dauerhaft ausschließen.

Arbeitslisteneinträge werden nur für notwendige fachliche Arbeit angelegt. Schon unverändert veröffentlichte oder bewusst gelöschte Ziele werden als No-op gezählt; bei jedem fünfminütigen Frischelauf Millionen fertiger Duplikate anzulegen wäre selbst ein Skalierungsfehler. Erledigte Arbeitslisteneinträge dürfen später nach einer definierten Aufbewahrungsregel verdichtet werden; die vorhandenen dauerhaften Vorkommens-/Versandidentitäten und Lösch-Tombstones bleiben erhalten.

## 3. Ein Durchlauf besitzt begrenzte Seiten, keinen Gesamtbestandsdeckel

1. Jobanlage speichert die vollständigen Parameter und alle benötigten Lanes. Die Antwort enthält die Job-ID; verlorene Antworten führen beim Wiederholen zur gleichen ID.
2. Ein Worker beansprucht eine fällige Lane in einer kurzen eigenen Claim-Transaktion. Ältere, zuletzt seltener bediente Lanes werden bevorzugt. Neue große Jobs verdrängen alte kleine Jobs nicht dauerhaft.
3. Entdeckung liest eine SQL-Keysetseite, beispielsweise 64 Quellen plus ein weiteres Element. Die Cursorreihenfolge basiert auf unveränderlichen Quellschlüsseln, mit oberer Startposition. Niemals `OFFSET`, vollständige `list_*`-Ergebnisse oder vollständige Mengen aller Vorkommen laden.
4. Neue notwendige Kandidaten und die neue Entdeckungsposition werden gemeinsam festgeschrieben. Stirbt der Prozess davor, bleibt die alte Position; danach liegen alle übergangenen Kandidaten dauerhaft in der Arbeitsliste. Fertigstellung einer Quellseite darf nur behauptet werden, wenn jedes Element entweder dauerhaft eingeplant oder nachweislich als No-op ausgewertet wurde.
5. Ein kleines Verarbeitungspaket lädt fällige Arbeitslisteneinträge. Jede fachliche Wirkung, ihr vorhandener Wiederholungsschlüssel und der Zustand des zugehörigen Eintrags werden gemeinsam in einer kurzen Transaktion geschrieben. Der Arbeitslisten- und Lanefortschritt sowie Ergebniszähler liegen in derselben Transaktion.
6. Nach ausgeschöpftem Seiten-/Zeitbudget endet das Paket regulär mit `has_more` bzw. Jobzustand `running`. Das Budget ist kein Ausnahmezustand. Folgende Pakete setzen an der dauerhaften Position fort. Der Worker bedient anschließend eine andere Lane.

Zur kleinsten ersten Implementierung genügt eine aktive Lane je Paket; damit kann der Legacy-`OperationalLockORM` als kurze gemeinsame fachliche Sperre zunächst erhalten bleiben. PostgreSQL kann Claims später parallel auswählen; längere Planung und CPU-Arbeit halten diese Sperre nicht. Der Claim alleine erlaubt noch keinen fachlichen Schreibzugriff.

Zeit- und Seitenwerte sind positive konfigurierbare Arbeitsbudgets. Der Server bleibt auch mit niedrigen Werten vollständig fortsetzbar. Ein Prozess-/SQL-Zeitlimit bricht das aktuelle Paket ab, nicht schon bestätigte Pakete anderer Lanes. Wird eine einzige Quelle zu teuer, erhält sie einen sichtbaren Einzelfehler mit Wiederholungspfad und blockiert keine ganze Quellenfamilie.

## 4. Claim, Lease und Fencing über mehrere Prozesse

PostgreSQL: kurzer Claim mit Zeilensperre, bei paralleler Auswahl `SKIP LOCKED` oder äquivalentes bedingtes Update. SQLite: kurzer Writerbeginn und bedingtes Update. Die Lease verwendet Datenbankzeit, einen neuen zufälligen Claimtoken und einen erhöhten Fencezähler. PostgreSQL braucht für den abschließenden Ablaufcheck reale Datenbankzeit wie `clock_timestamp()`, nicht das während einer Transaktion konstant bleibende `now()`. Ein Prozess darf nie aufgrund seiner eigenen Uhr oder seines lokalen Locks allein schreiben.

Für das Verarbeitungspaket gilt die konsistente Sperrreihenfolge: aktuelle Kontoverwaltung/Rechte → vorhandene operative Sperre → Lane → benötigte Fachquellen in stabiler Reihenfolge. Die Claim-Transaktion ist davor bereits abgeschlossen und nimmt keine umgekehrte Kontosperre. Die konkrete Reihenfolge wird vor Umsetzung mit den vorhandenen Finanz-/Vertragsdiensten abgeglichen.

Vor fachlichem DML werden Actor, Lanezustand, Token, Fence und Lease geprüft. Unmittelbar vor Commit erfolgt ein bedingtes Laneupdate mit demselben Token/Fence und einer noch gültigen Lease. Trifft es keine Zeile, rollt das gesamte aktuelle Paket einschließlich aller Ziele zurück. Fortschrittsupdate und fachliche Wirkung teilen eine Datenbanktransaktion. Ein alter Worker kann nach Leaseübernahme daher keinen Cursor oder Fachbeleg mehr veröffentlichen. Eine abgelaufene Lease verlängert sich nicht nachträglich nur deshalb, weil der alte Worker doch fertig geworden ist.

DB-Zeilensperren schützen das konkrete Paket zusätzlich; Lease/Fence schützen das Wiederaufnehmen zwischen Paketen. Lange laufende SQL-Anweisungen brauchen zum Paket passende Statement- und Lockbudgets. Heartbeat/Renewal erfolgen nur unter aktuellem Token/Fence. Auth- oder Portfolioentzug stoppt die weitere Arbeit mit sichtbarem Zustand `attention`, bereits bestätigte fachliche Belege bleiben erhalten.

## 5. Fachliche Identität, Änderungen und Fehler

Vorhandene `operational_occurrences` und `operational_dispatches` bleiben die fachlichen Duplikatsperren. Der Job selbst ist keine neue Identität für dieselbe Serieninstanz oder Benachrichtigung. Bewusst verschobene/gelöschte Ziele behalten ihre Tombstones. Geprüfte Korrespondenz verweist weiter auf Freigabehash und Verwaltungsdatum; ein Worker erzeugt keine neue Schreibenfassung.

Zwischen Entdeckung und Verarbeitung kann eine Quelle geändert oder bezahlt werden. Das Paket lädt sie deshalb frisch unter ihren geeigneten Fachsperren und prüft den geplanten Stand. Eine nicht mehr zutreffende Bedingung wird ausdrücklich als überholt/No-op abgeschlossen; eine weiterhin notwendige, aber geänderte Aktion wird mit ihrem aktuellen Stand neu geplant. Die alte geprüfte Fassung bleibt ein Beleg des tatsächlichen Planungsversuchs. Kein altes Payload darf eine mittlerweile bezahlte Forderung als offen veröffentlichen.

`as_of` und Zeitraum sind feste Jobparameter, jedoch kein behaupteter vollständiger historischer Datenbanksnapshot. Neue oder geänderte Quellen, die hinter einer bereits bestätigten Cursorposition liegen, werden durch den nächsten vollständigen Frischelauf erfasst. Dies ist in API/UI und Tests ausdrücklich zu beschreiben; ein Keysetcursor alleine liefert keine Momentaufnahme bei gleichzeitigen Änderungen. Später kann eine Quelländerungs-Queue die Latenz verringern, ist für den ersten korrekten Kern nicht erforderlich.

Transiente Sperr-/Verbindungsfehler rollen nur das aktuelle Paket zurück und bekommen einen begrenzten Rückoff mit dauerhaftem nächsten Versuch. Fachlich ungültige Quellen erhalten ein Fehlerobjekt mit Quellreferenz und konkreter Korrekturaktion; danach folgen andere Einträge. Wiederholung oder Überspringen sind ausdrückliche CAS-Befehle, keine stille Löschung. Ein Job mit ungelösten Fehlern heißt `attention` oder `completed_with_issues`, niemals uneingeschränkt `completed`. Innerhalb eines Pakets darf ein fehlgeschlagener Flush nicht durch Weiterarbeiten im defekten Sessionzustand kaschiert werden: Paketrollback oder geprüfter Savepoint pro Quelle.

Serien benötigen eine neue Seitenfunktion neben dem Legacy-`catch_up`: fester ursprünglicher Anker, Regelversion, absoluter Vorkommensindex bzw. Datum, letzte bestätigte Position und `has_more`. `COUNT`, Monatsende und Ein-offenes-Kind-Politik behalten ihre geprüfte Bedeutung. Die Gesamtzahl einer Serie wird niemals durch das Paketlimit ersetzt. Abfragen prüfen vorhandene Vorkommen mit Index/`EXISTS` für die betrachtete Seite statt sämtlichen alten Vorkommen im RAM.

## 6. API und sichtbarer Ablauf

Neue installationsweite API, beispielsweise `POST /tasks/operational-jobs`, `GET /tasks/operational-jobs/{id}`, `POST .../{id}/continue`, `POST .../{id}/cancel`, `POST .../{id}/items/{item_id}/retry`. Bestehende Middleware- und Rollenregeln bleiben bestehen. Befehle tragen Wiederholungsschlüssel und erwartete Revision. Listen und Einzelfehler sind paginiert und geben nur erlaubte Quellreferenzen aus. Der Jobkopf enthält Zähler und Links, keine wachsende JSON-Liste sämtlicher Ziel-IDs; Ergebnisreferenzen werden ebenfalls über Keysetseiten gelesen.

Die Oberfläche zeigt abgeschlossene Teile, noch ausstehende Arbeit und konkrete Fehler pro Arbeitsart. „Weiterverarbeiten“ setzt denselben Job fort. Verbindungsausfall oder Schließen der Seite beendet keinen bestätigten Auftrag. Abbrechen verhindert weitere Pakete und bezeichnet bereits erstellte Aufgaben/Termine/Meldungen wahrheitsgemäß; es behauptet keine Rücknahme. Eine ausdrücklich neue Auswertung erstellt einen neuen Job. Der Scheduler erzeugt nicht bei jedem Intervall unbegrenzt weitere identische Jobs: pro Parametersatz/Actor höchstens ein aktiver Nachfolger, danach ein neuer Frischelauf.

## 7. Migration, Recovery und Ablösung

Additive Migration der drei Tabellen mit benötigten Indizes. Vor Produktbetrieb Tabellenpräsenz komplett oder komplett abwesend erkennen; ein unvollständiger Satz ist ein reparierbarer Schemafehler. Historische lokale Datenbanken werden anhand ihrer tatsächlichen Tabellen geprüft, ohne blindes Alembicstempeln. In `full_recovery._database_state` muss der vollständig fehlende neue Tabellensatz ausdrücklich als alte vollständige Sicherung zulässig sein: seine Prüfung aller `Base.metadata`-Tabellen würde ältere Sicherungen nach bloßer Modellregistrierung sonst ablehnen. Teilweise vorhandene neue Tabellen oder unvollständige Spalten bleiben Fehler.

SQL-Modellregistrierung/Startup, MemoryStore-State, Testfixtures und alle drei vollständigen Wiederherstellungswege werden gemeinsam ergänzt. Die vorhandene physische Sicherung erhält alle Tabellen. Die logische Teilübertragung darf Jobs, Cursor und Tombstones weder teilweise ersetzen noch stillschweigend fremde IDs neu zuordnen; bestehende Ablehnung unsupported business data bleibt aktiv. Integritätsprüfung vor Veröffentlichung kontrolliert Job/Lane/Item-Beziehungen, Cursorformatversionen, Zustands-/Zählerkonsistenz und vorhandene fachliche Ergebnisreferenzen. Absichtlich gelöschte Fachziele dürfen als vorhandene Tombstones fehlen.

Restore verwirft alle übernommenen aktiven Claims, erhöht deren Fence, löscht Tokens/Leaseowner und setzt nicht fertig bestätigte Arbeit auf wiederaufnehmbar. Neue Claims erhalten neue zufällige Tokens; dadurch können zurückgespielte ältere Fencezahlen keine alten Worker legitimieren. Offline-Writerstop und bisherige Sessioninvalidierung bleiben erforderlich. Es wird nach Restore nichts unter alten Benutzerrechten automatisch weitergeschrieben: frische Actorprüfung und ausdrücklich konfigurierter Scheduler sind Voraussetzung.

Zuerst einen vollständig abgenommenen neuen Jobpfad bereitstellen; den Scheduler und die neue UI danach bewusst darauf umstellen. Der alte atomare Endpunkt kann vorübergehend kompatibel bleiben. Ihm heimliche Paketcommits zu geben würde das Rückgabeverhalten, Wiederholungen und bestehende Tests brechen.

## 8. Erforderliche Abnahme, bevor Scheduler/UI umgestellt werden

- 124 und anschließend wesentlich mehr offene Quellen, Paketbudget beispielsweise 7: Benachrichtigungen werden über mehrere bestätigte Pakete vollständig erzeugt; Korrespondenz kommt trotz weiter bestehender Benachrichtigungsarbeit zum Zug.
- Abbruch vor und nach Entdeckungscommit sowie vor und nach fachlichem Paketcommit: gleiche dauerhafte Job-ID, keine verlorene Quelle und kein doppeltes Ziel.
- Zwei echte PostgreSQL-Prozesse mit Leaseablauf/Übernahme: alter Token/Fence kann weder Ziel noch Cursor veröffentlichen. SQLite-Reihenfolge separat prüfen.
- Budgetende, sehr große fertige Tombstonebestände und eine fehlerhafte Quelle: reguläre Fortsetzung mit begrenztem Speicher; andere Lanes kommen voran. Quellabfragen nachweislich begrenzt, kein verborgenes `list_*`.
- Quelle bezahlt/geändert/gelöscht, Regel geändert, bewusste Zielverschiebung/-löschung, deaktivierter Actor bzw. entzogenes Portfolio während eines Pakets: frische Fachprüfung und richtige atomare Wirkung.
- Ursprünglicher Monatsanker, `COUNT`, Ein-offenes-Kind-Regel, jahrzehntelange tägliche Serie und Wiederaufnahme mitten in einer Serie: dieselben fachlichen Termine wie die geprüfte Regel, keine durch Paketgrenzen verkürzte Serie.
- Vollsicherung/Restore mitten im Job über alle unterstützten Wege: keine alte Lease aktiv, vollständige Fortsetzung, noch vorhandene Vorkommens-/Versandidentitäten. Partieller Tabellen-/Claimsatz wird vor Veröffentlichung abgelehnt.
- Tatsächlicher Browserablauf bei Antwortverlust, Neuladen, Abbrechen, Einzelfehlerkorrektur und Fortsetzen. Abschlussstatus entspricht wirklich allen Lanes und ungelösten Einträgen.

Diese Tests ergänzen die bestehenden atomaren Legacytests; sie ersetzen sie erst mit einer ausdrücklich entschiedenen API-Ablösung. Last- und Laufzeitwerte werden auf dokumentierter Hardware gemessen. Dieser Entwurf liefert keine ungemessene Laufzeit- oder 20-Jahres-Garantie.
