# Mieterdatenauskunft und Profil-Anonymisierung

Der Bereich unter **Mieter → Datenauskunft und Stammdaten-Anonymisierung** steht Eigentümern und Verwaltern mit der tatsächlichen Verwaltungsberechtigung offen. Eine Rolle allein überschreibt keine vom Server entzogene Berechtigung.

## Datenauskunft

Die JSON-Datei enthält das ausgewählte Mieterprofil und ausdrücklich über dessen Verträge verknüpfte Vertrags-, Forderungs-, Zahlungs-, Storno-, Abrechnungs-, Dokumentmetadaten-, Gesprächs- und Übergabedaten. Der Export sucht nicht nach Namen, E-Mail-Adressen oder gemeinsam genutzten Immobilien. Referenzierte, nicht einem Mieter zugeordnete Bankbuchungen werden nur auf Integrität geprüft; ihre Banktexte werden nicht allein durch einen Zahlungsbezug exportiert.

Dateiinhalte und opaque Datei-/Signaturpfade sind ausgeschlossen. Der Export weist Redaktionen und nicht erfasste Bereiche aus. Kontakte, frei zugeordnete Aufgaben, Wartungsfälle, geteilte Objektunterlagen und Auditdaten brauchen eine gesonderte Prüfung. Die Datei ist deshalb kein als rechtlich vollständig erklärter Art.-15-Auszug.

SQL liest jede Sammlung mit Mieter-/Vertrags-Subqueries und lädt Stornos gemeinsam. PostgreSQL verwendet REPEATABLE READ, SQLite einen ausdrücklich begonnenen WAL-Lesesnapshot. Der Memorypfad erzeugt unter derselben Schreibsperre eine getrennte Kopie. Die Ausgabe wird vollständig in einen spooled temporären Speicher geschrieben und oberhalb 1 MiB auf Platte ausgelagert. Das ist eine Speicherstrategie, keine Gesamtgrößengrenze. Erst danach beginnen HTTP-Download und Content-Length; die temporäre Datei wird nach Abschluss oder Abbruch geschlossen. Cache-Control ist private, no-store.

Die reine Beziehungsgrafik und ihre zusätzlichen Tests stammen aus dem bestehenden Assistenz-Chat „Software verbessern“. Die produktive SQL-Eingrenzung, Snapshot-Transaktion, Rechte, Download-, Bestätigungs- und Rollbackpfade wurden im Repository ergänzt und geprüft.

Version 2 ergänzt die tatsächlich gespeicherten Guthabenbelege einschließlich
Verrechnungszahlung und zugehöriger Stornos. Eine Verrechnung ohne passende eigene
Zahlung, Forderung oder Guthabenquelle bricht den Export ab. Die Guthabenstände
zeigen den aktuellen kohärenten Snapshot: verbrauchtes Guthaben wird abgezogen,
Korrekturforderungen derselben Abrechnungskette reservieren die verbleibenden
Mittel. Das ist ein eigener Stand und wird nicht einem historischen Mietsaldo
zugeschlagen. Guthabenänderungen machen eine bereits geprüfte
Anonymisierungsvorschau ungültig. Referenzierte Bankauszahlungen übernehmen keine
Texte oder Dateipfade unzugeordneter Bankbuchungen in den Export.

## Anonymisierung

Die Vorschau zeigt unverändert gespeicherte Unterlagen und Finanzbelege sowie die exakt betroffenen Profilfelder. Aktive Verträge verhindern diese Aktion. Die Bedienung verlangt den vollständigen Namen; das API zusätzlich Mieter-ID und SHA256 des geprüften Datenstands.

Nur Name, Kontakt-/Adressdaten, Zahlungsart, SEPA-Mandatsreferenz und Profilnotizen werden ersetzt beziehungsweise geleert; der Mieter wird archiviert. Verträge, Dokumentinhalte, Nachrichten und Belege bleiben erhalten. Der Umfang ist sichtbar und wird nicht als vollständige Löschung sämtlicher personenbezogener Daten bezeichnet.

Ein anderer Datenstand ergibt409 mit Aufforderung, die Vorschau neu zu laden. Die ursprüngliche Eingabe bleibt sichtbar. Schreibfehler rollen die komplette Profiländerung zurück, auch wenn ein innerer Repositoryaufruf bereits commit verwendet hat. Ein fehlender Mieter ergibt404; fehlerhafte Bestätigung422/409; unvollständige Daten oder fehlender Exportplatz ergeben503 mit Handlungshinweis.

## Prüfnachweise

- Echte Memory-/SQLite-Repositorydaten: Beziehungstrennung, Referenz- und Stornobelege, redigierte Fremdanhänge, unveränderte Originaldaten.
- Tatsächliche zweite SQLite-Session schreibt während des Exports: Profil und Verträge bleiben im alten kohärenten Snapshot.
- SQL-Queries enthalten WHERE und verwenden eine gemeinsame Stornoabfrage; globale Sammlungsmethoden sind im Test verboten.
-9-MiB-Export passiert die frühere8-MiB-Grenze, wird auf Platte ausgelagert und liefert denselben kanonischen Hash.
- Tatsächlicher Commit mit anschließendem Fehler: keine Teiländerung.
- Realer Edge-Browser: privater Download, parallele Änderung,409, erneute Prüfung und explizite Profil-Anonymisierung.

Eine Portfolio-Isolation folgt erst mit dem eigenen Berechtigungspaket. Die aktuelle Verwaltungsauthentisierung gilt installationsweit.
