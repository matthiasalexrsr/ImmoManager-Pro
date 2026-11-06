# Kommerzielle Auslieferung

## Unterstützte Produktprofile

Die Desktop-Pakete enthalten die eigenständige Qt-WebEngine-Oberfläche und den
alternativen Browserstart. Die festgelegte Desktop-Laufzeit steht in
`requirements-desktop.txt`. Originale Qt-/PySide-/Chromium-Lizenztexte und
Quellarchiv-Nachweise werden zusätzlich gesammelt; vollständige gepinnte Quellen
gehören als `Qt-Quellen` zur Auslieferung. Plattformgrenzen und tatsächlich
ausgeführte Prüfungen sind getrennt in `docs/DESKTOP_PLATFORMS.md` und im jeweiligen
Paket-Abnahmeprotokoll beschrieben. Die Desktop-Erweiterung ist kein optionales
Dokumentwerkzeug-Profil und benötigt keine erfundene Vertragsfreigabe.

Die Standardauslieferung enthält den Kern der Anwendung. Die installierte Umgebung entscheidet nicht mehr darüber, welche optionalen Komponenten mitgeliefert werden. Alle Build-Einstiege verwenden die festgelegten Laufzeitversionen in `requirements-runtime.txt` und die transitiven Versionen in `constraints.txt`; `pyproject.toml` liest dieselbe Laufzeitliste.

- Kern: `python scripts/build_exe.py --clean`.
- Bankintegration: zusätzlich `IMMO_BUILD_BANK=1` und Installation von `requirements-bank.txt` mit denselben Constraints.
- Interner Funktionstest der Dokumentwerkzeuge: `IMMO_BUILD_DOCUMENT_TOOLS=1`, `IMMO_BUILD_PURPOSE=validation`, Installation von `requirements-documents-optional.txt`, dann `python scripts/build_exe.py --with-document-tools`. Dieser Build ist keine Kundenauslieferung.
- Dokumentwerkzeuge zur Auslieferung: `IMMO_BUILD_PURPOSE=licensed` und `IMMO_LICENSE_APPROVAL_FILE` mit einer intern geprüften Rechtefreigabe. Die Datei muss für PyMuPDF, superdoc und @superdoc/docx-engine jeweils eine Vertrags-/Freigabereferenz und `distribution: true` enthalten. Vorlagen stehen in `packaging/license-approval.example.json`. Die Datei darf keine Vertragsgeheimnisse enthalten und gehört nicht ins Repository.

Der Build prüft diese Angaben technisch. Er kann keine Verträge prüfen oder Nutzungsrechte erwerben. Eine bloße Änderung der Freigabedatei schafft keine Rechte. Versions-, Laufzeit-, Nutzer-, Hosting- und Weitergaberechte sind anhand der tatsächlich geschlossenen Verträge zu prüfen. Die Komponenten werden nicht durch die MIT-Lizenz dieses Projekts umlizenziert.

PyMuPDF und SuperDoc bieten AGPL bzw. kommerzielle Bedingungen an. Die Lizenz des transitiven @superdoc/docx-engine ist gesondert zu prüfen. Ein proprietäres Produkt darf diese Komponenten nur mit nachweislich passenden Rechten ausliefern. Quellen:
- https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright
- https://docs.superdoc.dev/resources/license/
- https://docs.superdoc.dev/resources/docx-engine-license/

Optionale Hugging-Face-/Torch-Pakete sind Entwicklungs-/Forschungserweiterungen und werden aus dem geprüften Desktopprofil ausgeschlossen. Vor einer späteren Produktaufnahme sind genaue Paket- und Modellrevisionen, Modelllizenzen, Herkunft und Sicherheitsprüfungen erforderlich. Die externen Claude-/ChatGPT-Verbindungen benötigen diese Pakete nicht.

## Lizenzunterlagen im Paket

`python tools/third_party_notices.py` ermittelt die gewählten Python-Laufzeitabhängigkeiten und die installierten npm-Laufzeitpakete aus den Lockfiles, prüft die Versionen und sammelt die unveränderten Lizenz-/Notice-Dateien. Fehlende Texte führen zum Abbruch. Python-Laufzeit, PyInstaller-Ausnahme, Schriftarten und OCR-Modelle werden ebenfalls dokumentiert. PyInstaller erzeugt diese Sammlung automatisch und bindet sie als `THIRD_PARTY_NOTICES` ein.

