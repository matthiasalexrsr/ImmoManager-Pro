# Desktop- und Browserbetrieb

ImmoManager Pro kann dieselbe lokale Verwaltung in einem eigenen Anwendungsfenster
oder im Standardbrowser öffnen. Beide Varianten verwenden dieselbe Datenbank und
dieselben Dokumente. Ein Wechsel des Startmodus migriert oder kopiert keine Daten.
Eine zweite Instanz für denselben Datenordner wird abgefangen.

Die eigenständige Anwendung enthält Qt WebEngine / Chromium über PySide6 6.11.3.
Ein installierter Browser und WebView2 sind dafür nicht erforderlich. Der lokale
Server bleibt an die Loopback-Adresse gebunden. Externe Seiten werden nicht in die
Verwaltung eingebettet. Externe Verknüpfungen benötigen eine bewusste Bestätigung.

Normale Dokument-Uploads werden auch bei S3-Speicherung über die lokale
Anwendungsadresse bereitgestellt. Frei hinterlegte fremde HTTP(S)-Dateiadressen
werden dagegen nicht als Bild, PDF oder Download in das Desktopfenster geladen.
Für Vorschauen und Downloads solcher externen Datei-URLs den Browsermodus
verwenden. Diese Grenze betrifft keine regulär hochgeladenen Dokumente.

## Plattformziele und tatsächliche Grenzen

| Plattform | Architektur / Mindestbasis | Paket / Start |
| --- | --- | --- |
| Windows | x64, Windows 10 ab Build 19041 oder Windows 11 | Setup mit Auswahl Desktop/Browser, Startmenü und optionalem Desktopsymbol |
| Windows auf ARM | x64-Emulation unter Windows 11 | dasselbe x64-Paket; kein als nativ ARM ausgegebenes Paket |
| macOS | Intel und Apple Silicon, macOS 13 oder neuer | jeweils nativ gebautes `.app` in einer `.dmg` |
| Linux | x86_64 mit glibc ab 2.34, z. B. Ubuntu 22.04; ARM64 mit glibc ab 2.39, z. B. Ubuntu 24.04 | jeweils nativ gebautes Verzeichnis als `.tar.gz` |

Diese Tabelle beschreibt Build-Ziele und Abhängigkeitsgrenzen, keine pauschale
Testfreigabe aller Distributionen und Betriebssystemversionen. Welche nativen
Pakete wirklich gebaut und geprüft wurden, steht im jeweiligen Abnahmeprotokoll.
Ein Windows-Build kann keine funktionierende macOS-/Linux-Binärdatei erzeugen.

Windows 7/8, 32-Bit-Systeme, Android, iOS, BSD und Linux mit musl wie Alpine sind
keine Ziele dieser Desktop-Pakete. Auf anderen Geräten kann die Browseroberfläche
einer passend abgesicherten Serverinstallation genutzt werden; das ist ein
eigenständiges Bereitstellungsmodell und keine native Desktop-Freigabe.

Qt 6.11.3 wurde gezielt als aktueller Wartungsstand gewählt: Die offiziellen
Wheels unterstützen noch macOS 13; Qt/PySide 6.12 benötigt dort macOS 14.
Die Python-Quellinstallation benötigt Python 3.11 bis 3.14 und für Desktopbetrieb
`pip install -e ".[desktop]"`. Eine reine Serverinstallation benötigt Qt nicht.

## Öffnen und Moduswahl

Unter Windows bietet der Installer beide Varianten zur Auswahl an und merkt sich
die Auswahl für die nächste Installation. Zusätzliche Startmenüeinträge öffnen
gezielt die Desktop- oder Browservariante. Im normalen Betrieb wird keine Konsole
offen gehalten. Für einen Wechsel die laufende Anwendung zunächst über „Beenden“
schließen und danach den gewünschten Eintrag unter „Startmöglichkeiten“ öffnen.

Unter macOS die App aus dem Datenträgerabbild in „Programme“ ziehen und öffnen.
Der Standard ist das eigenständige Fenster. Ein gezielter Browserstart ist z. B.
mit `open -a "ImmoManager Pro" --args --mode browser` möglich.

Unter Linux das Archiv entpacken und `Start-Desktop` oder `Start-Browser` öffnen.
Beide Launcher müssen ausführbar bleiben. Es ist eine grafische Sitzung nötig:
X11 oder eine funktionierende Wayland-Sitzung mit den Qt-Plattformbibliotheken.
Qt benötigt unter anderem NSS, Fontconfig, OpenGL/Mesa, XKB und die zur Sitzung
passenden XCB/Wayland-Bibliotheken. Der native CI-Build installiert und prüft diese
Abhängigkeiten. Ein beliebig minimales Serversystem ist keine Desktopumgebung.
Für den Browser-Statusdialog muss zusätzlich Tcl/Tk verfügbar sein.

