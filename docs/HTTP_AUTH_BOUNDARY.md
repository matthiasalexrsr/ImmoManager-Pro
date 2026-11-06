# Hostnamen, Browseranfragen und Zwei-Faktor-Anmeldung

Die Anwendung prüft den HTTP-Hostnamen vor Anmeldung, Datenbankzugriff und
Erstregistrierung. Zugelassen sind Loopback (`localhost`, `127.0.0.1`, `[::1]`),
die Hostnamen aus `CORS_ORIGINS` und `PORTAL_PUBLIC_URL` sowie zusätzlich
ausdrücklich konfigurierte `TRUSTED_HOSTS`. Der Testhostname `testserver` ist nur
außerhalb der Produktionskonfiguration freigegeben. Ein beliebiger fremder Name,
auch wenn er auf die lokale IP zeigt, ist nicht zugelassen.

Für eine separate API-Adresse oder einen LAN-Zugriff werden **genaue Hostnamen
ohne Schema oder Port** angegeben. IPv6-Adressen stehen in eckigen Klammern.
Wildcards, URLs, Benutzerangaben und Pfade sind nicht zulässig. Beispiel:

```dotenv
ENVIRONMENT=production
CORS_ORIGINS=https://verwaltung.example.org
TRUSTED_HOSTS=api.example.org,192.168.1.20,[2001:db8::20]
```

Dies ersetzt weder die Firewall noch HTTPS oder eine Anmeldung. Ein Reverse-Proxy
muss den vorgesehenen Host weiterreichen und nur von der Anwendung ausdrücklich
vertraute Proxy-Header setzen. `TRUSTED_HOSTS` erlaubt keinen neuen externen
Browserursprung: Dafür ist weiterhin `CORS_ORIGINS` zuständig. Die lokale
Desktop-Anwendung verwendet ihre Loopback-Adresse und benötigt keine zusätzliche
Hostfreigabe. Die Konfiguration ist nach einem Neustart wirksam.

Bei der öffentlichen Erstregistrierung werden Eigentümerentscheidung und
Kontoerstellung in derselben SQL-Transaktion gesichert. Mehrere gleichzeitig
gestartete Serverprozesse können dadurch keinen zweiten ersten Eigentümer
erzeugen. Ist `ALLOW_SELF_REGISTRATION=true`, warten weitere öffentliche Konten
inaktiv und ohne Portfoliozuweisung auf die bewusste Aktivierung durch den
Eigentümer. Die Antwort meldet `is_active=false` und `approval_required=true`;
eine Anmeldung oder ein Datenzugriff ist vorher nicht erlaubt. Die bewusste
Kontoanlage durch die Administration ist davon getrennt.

Schreibende Browseranfragen (`POST`, `PUT`, `PATCH`, `DELETE`) benötigen bei
vorhandenem `Origin` die eigene Herkunft oder eine ausdrücklich konfigurierte
CORS-Herkunft. `Origin: null`, mehrdeutige Header und ein fremder Ursprung werden
vor der Verarbeitung abgewiesen. Fehlt `Origin`, bleibt ein gewöhnlicher
API-Client nutzbar; eine ausdrücklich als `Sec-Fetch-Site: cross-site` markierte
Schreibanfrage wird trotzdem abgewiesen. Diese zusätzliche Grenze ersetzt nicht
die Berechtigungsprüfung, die Cookie-Einstellungen oder CORS. Das gezielte
Negativexperiment mit fremdem Ursprung und JSON ohne Content-Type wurde bereits
von der vorhandenen FastAPI-Version als ungültige Eingabe zurückgewiesen; daraus
wird kein bestätigter Browser-CSRF-Exploit abgeleitet.

Für die Zwei-Faktor-Anmeldung gelten höchstens fünf Codeprüfungen in 15 Minuten
pro Konto bis zu einer erfolgreichen Prüfung. Anmeldung, Aktivierung und
Deaktivierung teilen dieselbe Grenze; E-Mail-Schreibweisen oder andere IP-Adressen
erzeugen kein weiteres Codebudget. SQLite und PostgreSQL reservieren die Prüfung
transaktional für mehrere Prozesse. Ein Ausfall dieser Speicherung erlaubt keine
zusätzliche Prüfung. Codes, Schlüssel und Tokens werden dabei nicht protokolliert.

Ein erfolgreich verwendeter TOTP-Zeitschritt kann für dasselbe Konto und denselben
Schlüssel kein zweites Mal verwendet werden. Die gespeicherte Identität ist
nicht umkehrbar und enthält weder den Schlüssel noch den Code; der Zeitschritt
wird atomar bestätigt. Auch ein Wechsel zwischen vorherigem, aktuellem und nächstem
akzeptierten Zeitfenster umgeht diese Reihenfolge nicht. Nach dem Aktivieren und
zum erneuten Anmelden oder Deaktivieren ist daher gegebenenfalls der nächste
Authenticator-Code abzuwarten. Ein geänderter Schlüssel und ein anderes Konto
haben getrennte Identitäten.

Nach einer unterstützten Wiederherstellung erzeugt das Zielprofil eine neue
private Datei `DATA_DIR/auth/session-epoch.json`. Dieser Nachweis wird unabhängig
von Datenbank, alter JWT-Konfiguration und AES-Schlüsselbund geprüft. Bereits
widerrufene Tokens dürfen durch das Zurückspielen älterer Daten deshalb nicht
wieder gültig werden. Die Datei wird beim Restore frisch erzeugt und darf nicht
aus einem älteren Archiv übernommen werden. Ein beschädigter oder nicht lesbarer
vorhandener Nachweis erlaubt keine Ausweichanmeldung mit alten Tokens.

Vor der ersten solchen Wiederherstellung bleiben vorhandene APIv1-Tokens ohne
Sitzungsinventar beziehungsweise ohne Epochenfeld kompatibel. Nach dem Restore
müssen sich auch diese Clients erneut anmelden. Login und Refresh verwenden für
beide ausgegebenen Tokens dieselbe zu Beginn geprüfte Profilgeneration; eine
parallel begonnene Anfrage kann nicht über die Restoregrenze in eine neue
Generation wechseln. Der AES-Schlüsselbund und bereits verschlüsselte Inhalte
werden durch diese Sitzungsgrenze nicht verändert. Bereits vorher autorisierte,
laufende Anwendungsoperationen sind dadurch nicht rückwirkend aufgehoben; die
Wiederherstellung muss weiterhin die eigene Offline-/Schreibsperre einhalten.
