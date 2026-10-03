# Begrenzte Familienabfrage im ausgewählten SQLite-Abbild

Die unabhängige Prüfung hat zwei gemeinsame SQLite-Schemahelfer gefunden, die
sämtliche Tabellennamen des Katalogs in ein Python-Set übertragen. Ihre Aufrufer
benötigen lediglich die beiden Namen ihrer jeweiligen TEHA- oder Originalfamilie.
Ein großer irrelevanter Katalog darf weder abgeschnitten werden noch den Speicher
der Prüfung unnötig belasten.

Die SQL-Abfragen werden daher auf die festen Familiennamen beschränkt. Die
atomare Vollständigkeitsprüfung und die Rückgabe bei vollständig fehlender
Familie behalten ihre Semantik. PostgreSQL, Index- und Spaltenprüfung werden in
diesem Paket nicht geändert. Die zusätzliche temporäre Schattierung und native
NOT-NULL-Prüfung erfolgen in einem separat reproduzierten Image-Paket.

Die gemeinsame Prüfung erfolgt anschließend mit tatsächlichen ausgewählten
TEHA-Bildern und der bestehenden Originalvalidierung. Dieser Schritt aktiviert
keine Migration, keinen externen Schreibvorgang und keinen Live-Import.
