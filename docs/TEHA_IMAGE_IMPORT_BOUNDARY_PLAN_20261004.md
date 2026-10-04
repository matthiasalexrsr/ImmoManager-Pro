# Frischer Prozess für die Bildprüfungsgrenze

Der ausgewählte TEHA-Bildprüfer darf statische Fach-/ORM-Metadaten importieren,
aber weder Laufzeitkonfiguration, aktuelle Benutzer, Providerverbindungen noch
eine neue Datenbankfabrik benötigen. Ein bestehender Testprozess kann solche
versehentlichen Abhängigkeiten durch bereits geladene Module verdecken.

Ein eigener frischer Pythonprozess blockiert deshalb die tatsächlichen
Konfigurations-, Auth-, Store-, DB-Session- und Integrationsruntime-Module sowie
neue SQLite-/SQLAlchemy-Verbindungen. Die einzige rohe SQLite-Verbindung wird
vor dieser Sperre im Test angelegt und als explizites ausgewähltes Bild in einer
read-only-Transaktion übergeben. Der vollständig abwesende L2-Bestand muss ohne
Schlüsselnachschlagen als Legacyzustand erkannt werden. Es gibt keine fremden
Dateien, Provideraufrufe oder Installationsschlüssel.

Der Test besitzt eine äußere Prozessfrist und hält seine ganze Evidenz im
eigenen Prozess. Er beweist die Import-/Absentfamily-Grenze, nicht die vollständige
Wiederherstellung oder eine externe fachliche Schreibfreigabe. Die echten
verschlüsselten Bildfälle bleiben die separate native Image-Prüfgruppe.