Auch die eigenständigen Browserdateien des Mietvertragsassistenten werden geprüft: pdfmake ist exakt im Frontend-Lockfile enthalten; die ausgelieferten Dateien müssen mit der installierten npm-Distribution und `vendor/SOURCES.json` übereinstimmen. Die eingebetteten Roboto-Schriften haben einen eigenen OFL-Lizenztext. Bei einer Aktualisierung beide Browserdateien aus `node_modules/pdfmake/build` übernehmen, Schriftversion und zugehörige Lizenz prüfen sowie Herkunft und SHA-256 in `SOURCES.json` aktualisieren. Der Build bricht bei Abweichungen ab; der Browser-PDF-Export ist anschließend erneut zu prüfen.

Für @foliojs-fork/fontkit, brotli und dfa enthalten die Originalpakete nur MIT-Erklärungen in README und Paketmetadaten, keinen separaten vollständigen Lizenztext. Die Sammlung erhält diese Erklärungen unverändert und ergänzt den klar als Vorlage bezeichneten SPDX-Standardtext, ohne zusätzliche Rechte zu behaupten. Die Apache-2.0-Hinweise in den Brotli-Decoderdateien und der zugehörige vollständige Text werden zusätzlich bewahrt. Diese Herkunft ist in `packaging/third-party/licenses.json` dokumentiert und Teil der abschließenden Rechteprüfung.

Für Certifi (MPL-2.0) liegt das vollständige, unveränderte Quellarchiv mit Bezugsquelle und SHA-256 direkt bei den Lizenztexten. Der Build prüft, dass die Quellversion zur installierten Version passt. Grundlage: https://www.mozilla.org/en-US/MPL/2.0/FAQ/#q8-i-want-to-distribute-outside-my-organization-executable-programs-or-libraries-that-i-have-compiled-from-someone-elses-unchanged-mpl-licensed-source-code-either-standalone-or-part-of-a-larger-work-what-do-i-have-to-do

Bei zusätzlich gewählten Copyleft-Komponenten, insbesondere der optionalen Bankintegration, sind Quelltextbereitstellung, Änderungshinweise und Austausch-/Neubauoptionen gesondert zu erfüllen. Der Produktverantwortliche muss Rechte am eigenen Quelltext, Marken, Bildern, Vorlagen und sonstigen Daten bestätigen. Die bisher bereits in den Projektmetadaten erklärte MIT-Lizenz liegt nun als Datei bei; damit werden keine Rechte Dritter eingeräumt.

## Veröffentlichung und Herkunft

Ein Versionstag darf nur nach erfolgreicher CI, nativer Desktop-Abnahme und dem
Workflow `release-hardening.yml` auf genau diesem Commit veröffentlicht werden.
Der Härtungslauf prüft das unabhängige Kontrollbuch über 120 Einheiten und fünf
simulierte Jahre, Wiederherstellung, harte Neustarts, Gleichzeitigkeit sowie den
kontrollierten KI-Protokoll-/Regelkorpus. Seine Run-ID wird zusammen mit CI und
nativer Abnahme im Releasebeleg gebunden. Der übersprungene interaktive
Oberflächenteil des Langzeitlaufs wird ausdrücklich ausgewiesen; die separate
CI-Browserabnahme bleibt erforderlich. Reguläre signierte Windows-Releases
benötigen eine gültige, mit Zeitstempel versehene Authenticode-Signatur sowie
`WINDOWS_SIGNING_PFX_BASE64`, `WINDOWS_SIGNING_PASSWORD` und
`WINDOWS_TIMESTAMP_URL` als geschützte CI-Konfiguration. Ohne das passende
Herausgeberzertifikat bricht dieser Veröffentlichungsweg ab.

Eine Windows-Signatur allein gibt keine macOS-Kundenauslieferung frei. Beide
Mac-Pakete müssen zusätzlich einen an ihre tatsächlichen Bytes gebundenen
`immomanager-macos-customer-signing/1`-Nachweis enthalten: Developer-ID-Prüfung,
Hardened Runtime, angenommenes Notarisierungsergebnis, gültiges angeheftetes
Ticket und erfolgreiche Gatekeeper-Prüfung. `finalize-signed` und `publish`
weisen die bisherigen ad-hoc signierten Test-DMGs zurück. Ohne diese tatsächlich
ausgeführten nativen Prüfungen bleibt der reguläre Kundenrelease blockiert.
Ein selbst ausgefülltes JSON ersetzt keine Signierung und Notarisierung auf
einem vertrauenswürdigen Mac-Buildsystem. Die Einrichtung eines echten
Herausgeberzertifikats und des Apple-Notarisierungszugangs ist ein eigener
Auslieferungsnachweis; dieser Quellstand erfindet dafür keine Identität.

