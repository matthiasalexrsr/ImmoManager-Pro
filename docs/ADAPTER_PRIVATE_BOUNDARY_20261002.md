# Private Adapterquellen und Installationsverwaltung

Stand: 2. Oktober 2026. Basis dieser isolierten Korrektur: `da8678b`.

Die Benutzerfreigabe erlaubt die vollständige Erfassung auffindbarer Schnittstellen, Parameter und fachlicher Werte. Diese privaten Quellen brauchen trotzdem eine passende Zugriffsgrenze. Der bestehende Integrationsmanager speichert Konfiguration und Historie installationsweit; er ist kein nach Immobilien aufgeteilter Datenspeicher. Vollständige TEHA-Quellen gehören deshalb in einen eigens autorisierten und verschlüsselten Hostspeicher, nicht in dessen allgemeine Historie.

Die Portfolio-Middleware verweigerte ausgewählten Verwaltern bereits vor dieser Änderung alle Integrationsrouten. Tatsächlich reproduziert wurde stattdessen der Zugriff sonstiger Rollen mit installationsweitem Leserecht auf private unbekannte Konfigurationsfelder. Alle Integrationsrouten verlangen nun Eigentümer oder Verwalter mit Zugriff auf alle Portfolios. Die Abhängigkeit prüft den frisch geladenen Benutzer zusätzlich zum ursprünglichen Anfragekontext. Erfolgreiche Antworten erhalten `Cache-Control: private, no-store` und `Vary: Authorization`.

Ein eigener enger Routenhandler prüft die erfasste Benutzer-/Portfolioidentität sowie das Zugriffstoken nach Handler und Serialisierung nochmals, bevor Starlette die Antwort sendet. Ein Rechteentzug während der Anfrage liefert eine reguläre 403, ein widerrufenes Token eine reguläre 401, jeweils ohne private Antwort. Der Hook läuft vor dem ersten ASGI-send; eine Ausnahme erst innerhalb von `http.response.start` wäre dafür zu spät. Das ist eine Prüfung unmittelbar vor Veröffentlichung, keine Aussage über das Zurückholen bereits ausgeführter externer Aktionen.

Die Oberfläche lädt globale Adapterdaten nur für diese Verwaltungsrollen und entfernt Daten bei Identitäts-/Rechtewechseln. Jede noch laufende Aktion gehört zu ihrer ursprünglichen Berechtigungsgeneration. GET, PATCH, POST und nachfolgende Historienabfragen werden abgebrochen; alle Fortsetzungen und Fehleranzeigen prüfen ihre Generation nochmals. Ein zwischenzeitlich entzogener und danach wieder gewährter Zugriff reaktiviert keine alte Antwort. Der Schutz bleibt auch bei Testtransporten wirksam, die ein Abbruchsignal ignorieren.

## Tatsächliche Prüfung

- 36 Backendtests bestanden: reale HTTP-Anfragen mit Memory und SQLite, bestehende Router-/Manager-/Konfigurationsfälle, Rollen und Portfolioänderungen mit demselben Token, gezielter Wechsel zwischen Middleware und Auth-Abhängigkeit, Widerruf von Rolle/Portfolio/Token nach Antwortmaterialisierung und vor Veröffentlichung. Keine privaten Sentinels in abgelehnten Antworten, keine nachträgliche Response-start-Ausnahme.
- 15 Oberflächentests bestanden: verweigerte Rollen, sofortiges Entfernen geladener Daten, verspätete GET/PATCH/POST/Historien-/Fehlerantworten trotz Wiederfreigabe, deutsche/englische/spanische Rückmeldung.
- Der unabhängig vor der Korrektur erstellte ausführbare React-Repro bestätigt zusätzlich sechs verspätete Aktionsfälle. Sämtliche alten privaten Anzeigen und unzulässigen Folgeabfragen bleiben aus.
- Ruff, gezieltes Mypy, gezieltes ESLint und Produktionsbuild bestanden.

Die vollständigen Release-Regressionen und die PostgreSQL-Prüfung werden getrennt dokumentiert. Diese Korrektur beweist weder eine dauerhafte TEHA-Importverkabelung noch die Behebung aller zuvor aufgedeckten PostgreSQL-Probleme.
