# Dauerhafte IBAN-Verschlüsselung

Die SQL-Kontenspeicherung verschlüsselt `Account.iban` tatsächlich beim Schreiben und entschlüsselt beim Lesen. APIs und Formulare erhalten die Bankverbindung, SQL-Dateien und Dumps den authentifizierten Ciphertext `enc:v1:<KeyID>:<Token>`. Andere personenbezogene Felder werden dadurch nicht automatisch verschlüsselt. Der Memory-Teststore besitzt keine persistente SQL-Datei; er behält seinen bisherigen DTO-Vertrag.

Neue Schlüssel sind unabhängig von JWT, Login, TOTP und Sitzungsablauf. Ein JWT-Wechsel beeinträchtigt diese neuen Kontodaten nicht. `cryptography` ist zwingend erforderlich: es gibt keinen Klartext-Fallback und bei Entschlüsselungsfehlern keinen als IBAN zurückgegebenen Maskenwert.

## Konfiguration

Alle Geheimnisse in einer ausschließlich für den Eigentümer lesbaren Installationskonfiguration halten. Die Wartungsbefehle verwenden deren ausdrücklichen Pfad, nicht geerbte Werte eines anderen Terminals.

- `ENCRYPTION_KEY`: 32 zufällige Bytes in kanonischem Base64url mit Padding, für einen einzelnen Schlüssel.
- Alternativ `ENCRYPTION_KEYRING`: JSON-Objekt `{KeyID: Base64urlSchlüssel}` und `ENCRYPTION_ACTIVE_KEY_ID`. Einzelschlüssel und Schlüsselring dürfen nicht gleichzeitig gefüllt sein. KeyIDs bestehen aus 1–64 Buchstaben, Ziffern, Unterstrichen oder Bindestrichen.
- `ENCRYPTION_INDEX_KEY`: separater stabiler 32-Byte-Schlüssel. Er erzeugt den HMAC-Vergleichswert für die eindeutige IBAN; **bei einer Verschlüsselungsschlüsselrotation unverändert behalten**.
- `ENCRYPTION_LEGACY_JWT_KEYS`: optionales JSON-Array früherer JWT-Geheimnisse ausschließlich zum Lesen alter `enc:`-Fernet-Daten. Das aktuelle `JWT_SECRET_KEY` wird ebenfalls nur für diesen Altbestand berücksichtigt. Neue Ciphertexts verwenden es nicht.

