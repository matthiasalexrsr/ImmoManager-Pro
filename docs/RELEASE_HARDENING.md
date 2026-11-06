# Release-Härtung und Freigabeverfahren

Dieses Dokument beschreibt den Härtungsstand nach dem bisherigen Beta-Tag. Es
ist keine Veröffentlichung eines neuen Installationspakets und keine pauschale
Verkaufsfreigabe. Der vorhandene Tag `v2.0.0-beta.1` bleibt unverändert. Ein neues
öffentliches Paket benötigt eine eigene passende Version und einen neuen Tag.

## Abnahme genau des ausgelieferten Quellstands

Vor einer Veröffentlichung müssen diese drei Workflows auf demselben vollständigen
Commit erfolgreich abgeschlossen sein:

| Prüfung | Erforderlicher Umfang |
| --- | --- |
| `ci.yml` | Vollständige Frontend-/Backend-Prüfung, Memory/SQLite mit beiden Python-Versionen, PostgreSQL, Windows-Pfade, echte Browser-/Dokumentabläufe und Deployment |
| `desktop.yml` | Windows x64, macOS Intel/ARM64 und Linux x64/ARM64; native Oberfläche, normales Schließen, Verlust des Elternprozesses, vollständige Demo, Datenpersistenz und Dokument-/Bildworker |
| `release-hardening.yml` | Kontrollbuch über 120 Einheiten und fünf simulierte Jahre, Wiederherstellung und Prozessabbruch, begrenzte gleichzeitige Last und wiederholter lokaler KI-Protokoll-/Regelkorpus |

Der Release-Workflow prüft alle drei Laufkennungen und das vollständige Paket-
und Quelleninventar. Die fünf nativen Ziele, das portable Windows-Paket, der
Projektquellstand und alle elf gepinnten Qt-Quellarchive dürfen nicht durch ein
kleineres, nur intern konsistentes Inventar ersetzt werden. Fehlende, falsche
oder nur teilweise erfolgreiche Laufzeit-/Workerbelege sperren die Übernahme.

Ein lokaler Lauf mit uncommittierten oder während der Prüfung veränderten
Quellen ist ein Entwicklungsnachweis. Er ersetzt nicht die Abnahme des
unveränderten Auslieferungscommits. Die Lastwerkzeuge unterscheiden ihren
fachlichen Laufstatus ausdrücklich von der Release-Eignung. Ein bestehender
Ausgabeordner wird nicht überschrieben; Fehlerbelege bleiben erhalten.

## Signierung und Paketprüfung

Ein regulärer Windows-Kundenrelease benötigt eine gültige zeitgestempelte
Authenticode-Signatur. Für beide Mac-Architekturen baut `customer-macos.yml`
den freigegebenen Stand mit dem echten Developer-ID-Zertifikat neu, notarisiert
App und DMG und prüft die tatsächliche Laufzeit aus den finalen Paketbytes.
Private Herausgeberzugänge werden vor den Anwendungstests entfernt.

Die unabhängige Mac-Prüfung verlangt erwartetes Team, vollständige Buildversion,
Hardened Runtime, Tickets und Gatekeeper sowie den vollständigen, an denselben
Paket-Hash gebundenen Laufzeitbeleg. Kontrollierte positive Apple-Antworten aus
Vertragstests sind kein echter Signatur- oder Notarisierungsnachweis.

Ein manueller Release-Lauf verwendet standardmäßig nur Artefakte. Eine ausdrücklich
gewählte unsignierte `beta.N` bleibt ein Test-Vorabrelease. Vorhandene Tags oder
Releases werden niemals für einen neuen Inhalt überschrieben. Die Konfiguration
und tatsächlichen Voraussetzungen stehen in [Kommerzielle Auslieferung](COMMERCIAL_RELEASE.md).

## Kundenupdate und Wiederherstellung

1. Ein geprüftes Vollbackup erstellen und dessen Vollständigkeit prüfen.
2. Herkunft und Signatur des neuen Pakets prüfen und die Anwendung vollständig schließen.
3. Den neuen Installer ausführen; portable Pakete in einen neuen Programmordner entpacken.
4. Falls nötig, das ausdrückliche Datenbankupgrade mit geprüftem Vor-Upgrade-Backup ausführen.
5. Anmeldung, Dokumente, Zuordnungen und eingerichtete Integrationen im neuen Stand prüfen.

Die laufende Kundenanwendung ersetzt ihren Quellcode nicht über HTTP. Der
Sourceupdater bleibt ein ausdrücklich optierter Offline-Entwicklerweg mit
Versionstag und vollständig erwartetem Commit. Ein unklarer Rücksprung bleibt
gegen Schreibzugriffe gesperrt.

Ein Vollrestore erfolgt offline in einen neuen leeren Datenordner. Danach ist
eine neue Anmeldung nötig; alte Tokens werden auch mit dem damals passenden
JWT-Schlüssel nicht wieder gültig. AES-Schlüssel und die verschlüsselten
Integrationsdaten bleiben zusammen erhalten. Die Datenschutzprüfung bleibt
offen. Das Geheimnisbundle kann mit einer Passphrase geschützt sein; Datenbank
und Dokumente im Vollarchiv sind dadurch nicht vollständig verschlüsselt.

Details: [Betrieb und Sicherung](OPERATIONS_BACKUP_SECRETS_20261008.md),
[HTTP- und Anmeldegrenzen](HTTP_AUTH_BOUNDARY.md).

## Aussagekraft und Grenzen der KI-Prüfung

Der Härtungskorpus prüft lokale deutsche Einleseregeln, ungültige Zuordnungen
und tatsächlich gestartete, kontrollierte Anbieter-Protokollprozesse. Dazu
gehören Fehler, Zeitüberschreitungen und falsche Sitzungszuordnung. Das misst
keine fachliche Antwortqualität eines externen Modells. Eine entsprechende
Abnahme muss mit dem tatsächlich gewählten Anbieter, Modell, Anwendungsfall
und dafür freigegebenen Daten erfolgen.

Optionale Forschungsmodelle sind kein Bestandteil des geprüften Desktopkerns.
Bei einer Kundenauslieferung müssen angebotene Funktionen, getestete
Zielsysteme, Anbieterbedingungen, Datenschutzunterlagen und Supportverfahren
zum tatsächlich gewählten Produktprofil passen.
