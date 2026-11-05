# Windows-Installer

Der Installer verwendet den modernen Inno-Setup-Assistenten mit der vorhandenen
ImmoManager-Marke. Er übernimmt das helle oder dunkle Windows-Farbschema, verwendet
Segoe UI und skaliert die vorhandenen hochauflösenden Grafiken für die Anzeige.
Es gibt einen klaren Ablauf für Startmodus, Zielordner, optionale
Desktopverknüpfung, Installation und anschließenden Programmstart.

Eine eigene Auswahlseite bietet zwei gleichwertige Startmöglichkeiten:
„Eigenständige Desktop-Anwendung (empfohlen)“ und „Im Webbrowser verwenden“.
Beide sind im selben Paket enthalten. Bei einer Aktualisierung bleibt die
Auswahl erhalten, sofern sie nicht ausdrücklich geändert wird. Der Hauptstarter,
die optionale Desktopverknüpfung und der Start nach der Installation verwenden
dieselbe Auswahl. Unter „Startmöglichkeiten“ im Startmenü sind beide Varianten
zusätzlich direkt erreichbar. Die Wahl erzeugt keinen persönlichen Datenordner;
eine abgebrochene Installation speichert keine neue Modusauswahl.

Die folgende Auswahl „Start nach der Installation“ öffnet entweder die eigene
Verwaltung oder die vorbereitete Demo Baden-Württemberg. Sie ändert ausschließlich
den angebotenen ersten Start. Haupt- und Desktopverknüpfung öffnen weiterhin die
eigene Verwaltung. Unter „Demo“ im Startmenü sind die Desktop- und Browservariante
der Demo jederzeit erreichbar. Der Demobestand verwendet
`%LOCALAPPDATA%\ImmoManagerProDemoBW` und standardmäßig Port 8766.
Der Demozugang wird auf der Anmeldeseite angezeigt und kann mit einem Knopf
in die Eingabefelder übernommen werden.

Standard ist eine Installation für das aktuelle Benutzerkonto, ohne
Administratorrechte: `%LOCALAPPDATA%\Programs\ImmoManagerPro`.
Der persönliche Datenordner `%LOCALAPPDATA%\ImmoManagerPro` bleibt getrennt und
wird weder bei Updates noch bei der Deinstallation gelöscht. Der Installer
beendet keine laufenden Programme. Solange der Desktopmanager oder sein Server
den Mutex `Local\ImmoManagerPro.Desktop` hält, verlangt er das geordnete Beenden.
Die Prüfung erfolgt auch unmittelbar vor dem Kopieren.

Jeder Paketinhalt erhält einen eigenen Unterordner `app/<Version>-<Payloadhash>`.
Startmenü und optionale Desktopverknüpfung zeigen direkt auf dessen
`ImmoManager-Pro.exe`. Dadurch gelangen ältere DLLs oder Pythonmodule bei einem
Update nicht in den Suchpfad der neuen Version. Inno protokolliert eigene Dateien
über mehrere Installationen; die normale Deinstallation entfernt diese. Es gibt
keine pauschalen rekursiven Löschanweisungen. Fremde Dateien bleiben erhalten.
`installation.json` im Programmordner dokumentiert Version, beide EXE-Pfade,
Payloadhash, beide Startmodi, die eigenständige Laufzeit und die vollständige
Dateiinventur.

## Reproduzierbar bauen

Zuerst das reguläre Windows-Bundle mit GUI- und separater CLI-EXE bauen. Danach:

```powershell
python scripts/build_installer.py `
  --dist dist/ImmoManager-Pro `
  --iscc C:/Tools/Inno-Setup-6.7.4/ISCC.exe `
  --output dist/installers