AES-SIV mit HKDF-64-Byte-Ableitung und authentifiziertem Feld-/Versions-/KeyID-Kontext bewahrt die Authentizität. Sein deterministischer Modus macht gleiche Feldwerte unter demselben Schlüssel erkennbar; der unabhängige HMAC-Index schützt die Eindeutigkeit auch über unterschiedliche KeyIDs. Für den Vergleich werden Leerzeichen entfernt und Buchstaben großgeschrieben; der gespeicherte Feldtext bleibt beim Roundtrip erhalten. Siehe [cryptography AES-SIV](https://cryptography.io/en/stable/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESSIV) und [SQLAlchemy TypeDecorator](https://docs.sqlalchemy.org/en/20/core/custom_types.html#sqlalchemy.types.TypeDecorator).

## Vorhandene Installation vorbereiten

Schema-Upgrade `m1a2b3c4d5e6` ergänzt die Vergleichsspalte und ihren UNIQUE-Index; es verschlüsselt vorhandene Konten noch nicht. Alte Klartext- und JWT-Fernet-Felder bleiben lesbar. Account-CRUD mit unindexiertem IBAN-Bestand wird mit `ENCRYPTION_MIGRATION_REQUIRED` blockiert, bis die ausdrückliche Migration erfolgt ist. Andere Daten, Zahlungsverläufe und bereits vorhandene Kontostände werden dabei nicht rückwirkend geändert.

Neue Geheimnisse niemals als Befehlsargument, im Chat oder in Protokollen eingeben. Das folgende Kommando erzeugt eine **neue** geschützte JSON-Datei; vorhandene Dateien werden nicht überschrieben:

```powershell
python -m backend.iban_maintenance create-keyring --output C:\Privat\iban-keys.json
```

Für frühere JWT-Geheimnisse `--legacy-secret-prompt` (getpass) oder `--legacy-secret-stdin` verwenden. Bei einer existierenden Schlüsselkonfiguration `--existing-config C:\Privat\installation.env` angeben: vorhandene Schlüssel, Legacy-Geheimnisse und der Indexschlüssel bleiben erhalten. Eine neue KeyID verhindert das versehentliche Überschreiben eines alten Schlüssels.

Status und Vorschau lesen die tatsächlichen Zeilen. Eine Vorschau schreibt keine Kontodaten; temporäre Prüftabellen bleiben innerhalb der Wartungstransaktion:

```powershell
python -m backend.iban_maintenance status --config C:\Privat\installation.env
python -m backend.iban_maintenance rotate --config C:\Privat\installation.env --key-config C:\Privat\iban-keys.json --dry-run
```

## Sicherung, Migration und spätere Rotation

1. Anwendung und sämtliche anderen Schreiber stoppen; Wartungszeit einplanen.
2. Eine vollständige Sicherung mit der bestehenden SQLite-/PostgreSQL-Sicherung erstellen und in eine **separate** Datenbank wiederherstellen. Anmeldung, TOTP, Belege und Dateien dort prüfen. Die Wartung verlangt kein bestimmtes Archivformat.
3. Aus der geschützten Konfiguration dieser tatsächlich wiederhergestellten Datenbank einen Nachweis erzeugen. Dieser überprüft das vollständige deklarierte Schema, SQLite-Integrität, die Entschlüsselbarkeit der Konto-IBANs und ihren gespeicherten Snapshot. Er ersetzt nicht die Prüfung anderer Inhalte eines fremden Archivformats.

```powershell
python -m backend.iban_maintenance backup-proof --config C:\Privat\wiederhergestellt.env --output C:\Privat\iban-backup-proof.json
python -m backend.iban_maintenance rotate --config C:\Privat\installation.env --key-config C:\Privat\iban-keys.json --backup-proof C:\Privat\iban-backup-proof.json --offline
```

Unter der Datenbanksperre muss der Nachweis exakt zum aktuellen Kontosnapshot passen. Die aktuelle Installation selbst wird als angebliche Sicherung abgewiesen. Duplikate, falsche Schlüssel, fehlende Schemafelder oder eine zwischenzeitliche Kontenänderung brechen die Operation ab. Jede IBAN wird in begrenzten Blöcken vorbereitet; eine temporäre UNIQUE-Tabelle prüft kanonische Duplikate. Erst danach werden alle IBAN-Speicherfelder in **einer** Transaktion übernommen und erneut entschlüsselt geprüft. Auch ein Fehler nach dem tatsächlichen UPDATE rollt den gesamten Job zurück. Kontostände, Belege, sonstige Kontoattribute und fachliche `updated_at`-Revisionen bleiben erhalten.

SQLite `BEGIN IMMEDIATE` und PostgreSQL-Tabellensperren koordinieren Wartung und Account-CRUD über unabhängige Prozesse. Die Wartung ersetzt nicht das vorherige Stoppen der Anwendung. Nach erfolgreichem Commit die neue vollständige Schlüsselkonfiguration in der geschützten Runtime-Konfiguration aktivieren und die Anwendung neu starten. Keine automatische `.env`-Überschreibung durch den Wartungsbefehl.

Für spätere Rotation eine neue Datei mit `create-keyring --existing-config ... --key-id 2030` erzeugen, erneut vollständig sichern/wiederherstellen und dieselben Schritte ausführen. **Alte Verschlüsselungs- und Legacy-Schlüssel niemals entfernen, solange historische Sicherungen sie benötigen.** Der Befehl entfernt keine Schlüssel. Nach einem Absturz liefert `status` den tatsächlichen alten oder vollständig neuen Zustand; es existiert kein teilweise committed Rotationsjob.

## Fehler und Wiederherstellung

`ENCRYPTION_KEY_MISSING`, `ENCRYPTION_KEY_UNAVAILABLE`, `ENCRYPTION_AUTHENTICATION_FAILED`, `ENCRYPTION_LEGACY_KEY_UNAVAILABLE` und `ENCRYPTION_INDEX_KEY_MISMATCH` verlangen die ursprüngliche vollständige Schlüsselkonfiguration. Keine Bankverbindung anhand eines Fehler-/Maskenwerts speichern. Der API-Handler meldet HTTP 503 mit konkretem `error.code`, ohne Schlüssel, Feldwerte oder Ciphertexts zu protokollieren.

Die vollständige Wiederherstellung muss `ENCRYPTION_*`, ursprüngliches JWT-/TOTP-Geheimnis, Benutzer und alle finanziellen Belege gemeinsam zurückbringen. Die Crypto-Prüfung arbeitet ausschließlich mit der Konfiguration der Sicherung, niemals mit einem zufälligen Schlüssel des aktuellen Terminals. Schema-Downgrade wird vor jedem DDL-Schritt abgelehnt, sobald verschlüsselte Konto- oder Vergleichsdaten vorhanden sind; für einen Programmrollback eine überprüfte vollständige Sicherung verwenden.