`scripts/verify_macos_customer.py` prüft ein bereits signiertes und notarisiertes
Paket auf der passenden nativen Mac-Architektur mit den tatsächlichen
Apple-Werkzeugen. Es prüft Produkt- und vollständige Buildversion, erwartete
Team-ID, Developer ID, sicheren Zeitstempel, Hardened Runtime sowie App- und
DMG-Tickets/Gatekeeper. Zusätzlich müssen die vollständigen echten
Source-/Frozen-/Demo-Abnahmeberichte vorliegen; deren
`native-environment.json` muss `customer_signed_runtime: true` und
`customer_package_sha256` mit dem Hash genau dieses finalen DMGs binden.
Die Prüfung verändert oder startet die Anwendung nicht und deaktiviert keine
Schutzfunktion. Sie erstellt bei Erfolg eine neue geprüfte Paketkopie samt
Bytebindung; ein vorhandenes Ausgabeziel wird abgewiesen. Beispiel im
zugehörigen nativen, vertrauenswürdigen Releasecheckout:

```text
python scripts/verify_macos_customer.py --package <finales.dmg> --receipt <native-Buildbeleg.json> --reports <native-Abnahmeordner> --output <neuer-Ausgabeordner> --version <Version> --commit <vollständiger-Commit> --architecture <x64-oder-arm64> --team-id <erwartete-Team-ID>
```

Der Toolvertrag wird mit kontrollierten Antworten geprüft. Die native Test-CI
prüft zusätzlich die tatsächliche Ablehnung ihrer ad-hoc signierten DMGs. Das
ist kein positiver Kunden-Signatur-/Notarisierungsnachweis. Die bisherigen
unsigned Testpakete und ihre Abnahmeberichte sind dafür weiterhin ungeeignet.

Der reguläre Veröffentlichungsweg ruft dafür den wiederverwendbaren Workflow
`customer-macos.yml` auf. Er baut auf nativen Intel- und ARM-Macs genau den
freigegebenen Commit neu, signiert App und DMG, lässt beide notarisieren und
heftet die Tickets an. Erst danach werden die endgültigen DMGs schreibgeschützt
eingebunden und mit getrennten synthetischen Profilen tatsächlich ausgeführt.
Der unabhängige Prüfer muss anschließend die Signaturen, Tickets, Gatekeeper
und alle an die finalen Paketbytes gebundenen Laufzeitbelege akzeptieren. Der
Release übernimmt beide Mac-Pakete gemeinsam in ein neues vollständiges Staging;
ein Fehler veröffentlicht keinen teilweise ersetzten Bestand. Interne
Artefaktläufe und der ausdrückliche unsigned Betaweg überspringen diesen
Kunden-Signierweg.

Die geschützte CI-Umgebung `customer-release` ist mit den vorgesehenen
Zugriffs-/Freigaberegeln einzurichten. Als Geheimnisse werden
`MACOS_SIGNING_P12_BASE64`, `MACOS_SIGNING_PASSWORD`,
`APPLE_NOTARY_KEY_BASE64`, `APPLE_NOTARY_KEY_ID` und
`APPLE_NOTARY_ISSUER_ID` benötigt. `MACOS_SIGNING_IDENTITY` und
`MACOS_TEAM_ID` sind explizite CI-Variablen. Die Identität muss ein echtes
Developer-ID-Application-Zertifikat des erwarteten Teams sein. Fehlende Angaben
führen zum Abbruch; es gibt keinen automatischen Rückfall auf ad-hoc-Signierung.
Private Zertifikatsdateien und der temporäre Schlüsselbund werden vor den
Anwendungsprüfungen entfernt und nicht als Artefakte hochgeladen. Der
Vorbereitungs- und Fehlervertrag ist testbar, ein gemockter Apple-Aufruf ist
weiterhin keine erfolgreiche echte Signierung oder Notarisierung.

Der Veröffentlichungsprüfer verlangt außerdem das vollständige Inventar aller
fünf Plattformpakete, das portable Windows-Paket, den Projektquellstand und alle
elf gepinnten Qt-Quellarchive. Ein intern konsistentes, aber verkleinertes
Inventar ist nicht freigabefähig. Die native Abnahme muss in Quellbetrieb,
gepackter Anwendung und Demo auch die echten PDF-/PNG-/DOCX-/Text-/Bildworker
bestätigen. Fehlende oder fehlgeschlagene Workerprotokolle verhindern die
Übernahme in den Release.

Herstellerreferenzen: [Apple zu Notarisierung und Developer ID](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution),
[Microsoft zur vertrauenswürdigen Codesignatur](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control).

