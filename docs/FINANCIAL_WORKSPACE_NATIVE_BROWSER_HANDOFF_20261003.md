# D/B: tatsächliche Finanz-Browserabnahme

Die vorhandenen Browserquellen des tatsächlichen Frontend-Assistenzchats wurden
zentral übernommen und ausgeführt. Root-Quelle `017d1a8` auf K2 besitzt **1 PASS
in 13,6 s**, Gesamtlauf **15,2 s**, keine Skips. Der vorhandene Runner führte den
Produktionsbuild (716 Module), die echte Alembicmigration bis K2 und eine eigene
temporäre SQL-Installation aus. Installiertes Edge, tatsächliche native HTTP-
und Browserzugänge, synthetische Benutzer und Datensätze; keine API-Stubs oder
privaten Daten. Dies ist ein zusammenhängender Finanzfall, keine gesamte D-/B-
oder Releasefreigabe.

## Tatsächlich durchlaufener Umfang

- Portfolio-/Objekt-/Einheits-/Kontoreferenzen mit echter beschränkter Auswahl
  und verborgenem Portfolio; Geldsummen inklusive 0,10 und 0,20 exakt.
- Monats-, Kostenarten- und Objektsummen mit direkt überprüften Quellantworten.
- 50 und zehn Belegzeilen auf echten Seiten, gleiche gebundene Filter/Sourcehash,
  disjunkte IDs und exakt wiederholte erste Seite.
- Echte zusätzliche Buchung bewirkt 409; sichtbarer Konflikt, erhaltene Auswahl,
  ausdrückliches Neuladen und neue richtige Summen.
- Tatsächlicher vollständiger CSV-Download mit sämtlichen gefilterten IDs,
  ausgeschlossenen Quellen und geschütztem Formeltext; unabhängige sichtbare
  Belegseite, kein verborgenes Objekt im Export.
- Browser bei 1440, 360 und 320 Pixeln ohne Seitenüberlauf, sichtbare Aktionen,
  Tastaturbedienung und Formularfehler; tatsächliche Screenshots gespeichert.
- Wechsel zu aufgezeichneten Buchungen mit erwarteten unterschiedlichen Summen;
  echter Grantentzug blendet bisherige private Werte und Namen aus. Anschließende
  echte Referenz-/Cash-Requests sind entsprechend eingeschränkt.

## Fehler und gezielte Korrekturen

Assistenz-QA-Korrekturen `b056601`, `e011af1` und `ca0f26b` passen Tastaturpfad,
Belegzeilen- und Alertauswahl an die tatsächlichen nativen Elemente an.
Root-Quelle `58aaf3e` stoppte nach bestätigtem 409 an zwei gleich benannten
Portfolioelementen: **1 FAIL / 12,8 s**. `83c86a9` begrenzt die strenge Auswahl
auf die ausdrücklich angewendete Auswertung. Der nächste Lauf bestätigte CSV und
alle drei Bildschirmbreiten, stoppte jedoch nach **240 s** an `getByLabel` für
eine native Auswahl, die der echte Accessibilitybaum als `combobox Grundlage`
auswies. `017d1a8` verwendet genau diese tatsächliche Rolle mit exaktem Namen
und begrenzter Aktionswartezeit. Danach lief der gesamte Fall vollständig grün.
Diese beiden Root-FAILs bleiben als Gegenbelege erhalten; kein Produktfehler oder
abgeschwächter Erfolgstatus wurde daraus erfunden.

Artefakte der drei Rootläufe stehen unter
`artifacts/financial-cash-native-20261003/attempt-1`, `attempt-2` und `attempt-3`.
Jeweils eigener Backendlog, Ergebnisstatus, Fehlerkontext/Trace oder drei normale
Screenshots. Die protokollierten eigenen Server 32128, 10968 und 34044 existierten
nach dem jeweiligen normalen Runnerabschluss nicht mehr. Kein fremder Prozess
wurde beendet.

## Visuelle Nacharbeit

Alle drei erfolgreichen normalen Bilder wurden tatsächlich angesehen. Dabei
zeigten sich unvereinheitlichte Datums-/Auswahlfelder und rohe Referenzlisten.
Der ausschließlich auf die Finanzseite begrenzte CSS-Nachtrag `9ca1612` fügt
konsistente 44-Pixel-Felder, Abstände, Umbruch, sichtbare Auswahl und passend
gestaltete begrenzte Listen hinzu. Funktionen, gemeinsamer ReferenceChoice,
Backend und Daten bleiben unverändert. Dieser neuere Darstellungsstand benötigt
seine anschließende tatsächliche Browser-/Bildprüfung; die Bilder von `017d1a8`
sind ausdrücklich kein visueller Nachweis für `9ca1612`.
