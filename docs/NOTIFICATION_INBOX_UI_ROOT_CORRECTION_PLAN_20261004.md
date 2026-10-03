# Inboxoberfläche: konkrete Rootkorrekturen vor Aktivierung

Source1e2bc4e und geschlossenes Handoffa41beea sind als780011c/b17a7f0
übernommen. Globale Glocke und öffentliche Schreibroute sind unverdrahtet.
Die unabhängige erneute Quellenreview bestätigt die sechs zuvor berichteten
Vertragskorrekturen; eine Request-/Generation-Schleife im Hook ist nicht belegt.

Zwei konkrete weitere Befunde werden vor Produktänderung festgehalten:

1. loadMore verbindet zwei für sich gültige Live-Seiten ohne Obergrenze durch
   ihren aktuellen full_count. Verschwindet ein schon angezeigtes Item und
   kommt ein älteres hinzu, können zwei disjunkte Seiten jeweils2 Items und
   denselben Count3 haben. Die vereinte Anzeige hat dann4 Zeilen beiBadge3.
   Die vereinte Itemzahl muss vor Veröffentlichung geprüft werden. Dieser
   beobachtbare Livewechsel wird neutral als changed mit Reload behandelt;
   er ist kein technischer Ladefehler und kein vorgetäuschter Snapshot.
2. Die Date-Konvertierung dividiert negative BigInt-Mikrosekunden gegenNull.
   Ein tatsächlicher begrenzter Node-Aufruf aufb17a7f0 liefert
   `1969-12-31T23:59:59.999999Z → 1970-01-01T00:00:00.000Z` und
   `0099-12-31T23:59:59.999999Z → 0100-01-01T00:00:00.000Z`.
   Konvertierung nachMillisekunden muss abwärts runden; die erhaltene
   Mikrosekunden-Sortierung und der UTF8-IDvergleich bleiben unverändert.

Root ergänzt zuerst Regressionen für beide Gegenbeispiele, führt diese mit
harter eigener Node-Prozessgrenze aus und dokumentiert den tatsächlichen
Vorherzustand. Dann nur die begrenzten Korrekturen und gezielte betroffene
Model-/Hookgates; unveränderte API-/Paneltests werden einmal inRoot geprüft.
Kein Browser-/Build-/Backend-/DBprozess gehört zu diesen Clienttests. Private
Zustände bleiben an actualserverActions/freshAuth/Principalgeneration gebunden.
Keine Mark-all-/PhaseBC-Aktivierung und kein positiver nativer Serverbeleg aus
Clientmocks. Gemeinsame HTTP-/UI-/Schema-/Rechteracefreigabe folgt separat.
