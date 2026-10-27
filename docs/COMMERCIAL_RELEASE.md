# Kommerzielle Auslieferung

## Unterstützte Produktprofile

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

Ein Versionstag darf nur nach erfolgreicher CI auf genau diesem Commit veröffentlicht werden. Zusätzlich erzwingt der Windows-Release-Workflow eine gültige, mit Zeitstempel versehene Authenticode-Signatur. Er benötigt `WINDOWS_SIGNING_PFX_BASE64`, `WINDOWS_SIGNING_PASSWORD` und `WINDOWS_TIMESTAMP_URL` als geschützte CI-Konfiguration. Der Herausgeber muss zum Produktanbieter passen. Ohne Zertifikat bricht eine Veröffentlichung ab; interne Branch-Builds bleiben als unsignierte Testartefakte erkennbar.

Der Workflow attestiert die ZIP-Datei und die SHA256-Datei über GitHub Actions. Kundenseitig lässt sich die Herkunft mit `gh attestation verify <Datei> --repo matthiasalexrsr/ImmoManager-Pro` überprüfen. Eine Prüfsumme ohne unabhängig geprüfte Herkunft reicht dafür nicht aus. Die Durchführung dieser CI-Schritte, Zertifikatsgültigkeit und reale Upgrade-Proben gehören zur Freigabe jedes Releases.

## Hosting

Die Anwendung trennt Rollen und Portfolios innerhalb EINER Verwaltung. Ein Eigentümer besitzt installationsweiten Zugriff. Verschiedene Kunden dürfen deshalb nicht gemeinsam als Portfolios oder Eigentümerkonten in derselben Installation betrieben werden.

Zulässiges Hostingprofil: eine isolierte Instanz pro Kunde mit eigener Datenbank, eigenem Betriebssystem-/Containerkonto, Uploadordner, Schlüsseln, Integrationskonfiguration und Backups. Zwischen Instanzen dürfen keine Datenvolumes, DB-Zugangsdaten, Signierschlüssel, Mailkonten oder KI-Anmeldungen geteilt werden. HTTPS, Proxyvertrauen, Firewall, Ressourcenlimits, Wiederherstellung und Betrieb müssen auf dieser Ebene geprüft werden. Eine echte gemeinsame Mehrmandantenplattform benötigt eine eigenständige Organisationsgrenze in Datenmodell, Authentifizierung, Hintergrundaufträgen, Exporten und Backups und ist durch dieses Audit nicht implementiert.

Siehe `docs/HOSTING_ISOLATION.md` für die konkrete Bereitstellungsprüfung.

## Datenübertragungen und verbleibende Freigaben

Die lokale Speicherung schließt externe Verarbeitung nicht aus. Verbundene KI-Dienste erhalten ausgewählte Dokumente, Ausschnitte, Bilder und Kontext; Mail-, Bank- und Sicherungsintegrationen haben eigene Empfänger. Betreiber müssen die tatsächlichen Datenflüsse dokumentieren, Kunden informieren und passende Verträge/Löschfristen festlegen.

Vor Kundenauslieferung sind Vertragsfreigaben optionaler Komponenten, tatsächlicher Signaturbetrieb, Wiederherstellung unter Zielbedingungen, Datenschutzunterlagen und die isolierte Hostingkonfiguration durch den Verantwortlichen zu bestätigen. Ein erfolgreicher technischer Test ersetzt diese externen Nachweise nicht.

Vertrags- und Schreibenstexte benötigen außerdem eine rechtliche Freigabe für den jeweiligen Einsatz. Der technische Abgleich stellt sicher, dass Vorschau und PDF denselben Text enthalten; er bestätigt nicht die rechtliche Wirksamkeit einzelner Klauseln.
