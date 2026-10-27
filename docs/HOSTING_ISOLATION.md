# Hosting mit einer Instanz pro Kunde

Die Instanz ist die Sicherheitsgrenze zwischen Kunden. Portfolios sind keine Mandanten.

Für jeden Kunden eine eigene VM oder einen isolierten Container als eigener, nicht privilegierter Benutzer bereitstellen. Die Anwendung ausschließlich über einen HTTPS-Reverse-Proxy erreichbar machen. Keine Host-Netzfreigaben und keine Docker-Socket-Freigabe. Ausgehend nur freigegebene Integrationen zulassen.

| Ressource | Pflicht pro Kundeninstanz |
|---|---|
| Datenbank | Eigene Datenbank, eigener DB-Benutzer mit Zugriff nur auf diese Datenbank |
| DATA_DIR / UPLOADS_DIR / BACKUP_DIR | Eigene, ausschließlich dieser Instanz zugängliche Verzeichnisse |
| SECRET_KEY_FILE / JWT_SECRET_KEY | Eigene zufällige Schlüssel, getrennte Secrets-Verwaltung |
| INTEGRATION_STATE_FILE | Eigene Konfiguration und Zugangsdaten |
| Backupziel | Eigener Namensraum und Zugang; verschlüsselt; getrennte Wiederherstellungsprobe |
| HTTP / Cookies / Proxy | Eigener Hostname, TLS, definierte vertrauenswürdige Proxygrenze |
| Jobs / Ressourcen | Eigene Prozesse, Speicher-/CPU-/Speicherplatzlimits, getrennte Protokolle |

Der Eigentümer ist Administrator dieser Kundeninstanz. Zugang der Hostingadministratoren zu System, Datenbanken und Backups bleibt ein privilegierter Betriebszugang und muss organisatorisch eingeschränkt und nachvollziehbar sein.

Abnahmetest mit zwei synthetischen Kundeninstanzen:
1. Gleiche Benutzernamen und absichtlich gleiche Datensatz-IDs in beiden Instanzen anlegen.
2. Token und Sessioncookie aus A müssen an B abgewiesen werden.
3. Upload-, Export-, Assistenten-, Hintergrundjob- und Backupzugriffe dürfen ausschließlich A erreichen.
4. Anwendungs- und DB-Benutzer aus A dürfen keine Verzeichnisse oder Datenbanken von B öffnen.
5. Backup A in eine dritte isolierte Instanz wiederherstellen; B muss unverändert bleiben.
6. Hostneustart, Zertifikaterneuerung, ausgeschöpfte Platte und unterbrochene Sicherung prüfen.

Die Checkliste muss in der tatsächlichen Hostingumgebung ausgeführt werden. Lokale Anwendungstests belegen keine Isolation eines späteren Hostinganbieters.