Für die Weitergabe einer Beta zum gemeinsamen Testen gibt es einen ausdrücklich
auszuwählenden manuellen Weg: `publish=true`, `release_tag=v<Projektversion>` und
`allow_unsigned_prerelease=true`. Er ist ausschließlich für Versionen der Form
`X.Y.Z-beta.N` verfügbar. Er übernimmt die bereits auf demselben Commit nativ
gebauten und geprüften fünf Plattformpakete einschließlich Windows-Installer,
Demo-Prüfungen und vollständiger Qt-Quellen. Das Release wird als Vorabversion
und unsigniert ausgewiesen; vorhandene Tags oder Releases werden nicht ersetzt.
Diese Auswahl aktiviert keine unsignierte Veröffentlichung einer stabilen Version.

Der Workflow attestiert die ZIP-Datei und die SHA256-Datei über GitHub Actions. Kundenseitig lässt sich die Herkunft mit `gh attestation verify <Datei> --repo matthiasalexrsr/ImmoManager-Pro` überprüfen. Eine Prüfsumme ohne unabhängig geprüfte Herkunft reicht dafür nicht aus. Die Durchführung dieser CI-Schritte, Zertifikatsgültigkeit und reale Upgrade-Proben gehören zur Freigabe jedes Releases.

## Kundenupdates und Wiederherstellung

Die Oberfläche bietet ausschließlich das geprüfte neue Installationspaket an.
`/updates/apply` darf keinen beliebigen Branchstand über eine laufende
Kundeninstallation schreiben. Auch ein älteres Backend mit `can_apply=true`
aktiviert in der aktuellen Oberfläche keinen direkten Sourceupdate-Knopf.
Downloadlinks werden auf HTTPS-GitHub-Releaseadressen begrenzt; eine fehlende
oder unpassende Adresse wird als Fehler gezeigt.

Vor der Aktualisierung ein geprüftes Vollbackup erstellen, Herkunft und
Signatur des Pakets prüfen, die Anwendung geordnet schließen und den Installer
verwenden. Vor einer erforderlichen Schemaänderung bleibt das geprüfte
Vor-Upgrade-Backup Pflicht. Alte Programmversion und bereits migrierte Daten
dürfen nicht zusammen gestartet werden. Für eine Rückkehr wird das vollständige
Vor-Upgrade-Backup einschließlich Anhängen und Schlüsseln in einen neuen
Datenordner wiederhergestellt; die aktualisierte Installation bleibt erhalten.

Der Sourceupdater ist ausschließlich ein ausdrückliches Entwicklerverfahren
mit Versionstag und vollständig erwartetem Commit. Er ist weder ein HTTP-Flag
noch ein Ersatz für die Herausgebersignatur eines Kundenpakets. Sein sicherer
automatischer Rollback ist auf SQLite begrenzt. PostgreSQL wird auf ein
überprüftes manuelles Deployment mit eigener Sicherung/Wiederherstellung
verwiesen. Ein fehlgeschlagener Rollback oder unklarer Transaktionszustand muss
Schreibzugriffe gesperrt lassen und eine sichtbare Wiederherstellung erfordern.

Der alte Raw-SQLite-HTTP-Restore ist ebenfalls geschlossen. Er könnte weder
laufende Fach-/Versandjobs noch alle Sessions über mehrere Serverprozesse
zuverlässig anhalten. Die weiterhin verfügbare Wiederherstellungsprobe arbeitet
in einem getrennten Testbestand; sie tauscht die laufende Datenbank nicht aus.
Transaktional begrenzte fachliche JSON-Snapshots und Mergeimporte sind gesonderte
Verfahren und keine Freigabe des Raw-DB-Austauschs.

Nach einem Vollrestore ist eine neue Anmeldung erforderlich. Der neue Zielbestand
erhält eine frische private Sitzungsgrenze; auch alte, zur gesicherten Datenbank
und zum damaligen JWT-Schlüssel passende Tokens dürfen damit nicht wieder gültig
werden. AES-Schlüssel für verschlüsselte Integrationsdaten bleiben erhalten.
Die Datenschutzprüfung bleibt nach der Wiederherstellung offen. Ein durch einen
harten Prozessabbruch hinterlassenes privates `.restore-*`-Arbeitsverzeichnis
wird nicht als fertiger Zielbestand veröffentlicht und kann eine gesonderte
manuelle Bereinigung erfordern.