Der Chromium-Prozess benötigt seine Betriebssystem-Sandbox. Unter Linux müssen
unprivilegierte Benutzernamensräume und seccomp für die Anwendung zulässig sein.
Es gibt keinen automatischen Fallback mit abgeschalteter Sandbox. Auf restriktiven
Distributionen ist eine auf das Programm begrenzte AppArmor-Freigabe oder eine
passend konfigurierte Desktopumgebung nötig. Die Anwendung nicht als root starten.

## Daten und Beenden

### Vorbereitete Demo Baden-Württemberg

Unter Windows die Demo im Installer als Erststart wählen oder die beiden Einträge
„Demo Baden-Württemberg“ unter den Startmöglichkeiten öffnen. Desktop und Browser
stehen auch dafür zur Wahl. „Demozugang übernehmen“ auf der Anmeldeseite füllt
`demo.bw` und `Immo-Demo-BW-2026!` ein; anschließend „Anmelden“ wählen.

Die Demo enthält acht Immobilien mit 46 Einheiten, 42 Mietverträgen und mehr als
1.000 Buchungen einschließlich Dokumenten und laufenden Verwaltungsvorgängen.
Sie verwendet den getrennten Datenordner `ImmoManagerProDemoBW`, initialisiert
ihn einmal und erhält spätere Änderungen. Reguläre Datenordner und deren
Verbindungseinstellungen werden dafür nicht übernommen. Standardport ist 8766.

Im Quellbetrieb: `python -m backend --demo`, unter Windows auch
`start.bat -Demo`. Unter Linux stehen `Demo-Desktop` und `Demo-Browser` bereit;
unter macOS startet `open -a "ImmoManager Pro" --args --demo` die eigene Oberfläche
und `open -a "ImmoManager Pro" --args --demo --mode browser` die Browservariante.

### Eigene Verwaltung

- Windows: `%LOCALAPPDATA%\ImmoManagerPro`
- macOS: `~/Library/Application Support/ImmoManagerPro`
- Linux: `$XDG_DATA_HOME/ImmoManagerPro`, sonst `~/.local/share/ImmoManagerPro`

`--data-dir` und bewusst gesetzte Serverkonfigurationen bleiben verfügbar. Ein
relativer XDG-Pfad wird nicht als persönlicher Datenordner übernommen. Vorhandene
eigene Datenordner werden nicht stillschweigend verschoben.

Beim Schließen beendet das Anwendungsfenster seinen eigenen Server geordnet.
Fehler beim Start, ein belegter Port und ein abgestürzter Renderer werden angezeigt
und protokolliert. Eine fremde Anwendung auf demselben Port wird nicht übernommen
oder beendet. Die Protokolle liegen im persönlichen Datenordner unter `logs`.

## Build, Quellen und Signaturen

`requirements-desktop.txt` legt die gemeinsam zu bauenden Qt-Versionen fest.
`immomanager.spec` verwendet die offiziellen PyInstaller-Qt-Hooks, prüft native
Renderer, Bibliotheken, Ressourcen und deutsche/englische Sprachpakete und erzeugt
`desktop-runtime.json`. Ein unvollständiges Browserpaket darf den Installer nicht
erzeugen. macOS- und Linux-Pakete werden mit `scripts/package_native_desktop.py`
ausschließlich auf dem jeweiligen Zielsystem erstellt.

`packaging/third-party/qt-sources.json` enthält unveränderliche offizielle Quellen
mit SHA-256. Der Build sammelt originale Lizenz-/Drittanbietertexte einschließlich
Chromium. Vollständige Qt-/PySide-Quellarchive werden im Ordner `Qt-Quellen` als
Begleitdateien zur Auslieferung bereitgestellt. Die dynamischen Qt-Bibliotheken
können ABI-kompatibel ersetzt werden; es gibt keine Sperre für die Untersuchung
solcher Änderungen. Weitere Hinweise stehen in den mitgelieferten Lizenzen.

Code-Signatur, macOS Developer-ID und Apple-Notarisierung benötigen die jeweiligen
Herausgeberzertifikate. Ein lokaler Testbuild erhält dadurch keine automatische
Signatur oder Plattformfreigabe. Der Paketnachweis nennt den tatsächlichen Zustand.

Primärquellen: [PySide6 6.11.3](https://pypi.org/project/PySide6/6.11.3/),
[Qt WebEngine Deployment](https://doc.qt.io/qt-6/qtwebengine-deploying.html),
[Qt WebEngine Platform Notes](https://doc.qt.io/qt-6/qtwebengine-platform-notes.html),
[native GitHub-Runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