```

Der Builder installiert nichts und lädt nichts herunter. Er prüft die beiden
Windows-EXEs, die gebündelte Projektversion und das Produktprofil. Er verlangt
außerdem `_internal/desktop-runtime.json` mit der Engine `pyside6-qtwebengine`,
der konkreten Laufzeitversion und `native_required_files`. Diese Pfade müssen
relativ zur Bundlewurzel sein; die aufgelisteten Dateien müssen tatsächlich
vorhanden und nicht leer sein. QtWebEngine-Prozess, Bibliotheken, Windows-Plugin,
Ressourcen und Sprachdateien werden ausdrücklich geprüft. Ein reines
Browserpaket kann daher nicht als Installation mit beiden Modi ausgegeben
werden. Datenbanken,
Konfigurationsdateien und persönliche Datenordner werden abgewiesen. Links und
Reparsepunkte sind keine Paketquellen. Das Ergebnis sind ein Setup-EXE, eine
Buildbeschreibung `.build.json` und eine `.sha256`-Prüfsumme. Vorhandene
Setup-Dateien werden nicht still überschrieben.

Der Compiler ist auf **Inno Setup 6.7.4** festgelegt. Das offizielle unveränderliche
[Release is-6_7_4](https://github.com/jrsoftware/issrc/releases/tag/is-6_7_4)
enthält `innosetup-6.7.4.exe`, 10.604.576 Bytes, mit SHA-256:

```text
a549929319f9120716677c685535ca4671e4b937b5fdc87e2585f32d8eb30e8c
```

Direkter Herstellerdownload:
https://github.com/jrsoftware/issrc/releases/download/is-6_7_4/innosetup-6.7.4.exe

Vor seiner Ausführung Originalhash und gültige Authenticode-Signatur des
Herstellers **Pyrsys B.V.** prüfen. Die
[Herstelleranleitung](https://jrsoftware.org/isdl-verify.php) beschreibt zusätzliche
ISSig-/Release-Attestationsprüfungen. Der Builder akzeptiert mit `--iscc` auch einen
bereits verifizierten, isoliert vorbereiteten Compiler. Die Inno-Setup-Lizenz
dieses konkreten Releases bleibt maßgeblich; es wird kein Compiler mit dem
Anwendungsinstaller ausgeliefert.

## Installation prüfen

Ein Test muss in einem neuen eigenen Testordner erfolgen. Vor einem Test mit der
regulären AppId den entsprechenden vorhandenen HKCU-Uninstall-Eintrag prüfen;
eine echte Installation darf nicht umgebogen werden.

Für einen unbeaufsichtigten Test unterstützt Inno beispielsweise `/VERYSILENT
/SUPPRESSMSGBOXES /NORESTART /SP- /NOICONS /TASKS="" /DIR="<neuer Testordner>"
/MODE=standalone`. `/MODE=browser` wählt den Webbrowser. Ohne `/MODE` wird bei
einer neuen Installation die Desktop-Anwendung gewählt, bei einer vorhandenen
Installation ihre gespeicherte Auswahl. Ungültige Werte werden vor dem
Kopieren der Programmdateien abgewiesen.
`/DEMO=1` wählt die Demo für den ersten Start nach der Installation, `/DEMO=0`
die eigene Verwaltung. Ohne diese Angabe bleibt die vorige Auswahl erhalten
(bei einer neuen Installation: eigene Verwaltung). Stille Installationen starten
keine der beiden Verwaltungen. Die normalen Hauptverknüpfungen bleiben auch bei
gewählter Demo auf die eigene Verwaltung gerichtet.
`skipifsilent` verhindert dabei den automatischen Appstart. Der echte GUI-Test
startet anschließend den in `installation.json` angegebenen relativen GUI-Pfad
mit einem eigenen `--data-dir` und einem eigenen Port. Nach dem geordneten
Beenden `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART` verwenden und
prüfen, dass eigene Daten und eine fremde Testdatei erhalten bleiben.

`scripts/check_windows_installer.py` prüft ein tatsächlich gebautes Setup mit
vier stillen Durchläufen: Standardmodus ohne Vorgabe, ausdrücklicher Desktopmodus,
Wechsel zum Browsermodus und erneute Installation ohne Modusangabe. Es liest die erzeugten Windows-
Verknüpfungen und kontrolliert Ziel, Argumente und Arbeitsordner. Ein eigener,
eindeutiger Startmenüordner wird dafür verwendet. Eine bereits vorhandene
Desktopverknüpfung wird nicht geändert. Existiert der reguläre Startmenüordner
„ImmoManager Pro“ bereits, beginnt der Test keine Installation, selbst wenn
keine Installation registriert ist. Die Startmenüauswahl wird lediglich im
sichtbaren Ablauf übersprungen; Innos `/GROUP`-Verarbeitung bleibt aktiv.
Der Test prüft außerdem ungültige
Modusangaben vor und nach der Installation, einen zu langen Zielpfad, die
Laufzeitsperre, vollständige Paketidentität, Daten- und Fremddateierhalt sowie die
Entfernung aller eigenen Paketdateien und Testverknüpfungen. Sein `--work`-Ordner
muss kurz genug sein, damit der vollständige Paketpfad in das berechnete
Installationsbudget passt. Ein normaler Benutzer-TEMP-Ordner ist geeignet.

Die Markenbilder können mit `build_branding.py` aus dem kanonischen SVG neu
erzeugt werden. Das ist ein optionales Artwork-Werkzeug mit PyMuPDF/Pillow;
Compiler und Laufzeitanwendung benötigen diese zusätzlichen Renderer nicht.

Primärreferenzen: [modernes Farbschema](https://jrsoftware.org/ishelp/topic_setup_wizardstyle.htm),
[Benutzerinstallation](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm),
[AppMutex](https://jrsoftware.org/ishelp/topic_setup_appmutex.htm),
[Dateibelegung und Programmbeendigung](https://jrsoftware.org/ishelp/topic_setup_closeapplications.htm),
[native Optionsauswahl](https://jrsoftware.org/ishelp/topic_isxfunc_createinputoptionpage.htm),
[gespeicherte Auswahlen lesen](https://jrsoftware.org/ishelp/topic_isxfunc_getpreviousdata.htm)
und [nach erfolgreicher Installation speichern](https://jrsoftware.org/ishelp/topic_isxfunc_setpreviousdata.htm).