Die Sicherung und ihre SHA-Datei belegen Integrität, keine unabhängige
Herausgeberidentität. `BACKUP_PASSPHRASE` schützt das Geheimnisbundle, nicht den
gesamten Inhalt aus Datenbank und Dokumenten. Vollarchive gehören daher auf
zugriffsgeschützten, bei Bedarf verschlüsselten Speicher. Die Prüfungen ersetzen
keine Hardware-, Stromausfall- oder Netzlaufwerksgarantie.

## Ersteinrichtung und neue Konten

Die Entscheidung über den ersten Eigentümer und das Anlegen seines Kontos
müssen auch zwischen mehreren SQL-Serverprozessen atomar sein. Öffentlich
erlaubte Folgeregistrierungen erhalten zunächst ein inaktives Nur-Lesen-Konto
ohne Portfolios. Erst ein Eigentümer aktiviert das Konto und weist die
benötigten Portfolios zu. Die Registrierung erklärt diese Freigabe und erzeugt
vorher keine Sitzung. Bewusst durch den Eigentümer angelegte Konten bleiben ein
eigener administrativer Ablauf. Offene Selbstregistrierung bleibt standardmäßig
ausgeschaltet; sie ersetzt keine kundenspezifische Instanztrennung.

## Hosting

Die Anwendung trennt Rollen und Portfolios innerhalb EINER Verwaltung. Ein Eigentümer besitzt installationsweiten Zugriff. Verschiedene Kunden dürfen deshalb nicht gemeinsam als Portfolios oder Eigentümerkonten in derselben Installation betrieben werden.

Zulässiges Hostingprofil: eine isolierte Instanz pro Kunde mit eigener Datenbank, eigenem Betriebssystem-/Containerkonto, Uploadordner, Schlüsseln, Integrationskonfiguration und Backups. Zwischen Instanzen dürfen keine Datenvolumes, DB-Zugangsdaten, Signierschlüssel, Mailkonten oder KI-Anmeldungen geteilt werden. HTTPS, Proxyvertrauen, Firewall, Ressourcenlimits, Wiederherstellung und Betrieb müssen auf dieser Ebene geprüft werden. Eine echte gemeinsame Mehrmandantenplattform benötigt eine eigenständige Organisationsgrenze in Datenmodell, Authentifizierung, Hintergrundaufträgen, Exporten und Backups und ist durch dieses Audit nicht implementiert.

Siehe `docs/HOSTING_ISOLATION.md` für die konkrete Bereitstellungsprüfung.

## Datenübertragungen und verbleibende Freigaben

Die lokale Speicherung schließt externe Verarbeitung nicht aus. Verbundene KI-Dienste erhalten ausgewählte Dokumente, Ausschnitte, Bilder und Kontext; Mail-, Bank- und Sicherungsintegrationen haben eigene Empfänger. Betreiber müssen die tatsächlichen Datenflüsse dokumentieren, Kunden informieren und passende Verträge/Löschfristen festlegen.

Vor Kundenauslieferung sind Vertragsfreigaben optionaler Komponenten, tatsächlicher Signaturbetrieb, Wiederherstellung unter Zielbedingungen, Datenschutzunterlagen und die isolierte Hostingkonfiguration durch den Verantwortlichen zu bestätigen. Ein erfolgreicher technischer Test ersetzt diese externen Nachweise nicht.

Bei der KI-Anbindung sind persönliche lokale CLI-Nutzung und eine kommerzielle
Produkteinbindung getrennt zu bewerten. Die Anwendung verwendet unveränderte
native Anbieterclients mit persönlichen Profilen und verkauft keine
Anbieter-Kontingente. Daraus folgt keine pauschale Anbieterfreigabe für jedes
Vertriebs-/Hostingmodell. Anthropic beschreibt sowohl Bedingungen für
unverändertes Claude Code in Produkten als auch Grenzen für eigene
Claude.ai-Anmeldungen und Zugangsdatenvermittlung; der aktuelle Hilfetext
beschreibt gesondert `claude -p`-/SDK-Abrechnung. Maßgeblich sind die für das
konkrete Produktmodell vereinbarten Bedingungen. Quellen:
[Claude Code Legal and Compliance](https://code.claude.com/docs/en/legal-and-compliance),
[Claude-Plan und Agent SDK](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan),
[Codex App Server](https://learn.chatgpt.com/docs/app-server).
Es wird keine Rechtsfreigabe oder Umgehung dieser Grenzen behauptet.

Vertrags- und Schreibenstexte benötigen außerdem eine rechtliche Freigabe für den jeweiligen Einsatz. Der technische Abgleich stellt sicher, dass Vorschau und PDF denselben Text enthalten; er bestätigt nicht die rechtliche Wirksamkeit einzelner Klauseln.
